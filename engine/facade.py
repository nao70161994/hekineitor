import os
import threading
import time
from analytics import build_quality_report
from config import get_fetish_log_path
from matrix_service import collect_matrix_updates, matrix_validation_report
from storage import DATA_DIR, DATABASE_URL, HAS_PSYCOPG2
from storage import atomic_write_json, data_path, load_json_file
from storage import get_conn as _storage_get_conn
from storage import put_conn as _storage_put_conn
from storage import use_db as _storage_use_db
from work_utils import parse_work_item, parse_works_list, work_title
from . import admin_reports as engine_admin_reports
from . import compound_works as engine_compound_works
from . import correlation as engine_correlation
from . import db as engine_db
from . import inference as engine_inference
from . import learning as engine_learning
from . import mutations as engine_mutations
from . import persistence as engine_persistence
from . import question_selection as engine_question_selection
from . import reporting as engine_reporting
from . import runtime as engine_runtime
from . import stats as engine_stats
from .constants import (
    AXIS_INDIRECT_BONUS,
    EARLY_RANDOM_DEPTH,
    EARLY_RANDOM_TOP_K,
    FOCUS_THRESHOLD,
    FOCUS_TOP_N,
    PLAYER_FETISH_BASE_ID,
    PSEUDO,
    UCB_EXPLORE_C,
)

try:
    import psycopg2.extras
except ImportError:
    pass

from .data import (
    DOMAIN_PRIORS,
    FETISH_PRIOR_WEIGHTS,
    FETISH_RELATIONS,
    QUESTION_AXES,
)
def _use_db():
    return _storage_use_db()


_COMPOUND_WORKS: dict = {}
_compound_works_loaded = False
_COMPOUND_WORKS_PATH = data_path('compound_works.json')

def _load_compound_works():
    global _COMPOUND_WORKS, _compound_works_loaded
    loaded = engine_compound_works.load_cache(
        loaded=_compound_works_loaded,
        load_fn=load_json_file,
    )
    if loaded is not None:
        _COMPOUND_WORKS = loaded
        _compound_works_loaded = True

def _save_compound_works():
    engine_compound_works.save_cache(_COMPOUND_WORKS_PATH, _COMPOUND_WORKS, atomic_write_json)

def get_compound_works(id_a: int, id_b: int) -> list:
    """2つの性癖IDペアに特化した作品リストを返す。なければ空リスト。"""
    _load_compound_works()
    return engine_compound_works.get_works(_COMPOUND_WORKS, id_a, id_b)

def list_compound_works() -> list:
    """全ペアをリスト形式で返す。[{key, id_a, id_b, works}, ...]"""
    _load_compound_works()
    return engine_compound_works.serialize_compound_works(_COMPOUND_WORKS)

def set_compound_works(id_a: int, id_b: int, works: list) -> str:
    """ペアの作品リストを追加・更新する。キーを返す。"""
    _load_compound_works()
    key = engine_compound_works.set_works(_COMPOUND_WORKS, id_a, id_b, works)
    _save_compound_works()
    return key

def delete_compound_works(id_a: int, id_b: int) -> bool:
    """ペアを削除する。存在しなければFalse。"""
    _load_compound_works()
    if not engine_compound_works.delete_works(_COMPOUND_WORKS, id_a, id_b):
        return False
    _save_compound_works()
    return True


def _get_conn():
    return _storage_get_conn()

def _put_conn(conn):
    _storage_put_conn(conn)


def _build_initial_matrix(nf, nq):
    alpha = 2.0
    yes   = [[alpha]       * nq for _ in range(nf)]
    total = [[alpha * 2.0] * nq for _ in range(nf)]
    for f, q, p in DOMAIN_PRIORS:
        yes[f][q]   = p * PSEUDO
        total[f][q] = float(PSEUDO)
    return yes, total


_MATRIX_RELOAD_INTERVAL  = 5.0   # 複数worker対応: DBからmatrixをリロードする間隔(秒)
_DYNAMIC_PRIOR_INTERVAL  = 60.0  # 動的事前確率キャッシュの更新間隔(秒)

class Engine:
    def __init__(self):
        self._lock = threading.RLock()
        self.questions = self._load_json('questions.json')
        if _use_db():
            self._ensure_db()
            self.fetishes = self._load_fetishes_from_db()
            self.matrix   = self._load_from_db()
        else:
            self.fetishes = self._load_json('fetishes.json')
            self.matrix   = self._load_matrix_file()
        self.disabled_questions    = self._load_disabled_questions()
        self._matrix_last_loaded   = time.monotonic()
        self._dynamic_prior_cache  = {}
        self._dynamic_prior_time   = 0.0
        self._disc_cache           = []   # [disc_value per question]
        self._disc_cache_time      = 0.0
        self._corr_cache           = []   # get_correlation_stats のキャッシュ
        self._corr_cache_time      = 0.0
        self.config                = self._load_config()

    # ── JSON ローカル ──────────────────────────────────────
    def _load_json(self, fname):
        return load_json_file(fname)

    def _valid_matrix_shape(self, matrix, nf, nq):
        return engine_persistence.valid_matrix_shape(matrix, nf, nq)

    def _load_matrix_file(self):
        return engine_persistence.load_matrix_file(
            os.path.join(DATA_DIR, 'matrix.json'),
            self.fetishes,
            self.questions,
            init_matrix=self._init_matrix_file,
        )

    def _init_matrix_file(self):
        matrix = engine_persistence.initial_matrix(
            self.fetishes,
            self.questions,
            build_initial_matrix=_build_initial_matrix,
            learned_priors_path=os.path.join(DATA_DIR, 'learned_priors.json'),
            pseudo=PSEUDO,
        )
        self.matrix = matrix
        self._save_matrix_file()
        return matrix

    def _atomic_write(self, path, data, **kwargs):
        atomic_write_json(path, data, **kwargs)

    def _matrix_snapshot(self):
        with self._lock:
            return {
                'yes': [list(row) for row in self.matrix.get('yes', [])],
                'total': [list(row) for row in self.matrix.get('total', [])],
            }

    def _save_matrix_file(self):
        engine_persistence.save_matrix_file(
            os.path.join(DATA_DIR, 'matrix.json'),
            self._matrix_snapshot(),
            atomic_write=self._atomic_write,
        )

    def _save_async(self, all_updates, idx_to_db_id):
        """バックグラウンドスレッドで matrix 保存を行う（レスポンスをブロックしない）。"""
        if _use_db():
            t = threading.Thread(target=self._save_to_db, args=(all_updates, idx_to_db_id), daemon=True)
            t.start()
        else:
            self._save_matrix_file()

    def _save_fetishes_file(self):
        engine_persistence.save_fetishes_file(
            os.path.join(DATA_DIR, 'fetishes.json'),
            self.fetishes,
            atomic_write=self._atomic_write,
        )

    # ── PostgreSQL ─────────────────────────────────────────
    def _ensure_db(self):
        engine_db.ensure_schema(
            self,
            get_conn=_get_conn,
            put_conn=_put_conn,
            execute_values=psycopg2.extras.execute_values,
            player_base_id=PLAYER_FETISH_BASE_ID,
            build_initial_matrix=_build_initial_matrix,
        )

    def _load_fetishes_from_db(self):
        return engine_db.load_fetishes(get_conn=_get_conn, put_conn=_put_conn)

    def _seed_db(self, cur, fetishes=None):
        if fetishes is None:
            fetishes = self.fetishes
        engine_db.seed_matrix(
            cur,
            fetishes,
            len(self.questions),
            execute_values=psycopg2.extras.execute_values,
            build_initial_matrix=_build_initial_matrix,
        )

    def _load_from_db(self):
        return engine_db.load_matrix(self.fetishes, self.questions, get_conn=_get_conn, put_conn=_put_conn)

    def _increment_stat(self, key):
        if _use_db():
            engine_db.increment_stat(key, get_conn=_get_conn, put_conn=_put_conn)
        else:
            path = os.path.join(DATA_DIR, 'stats.json')
            engine_stats.increment_counter_file(path, key, lock=self._lock, atomic_write=self._atomic_write)

    def _record_daily_stat(self, key):
        from datetime import date as _date
        today = _date.today().isoformat()
        if _use_db():
            engine_db.record_daily_stat(key, today, get_conn=_get_conn, put_conn=_put_conn)
        else:
            path = os.path.join(DATA_DIR, 'stats_history.json')
            engine_stats.record_daily_counter_file(path, key, today, lock=self._lock, atomic_write=self._atomic_write)

    def _increment_learn_count(self):
        self._increment_stat('learn_count')
        self._record_daily_stat('learn')

    def increment_play_count(self):
        self._increment_stat('play_count')
        self._record_daily_stat('play')

    def get_stats(self):
        keys = ('play_count', 'learn_count')
        if _use_db():
            return engine_db.load_stats(keys, get_conn=_get_conn, put_conn=_put_conn)
        path = os.path.join(DATA_DIR, 'stats.json')
        return engine_stats.counters_from_file(path, keys)

    def get_stats_history(self, days=30):
        """過去N日間の日別プレイ・学習回数を [{date, play, learn}, ...] で返す。"""
        from datetime import date as _date, timedelta
        today = _date.today()
        date_range = [(today - timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]
        if _use_db():
            return engine_db.load_stats_history(date_range, get_conn=_get_conn, put_conn=_put_conn)
        path = os.path.join(DATA_DIR, 'stats_history.json')
        return engine_stats.history_rows_from_file(path, date_range)

    def get_recent_fetish_ranking(self, days=7, top_n=10):
        """過去N日間に正解/外れフィードバックが多かった性癖TOP n件を返す。"""
        from datetime import date as _date, timedelta
        today = _date.today()
        since = (today - timedelta(days=days - 1)).isoformat()
        totals = {}  # fetish_id -> {'correct': int, 'wrong': int}
        if _use_db():
            totals = engine_db.load_feedback_totals(since, get_conn=_get_conn, put_conn=_put_conn)
        else:
            path = os.path.join(DATA_DIR, 'stats_history.json')
            raw = engine_stats.read_json_path(path, {})
            date_range = [(today - timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]
            totals = engine_reporting.fetish_feedback_totals_from_history(raw, date_range)
        id_to_name = {f['id']: f['name'] for f in self.fetishes}
        return engine_reporting.format_recent_fetish_ranking(totals, id_to_name, top_n)

    def get_fetish_history(self, fetish_db_id, days=30):
        """指定性癖の日別正解/外れ件数を [{date, correct, wrong}, ...] で返す。"""
        from datetime import date as _date, timedelta
        today = _date.today()
        date_range = [(today - timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]
        ck = f'f_correct_{fetish_db_id}'
        wk = f'f_wrong_{fetish_db_id}'
        if _use_db():
            raw = engine_db.load_fetish_history(date_range, ck, wk, get_conn=_get_conn, put_conn=_put_conn)
        else:
            path = os.path.join(DATA_DIR, 'stats_history.json')
            raw = engine_stats.read_json_path(path, {})
        return engine_reporting.fetish_history_rows(raw, date_range, ck, wk)

    def get_quality_event_summary(self, days=30):
        """診断品質用の内部イベントを過去N日分集計して返す。"""
        from datetime import date as _date, timedelta
        today = _date.today()
        days = max(1, int(days or 30))
        date_range = [(today - timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]
        keys = (
            'q_low_conf_guess',
            'q_low_conf_correct',
            'q_low_conf_wrong',
            'q_additional_guess',
            'q_additional_correct',
            'q_additional_wrong',
            'q_additional_question',
        )
        totals = {key: 0 for key in keys}
        if _use_db():
            totals = engine_db.load_quality_event_totals(date_range, keys, get_conn=_get_conn, put_conn=_put_conn)
        else:
            path = os.path.join(DATA_DIR, 'stats_history.json')
            raw = engine_stats.read_json_path(path, {})
            for d in date_range:
                day = raw.get(d, {})
                for key in keys:
                    totals[key] += int(day.get(key, 0) or 0)
        return engine_reporting.quality_event_summary_from_totals(totals, days)

    # ── 質問無効化フラグ ───────────────────────────────────
    def _load_disabled_questions(self):
        if _use_db():
            return engine_db.load_disabled_questions(get_conn=_get_conn, put_conn=_put_conn)
        else:
            path = os.path.join(DATA_DIR, 'question_flags.json')
            return engine_stats.load_disabled_questions_file(path)

    def _save_disabled_questions(self):
        if _use_db():
            engine_db.save_disabled_questions(self.disabled_questions, get_conn=_get_conn, put_conn=_put_conn)
        else:
            path = os.path.join(DATA_DIR, 'question_flags.json')
            engine_stats.save_disabled_questions_file(path, self.disabled_questions, atomic_write=self._atomic_write)

    def toggle_question_disabled(self, q_id):
        """無効化/有効化を切り替え。True=無効化後の状態を返す。"""
        with self._lock:
            if q_id in self.disabled_questions:
                self.disabled_questions.discard(q_id)
                result = False
            else:
                self.disabled_questions.add(q_id)
                result = True
        self._save_disabled_questions()
        return result

    # ── 診断ログ ──────────────────────────────────────────
    def _increment_fetish_log(self, fetish_db_id, col):
        if col not in ('guessed', 'correct', 'wrong'):
            raise ValueError(f'不正な列名: {col}')
        if _use_db():
            engine_db.increment_fetish_log(fetish_db_id, col, get_conn=_get_conn, put_conn=_put_conn)
        else:
            path = get_fetish_log_path()
            engine_stats.increment_fetish_log_file(
                path, fetish_db_id, col, lock=self._lock, atomic_write=self._atomic_write
            )

    def log_guessed(self, fetish_db_id):
        self._increment_fetish_log(fetish_db_id, 'guessed')

    def log_correct(self, fetish_db_id):
        self._increment_fetish_log(fetish_db_id, 'correct')
        self._record_daily_stat('correct')
        self._record_daily_stat(f'f_correct_{fetish_db_id}')

    def log_wrong(self, fetish_db_id):
        self._increment_fetish_log(fetish_db_id, 'wrong')
        self._record_daily_stat('wrong')
        self._record_daily_stat(f'f_wrong_{fetish_db_id}')

    def get_fetish_log(self):
        """全性癖のログを {fetish_db_id: {guessed, correct, wrong}} で返す。"""
        if _use_db():
            return engine_db.load_fetish_log(get_conn=_get_conn, put_conn=_put_conn)
        else:
            path = get_fetish_log_path()
            return engine_stats.load_fetish_log_file(path)


    def _save_to_db(self, all_updates, idx_to_db_id=None):
        if not all_updates:
            return
        # idx_to_db_id はロック内で取得したスナップショット。
        # None の場合は呼び出し元が古い方式なのでフォールバック（ロック外アクセス）。
        engine_db.save_matrix_updates(
            all_updates,
            idx_to_db_id,
            self.fetishes,
            get_conn=_get_conn,
            put_conn=_put_conn,
        )

    # ── パラメータ設定 ────────────────────────────────────
    _CONFIG_DEFAULTS = {
        'guess_threshold': 0.75,
        'compound_ratio':  0.55,
        'triple_ratio':    0.45,
        'ucb_explore_c':   0.05,
        'focus_threshold': 0.40,
    }

    def _load_config(self):
        return engine_db.load_config(
            self._CONFIG_DEFAULTS,
            use_db=_use_db,
            get_conn=_get_conn,
            put_conn=_put_conn,
            config_path=os.path.join(DATA_DIR, 'config.json'),
            read_json=engine_stats.read_json_path,
        )

    def set_config(self, key, value):
        if key not in self._CONFIG_DEFAULTS:
            raise ValueError(f'未知のパラメータ: {key}')
        fval = float(value)
        self.config[key] = fval
        engine_db.save_config_value(
            key,
            fval,
            use_db=_use_db,
            get_conn=_get_conn,
            put_conn=_put_conn,
            config_path=os.path.join(DATA_DIR, 'config.json'),
            read_json=engine_stats.read_json_path,
            atomic_write=self._atomic_write,
        )

    # ── disc キャッシュ（学習重みスケーリング用） ──────────
    _DISC_CACHE_TTL = 120.0  # 2分ごとに再計算

    def _get_disc_scales(self):
        now = time.monotonic()
        if self._disc_cache and now - self._disc_cache_time < self._DISC_CACHE_TTL:
            return self._disc_cache
        scales = engine_runtime.disc_scales(
            len(self.fetishes),
            len(self.questions),
            probability=self._prob,
        )
        self._disc_cache      = scales
        self._disc_cache_time = now
        return scales

    # ── 複数Worker対応: DBからmatrixをTTLリロード ──────────
    def _reload_matrix_if_stale(self):
        if not _use_db():
            return
        now = time.monotonic()
        if now - self._matrix_last_loaded < _MATRIX_RELOAD_INTERVAL:
            return
        with self._lock:
            if time.monotonic() - self._matrix_last_loaded < _MATRIX_RELOAD_INTERVAL:
                return
            self.matrix = self._load_from_db()
            self._matrix_last_loaded = time.monotonic()

    # ── 動的事前確率（診断ログから自動更新） ──────────────
    def _get_dynamic_prior_weights(self):
        now = time.monotonic()
        if now - self._dynamic_prior_time < _DYNAMIC_PRIOR_INTERVAL:
            return self._dynamic_prior_cache
        log = self.get_fetish_log()
        if not log:
            self._dynamic_prior_time = now
            return self._dynamic_prior_cache
        weights = engine_runtime.dynamic_prior_weights(self.fetishes, log, FETISH_PRIOR_WEIGHTS)
        self._dynamic_prior_cache = weights
        self._dynamic_prior_time  = now
        return weights

    def get_top_questions_per_fetish(self, top_n=5):
        """各性癖について P(yes) が高い/低い質問を返す（DOMAIN_PRIORS整備の参考用）。"""
        result = []
        nq = len(self.questions)
        for fi, f in enumerate(self.fetishes):
            probs = [(q, self._prob(fi, q)) for q in range(nq)]
            probs.sort(key=lambda x: x[1], reverse=True)
            high = [{'q_id': q, 'text': self.questions[q]['text'], 'p': round(p, 3)}
                    for q, p in probs[:top_n]]
            low  = [{'q_id': q, 'text': self.questions[q]['text'], 'p': round(p, 3)}
                    for q, p in probs[-top_n:]]
            result.append({'fetish_id': f['id'], 'fetish_name': f['name'],
                           'high': high, 'low': low})
        return result

    # ── 推論 ───────────────────────────────────────────────
    def _prob(self, f, q):
        return engine_inference.probability(self, f, q)

    def posteriors(self, answers):
        return engine_inference.posteriors(self, answers, fetish_prior_weights=FETISH_PRIOR_WEIGHTS)

    def _question_axis(self, q):
        return engine_question_selection.question_axis(q, QUESTION_AXES)

    def best_question(self, answers, asked, idk_streak=0):
        return engine_question_selection.best_question(
            self,
            answers,
            asked,
            idk_streak=idk_streak,
            question_axes=QUESTION_AXES,
            focus_threshold_default=FOCUS_THRESHOLD,
            ucb_explore_c=UCB_EXPLORE_C,
            focus_top_n=FOCUS_TOP_N,
            early_random_depth=EARLY_RANDOM_DEPTH,
            early_random_top_k=EARLY_RANDOM_TOP_K,
            axis_indirect_bonus=AXIS_INDIRECT_BONUS,
        )

    def best_disambiguating_question(self, answers, asked, candidate_count=3, idk_streak=0):
        return engine_question_selection.best_disambiguating_question(
            self,
            answers,
            asked,
            candidate_count=candidate_count,
            idk_streak=idk_streak,
        )

    def get_matrix_heatmap(self, n_fetishes=20, n_questions=20):
        """上位N性癖×上位N質問の P(yes) ヒートマップデータを返す。"""
        return engine_admin_reports.matrix_heatmap(self, n_fetishes=n_fetishes, n_questions=n_questions)

    def get_learning_stats(self):
        return engine_admin_reports.learning_stats(self, domain_priors=DOMAIN_PRIORS, pseudo=PSEUDO)

    def get_question_stats(self):
        """各質問の識別力を返す（識別力 = 各性癖でP(yes)が0.5からどれだけ離れているかの平均）。"""
        return engine_admin_reports.question_stats(self)

    def get_axis_stats(self):
        """QUESTION_AXES別の質問数・平均disc・無効化数を返す。"""
        return engine_admin_reports.axis_stats(self, question_axes=QUESTION_AXES)

    def fetish_similarity(self, id_a, id_b):
        """2つの性癖のP(yes)ベクトルのコサイン類似度と差異が大きい質問TOP5を返す。"""
        return engine_admin_reports.fetish_similarity(self, id_a, id_b)

    _CORR_CACHE_TTL = 300.0  # 相関キャッシュ有効期間（秒）

    def get_correlation_stats(self, top_n=30):
        """質問ベクトル間のコサイン類似度を計算し、上位ペアを返す（5分TTLキャッシュ）。"""
        return engine_correlation.correlation_stats(
            self, top_n=top_n, now=time.monotonic(), ttl=self._CORR_CACHE_TTL
        )

    def get_quality_report(self):
        """診断品質改善に使う要注意項目を返す。"""
        return build_quality_report(self)

    def top_guess(self, answers, n=1):
        return engine_inference.top_guess(self, answers, n=n)

    def get_answer_contributions(self, answers, fetish_idx, top_n=3):
        return engine_inference.answer_contributions(self, answers, fetish_idx, top_n=top_n)

    def detect_contradictions(self, answers):
        """高相関な質問ペアで逆方向の回答があれば最大2件返す。"""
        return engine_correlation.detect_contradictions(self, answers)

    def learn(self, answers, fetish_idx, strength_factor=1.0):
        return engine_learning.learn(self, answers, fetish_idx, strength_factor=strength_factor, pseudo=PSEUDO)

    def learn_cooccurrence(self, answers, idx_a, idx_b, factor=0.25):
        return engine_learning.learn_cooccurrence(self, answers, idx_a, idx_b, factor=factor, pseudo=PSEUDO)

    def learn_near_miss(self, answers, fetish_idx, strength_factor=1.0):
        return engine_learning.learn_near_miss(
            self, answers, fetish_idx, strength_factor=strength_factor, pseudo=PSEUDO
        )

    def learn_negative(self, answers, fetish_idx, strength_factor=1.0):
        return engine_learning.learn_negative(
            self, answers, fetish_idx, strength_factor=strength_factor, pseudo=PSEUDO
        )

    def _learn_silent(self, answers, fetish_idx, cold_start=False):
        """learn() without incrementing learn_count (used for initial boost).
        cold_start=True で蓄積データによる減衰を無効化（新規追加性癖の cold start 対応）。"""
        return engine_learning.learn_silent(self, answers, fetish_idx, cold_start=cold_start, pseudo=PSEUDO)

    def add_fetish(self, name, desc, answers):
        """新しい性癖をDBに登録する（学習はしない）。返り値は (array_idx, db_id)。
        学習は完了確定時に boost_learn_new() を別途呼ぶ。"""
        nq = len(self.questions)
        alpha = 2.0

        # 現在の回答から最も確率の高い既存性癖をテンプレートに自動選択
        probs = self.posteriors(answers)
        auto_template = int(max(range(len(probs)), key=lambda i: probs[i])) if probs else None

        with self._lock:
            array_idx = len(self.fetishes)
            if auto_template is not None and 0 <= auto_template < array_idx:
                new_yes   = list(self.matrix['yes'][auto_template])
                new_total = list(self.matrix['total'][auto_template])
            else:
                new_yes   = [alpha] * nq
                new_total = [alpha * 2.0] * nq

            if _use_db():
                db_id = engine_db.insert_fetish_with_matrix(
                    name,
                    desc,
                    new_yes,
                    new_total,
                    get_conn=_get_conn,
                    put_conn=_put_conn,
                    execute_values=psycopg2.extras.execute_values,
                    player_base_id=PLAYER_FETISH_BASE_ID,
                )
            else:
                db_id = engine_mutations.next_player_fetish_id(self.fetishes, PLAYER_FETISH_BASE_ID)

            array_idx = engine_mutations.append_fetish(
                self.fetishes, self.matrix, db_id=db_id, name=name, desc=desc, yes_row=new_yes, total_row=new_total
            )

            if not _use_db():
                self._save_fetishes_file()

        return array_idx, db_id

    def boost_learn_new(self, fetish_idx, answers):
        """新規追加時の初期ブースト：cold_start で _learn_silent × 5 + learn × 1。
        cold_start=True により蓄積データの減衰を無視し、回答済みの質問の値を確実に動かす。"""
        for _ in range(5):
            self._learn_silent(answers, fetish_idx, cold_start=True)
        self.learn(answers, fetish_idx)

    def index_of(self, db_id):
        """DB id から配列インデックスを取得する。見つからなければ None。"""
        return next((i for i, f in enumerate(self.fetishes) if f['id'] == db_id), None)

    def merge_fetishes(self, id_keep, id_remove, new_name=None, new_desc=None):
        """id_remove の性癖を id_keep にマージ（matrixを加算、id_remove を削除）。"""
        with self._lock:
            idx_keep = self.index_of(id_keep)
            idx_rm   = self.index_of(id_remove)
            if idx_keep is None or idx_rm is None or id_keep == id_remove:
                return False
            keep_name, keep_desc = engine_mutations.merge_fetish_rows(
                self.fetishes, self.matrix, idx_keep, idx_rm, new_name=new_name, new_desc=new_desc
            )
            if _use_db():
                engine_db.merge_fetish_rows_db(
                    id_keep,
                    id_remove,
                    new_name=new_name,
                    new_desc=new_desc,
                    keep_name=keep_name,
                    keep_desc=keep_desc,
                    get_conn=_get_conn,
                    put_conn=_put_conn,
                )
            else:
                self._save_fetishes_file()
                self._save_matrix_file()
                log_path = get_fetish_log_path()
                log = engine_stats.read_json_path(log_path, {})
                engine_mutations.merge_log_entries(log, id_keep, id_remove)
                self._atomic_write(log_path, log)
        return True

    def edit_question(self, q_idx, text):
        """質問テキストをインメモリ・questions.json に反映する。"""
        if q_idx < 0 or q_idx >= len(self.questions):
            return False
        text = text.strip()
        if not text:
            return False
        with self._lock:
            self.questions[q_idx]['text'] = text
            engine_persistence.save_questions_file(
                os.path.join(DATA_DIR, 'questions.json'),
                self.questions,
                atomic_write=self._atomic_write,
            )
        return True

    def _collect_matrix_updates(self, matrix_rows: list) -> tuple[dict, dict]:
        return collect_matrix_updates(self.fetishes, self.questions, matrix_rows)

    def validate_matrix_rows(self, matrix_rows: list) -> dict:
        """matrix import の内容を保存せずに検証し、反映対象件数を返す。"""
        return matrix_validation_report(self.fetishes, self.questions, matrix_rows)

    def import_matrix(self, matrix_rows: list) -> int:
        """matrix_rows（export_matrixと同形式）でmatrixを上書き復元する。返り値は反映行数。"""
        updates, _meta = self._collect_matrix_updates(matrix_rows)
        with self._lock:
            for fi, qs in updates.items():
                for qi, y, t in qs:
                    self.matrix['yes'][fi][qi]   = y
                    self.matrix['total'][fi][qi] = t
        if _use_db() and updates:
            idx_map = {f['id']: i for i, f in enumerate(self.fetishes)}
            self._import_to_db(updates, idx_map)
        elif not _use_db():
            self._save_matrix_file()
        return sum(len(v) for v in updates.values())

    def _import_to_db(self, updates: dict, idx_map: dict):
        """import_matrix 専用: yes/total を加算ではなく上書きでDB保存。"""
        engine_db.import_matrix_rows(
            updates,
            idx_map,
            get_conn=_get_conn,
            put_conn=_put_conn,
            execute_values=psycopg2.extras.execute_values,
        )

    def edit_fetish(self, fetish_id, name=None, desc=None, works=None):
        """性癖の名前・説明文・作品リストを更新する。変更したフィールドのみ渡す。"""
        with self._lock:
            idx = self.index_of(fetish_id)
            if idx is None:
                return False
            engine_mutations.apply_fetish_edits(self.fetishes[idx], name=name, desc=desc, works=works)
            if _use_db():
                engine_db.update_fetish_fields(
                    fetish_id,
                    name=name,
                    desc=desc,
                    works=works,
                    get_conn=_get_conn,
                    put_conn=_put_conn,
                )
            else:
                self._save_fetishes_file()
        return True

    def delete_fetish(self, fetish_id):
        """プレイヤー追加性癖（ID >= PLAYER_FETISH_BASE_ID）を削除する。"""
        with self._lock:
            idx = next((i for i, f in enumerate(self.fetishes) if f['id'] == fetish_id), None)
            if idx is None or self.fetishes[idx]['id'] < PLAYER_FETISH_BASE_ID:
                return False
            engine_mutations.delete_fetish_at(self.fetishes, self.matrix, idx)
            if _use_db():
                engine_db.delete_fetish_rows(fetish_id, get_conn=_get_conn, put_conn=_put_conn)
            else:
                self._save_fetishes_file()
                self._save_matrix_file()
        return True

    def promote_fetish(self, old_id):
        """プレイヤー追加性癖（ID≥10000）をシード性癖に格上げ（次の空きIDを割り当て）。
        DB・matrix・fetish_log のIDを全て更新する。返り値は新ID、失敗時None。"""
        with self._lock:
            idx = self.index_of(old_id)
            if idx is None or self.fetishes[idx]['id'] < PLAYER_FETISH_BASE_ID:
                return None
            new_id = engine_mutations.first_free_seed_id(self.fetishes, PLAYER_FETISH_BASE_ID)
            if new_id is None:
                return None
            self.fetishes[idx]['id'] = new_id
            if _use_db():
                engine_db.promote_fetish_id(old_id, new_id, get_conn=_get_conn, put_conn=_put_conn)
            else:
                self._save_fetishes_file()
        return new_id

    def capture_learned_priors(self):
        """現在の P(yes) を learned_priors.json として保存する。
        matrix.json を削除して再初期化する際に DOMAIN_PRIORS の代替として使用される。"""
        engine_persistence.save_learned_priors(
            os.path.join(DATA_DIR, 'learned_priors.json'),
            self.fetishes,
            self.questions,
            probability=self._prob,
            atomic_write=self._atomic_write,
        )

    def get_related(self, fetish_id):
        related_ids = FETISH_RELATIONS.get(fetish_id, [])
        out = []
        for fid in related_ids:
            idx = self.index_of(fid)
            if idx is not None:
                out.append({'fetish_id': fid, 'fetish_name': self.fetishes[idx]['name']})
        return out

    def _entropy(self, probs):
        return engine_runtime.entropy(probs)
