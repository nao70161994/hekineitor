import json
import math
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
import engine_inference
import engine_learning
import engine_question_selection
import engine_compound_works
import engine_stats
from engine_constants import (
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

from engine_data import (
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
        if not isinstance(matrix, dict):
            return False
        yes = matrix.get('yes')
        total = matrix.get('total')
        return (
            isinstance(yes, list)
            and isinstance(total, list)
            and len(yes) == nf
            and len(total) == nf
            and all(isinstance(row, list) and len(row) == nq for row in yes)
            and all(isinstance(row, list) and len(row) == nq for row in total)
        )

    def _load_matrix_file(self):
        path = os.path.join(DATA_DIR, 'matrix.json')
        if os.path.exists(path):
            with open(path, encoding='utf-8') as f:
                m = json.load(f)
            nf = len(self.fetishes)
            nq = len(self.questions)
            if self._valid_matrix_shape(m, nf, nq):
                return m
            # サイズ不整合: 削除前にバックアップを作成
            backup = path + '.bak'
            try:
                import shutil
                shutil.copy2(path, backup)
            except OSError:
                pass
            import logging as _logging
            _logging.getLogger(__name__).warning(
                'matrix.json のサイズ不整合 (fetishes=%d, questions=%d) — 再初期化します。バックアップ: %s',
                nf, nq, backup
            )
            os.remove(path)
        return self._init_matrix_file()

    def _init_matrix_file(self):
        nf = len(self.fetishes)
        nq = len(self.questions)
        yes, total = _build_initial_matrix(nf, nq)
        # キャプチャ済みの学習priorがあれば DOMAIN_PRIORS より優先して上書き
        lp_path = os.path.join(DATA_DIR, 'learned_priors.json')
        if os.path.exists(lp_path):
            try:
                with open(lp_path, encoding='utf-8') as f:
                    learned = json.load(f)
                id_to_idx = {fobj['id']: i for i, fobj in enumerate(self.fetishes)}
                for fid_str, row in learned.items():
                    fi = id_to_idx.get(int(fid_str))
                    if fi is None:
                        continue
                    for q_str, p in row.items():
                        q = int(q_str)
                        if 0 <= q < nq:
                            yes[fi][q]   = float(p) * PSEUDO
                            total[fi][q] = float(PSEUDO)
            except Exception:
                pass
        m = {'yes': yes, 'total': total}
        self.matrix = m
        self._save_matrix_file()
        return m

    def _atomic_write(self, path, data, **kwargs):
        atomic_write_json(path, data, **kwargs)

    def _matrix_snapshot(self):
        with self._lock:
            return {
                'yes': [list(row) for row in self.matrix.get('yes', [])],
                'total': [list(row) for row in self.matrix.get('total', [])],
            }

    def _save_matrix_file(self):
        self._atomic_write(os.path.join(DATA_DIR, 'matrix.json'), self._matrix_snapshot())

    def _save_async(self, all_updates, idx_to_db_id):
        """バックグラウンドスレッドで matrix 保存を行う（レスポンスをブロックしない）。"""
        if _use_db():
            t = threading.Thread(target=self._save_to_db, args=(all_updates, idx_to_db_id), daemon=True)
            t.start()
        else:
            self._save_matrix_file()

    def _save_fetishes_file(self):
        self._atomic_write(
            os.path.join(DATA_DIR, 'fetishes.json'),
            self.fetishes,
            ensure_ascii=False, indent=2,
        )

    # ── PostgreSQL ─────────────────────────────────────────
    def _ensure_db(self):
        conn = _get_conn()
        try:
            with conn:
                cur = conn.cursor()
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS fetishes (
                        id   INTEGER PRIMARY KEY,
                        name TEXT NOT NULL,
                        "desc" TEXT NOT NULL,
                        works TEXT NOT NULL DEFAULT '[]'
                    )
                ''')
                cur.execute("ALTER TABLE fetishes ADD COLUMN IF NOT EXISTS works TEXT NOT NULL DEFAULT '[]'")
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS matrix (
                        fetish_id   INTEGER,
                        question_id INTEGER,
                        yes_count   REAL NOT NULL,
                        total_count REAL NOT NULL,
                        PRIMARY KEY (fetish_id, question_id)
                    )
                ''')
                cur.execute('SELECT COUNT(*) FROM fetishes')
                if cur.fetchone()[0] == 0:
                    seed_fetishes = self._load_json('fetishes.json')
                    psycopg2.extras.execute_values(
                        cur,
                        'INSERT INTO fetishes (id, name, "desc", works) VALUES %s',
                        [
                            (f['id'], f['name'], f['desc'],
                             json.dumps(f.get('works', []), ensure_ascii=False))
                            for f in seed_fetishes
                        ]
                    )
                cur.execute('SELECT COUNT(*) FROM matrix')
                if cur.fetchone()[0] == 0:
                    seed_fetishes = self._load_json('fetishes.json')
                    self._seed_db(cur, seed_fetishes)
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS stats (
                        key   TEXT PRIMARY KEY,
                        value INTEGER NOT NULL DEFAULT 0
                    )
                ''')
                for k in ('learn_count', 'play_count'):
                    cur.execute(
                        "INSERT INTO stats (key, value) VALUES (%s, 0) ON CONFLICT DO NOTHING", (k,)
                    )
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS fetish_log (
                        fetish_id INTEGER PRIMARY KEY,
                        guessed   INTEGER NOT NULL DEFAULT 0,
                        correct   INTEGER NOT NULL DEFAULT 0,
                        wrong     INTEGER NOT NULL DEFAULT 0
                    )
                ''')
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS sessions (
                        session_id TEXT PRIMARY KEY,
                        data       TEXT NOT NULL,
                        updated_at REAL NOT NULL
                    )
                ''')
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS config (
                        key   TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    )
                ''')
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS stats_history (
                        date  TEXT NOT NULL,
                        key   TEXT NOT NULL,
                        value INTEGER NOT NULL DEFAULT 0,
                        PRIMARY KEY (date, key)
                    )
                ''')
                # 新しい性癖を fetishes.json から差分追加（マイグレーション）
                cur.execute('SELECT id FROM fetishes')
                existing_ids = {r[0] for r in cur.fetchall()}
                seed = [f for f in self._load_json('fetishes.json')
                        if f['id'] < PLAYER_FETISH_BASE_ID]
                new_f = [f for f in seed if f['id'] not in existing_ids]
                if new_f:
                    psycopg2.extras.execute_values(
                        cur,
                        'INSERT INTO fetishes (id, name, "desc", works) VALUES %s ON CONFLICT DO NOTHING',
                        [
                            (f['id'], f['name'], f['desc'],
                             json.dumps(f.get('works', []), ensure_ascii=False))
                            for f in new_f
                        ]
                    )
                    nq = len(self.questions)
                    nf_total = len(seed)
                    full_yes, full_total = _build_initial_matrix(nf_total, nq)
                    seed_id_to_idx = {f['id']: i for i, f in enumerate(seed)}
                    new_rows = [
                        (f['id'], q,
                         full_yes[seed_id_to_idx[f['id']]][q],
                         full_total[seed_id_to_idx[f['id']]][q])
                        for f in new_f for q in range(nq)
                    ]
                    psycopg2.extras.execute_values(
                        cur,
                        'INSERT INTO matrix (fetish_id, question_id, yes_count, total_count) VALUES %s ON CONFLICT DO NOTHING',
                        new_rows
                    )
                # 既存性癖の名前・説明を fetishes.json と同期
                for f in seed:
                    cur.execute(
                        'UPDATE fetishes SET name=%s, "desc"=%s WHERE id=%s',
                        (f['name'], f['desc'], f['id'])
                    )
                # 新しい質問を matrix に差分追加
                nq = len(self.questions)
                cur.execute('SELECT MAX(question_id) FROM matrix')
                max_qid = cur.fetchone()[0]
                if max_qid is not None and max_qid < nq - 1:
                    cur.execute('SELECT id FROM fetishes')
                    all_fids = [row[0] for row in cur.fetchall()]
                    alpha = 2.0
                    new_q_rows = [
                        (fid, q, alpha, alpha * 2.0)
                        for fid in all_fids
                        for q in range(max_qid + 1, nq)
                    ]
                    if new_q_rows:
                        psycopg2.extras.execute_values(
                            cur,
                            'INSERT INTO matrix (fetish_id, question_id, yes_count, total_count) VALUES %s ON CONFLICT DO NOTHING',
                            new_q_rows
                        )
        finally:
            _put_conn(conn)

    def _load_fetishes_from_db(self):
        conn = _get_conn()
        try:
            cur = conn.cursor()
            cur.execute('SELECT id, name, "desc", works FROM fetishes ORDER BY id')
            rows = []
            for r in cur.fetchall():
                try:
                    works = json.loads(r[3]) if r[3] else []
                    if not isinstance(works, list):
                        works = []
                except (TypeError, json.JSONDecodeError):
                    works = []
                rows.append({'id': r[0], 'name': r[1], 'desc': r[2], 'works': works})
        finally:
            _put_conn(conn)
        return rows

    def _seed_db(self, cur, fetishes=None):
        if fetishes is None:
            fetishes = self.fetishes
        nq = len(self.questions)
        yes, total = _build_initial_matrix(len(fetishes), nq)
        rows = [
            (f['id'], q, yes[fi][q], total[fi][q])
            for fi, f in enumerate(fetishes) for q in range(nq)
        ]
        psycopg2.extras.execute_values(
            cur,
            'INSERT INTO matrix (fetish_id, question_id, yes_count, total_count) VALUES %s',
            rows
        )

    def _load_from_db(self):
        nf = len(self.fetishes)
        nq = len(self.questions)
        id_to_idx = {f['id']: i for i, f in enumerate(self.fetishes)}
        yes   = [[0.0] * nq for _ in range(nf)]
        total = [[0.0] * nq for _ in range(nf)]
        conn = _get_conn()
        try:
            cur = conn.cursor()
            cur.execute('SELECT fetish_id, question_id, yes_count, total_count FROM matrix')
            for f_id, q, y, t in cur.fetchall():
                idx = id_to_idx.get(f_id)
                if idx is not None and 0 <= q < nq:
                    yes[idx][q]   = y
                    total[idx][q] = t
        finally:
            _put_conn(conn)
        return {'yes': yes, 'total': total}

    def _increment_stat(self, key):
        if _use_db():
            conn = _get_conn()
            try:
                with conn:
                    cur = conn.cursor()
                    cur.execute(
                        "INSERT INTO stats (key, value) VALUES (%s, 1) ON CONFLICT (key) DO UPDATE SET value = stats.value + 1",
                        (key,)
                    )
            finally:
                _put_conn(conn)
        else:
            path = os.path.join(DATA_DIR, 'stats.json')
            engine_stats.increment_counter_file(path, key, lock=self._lock, atomic_write=self._atomic_write)

    def _record_daily_stat(self, key):
        from datetime import date as _date
        today = _date.today().isoformat()
        if _use_db():
            conn = _get_conn()
            try:
                with conn:
                    cur = conn.cursor()
                    cur.execute(
                        "INSERT INTO stats_history (date, key, value) VALUES (%s, %s, 1) "
                        "ON CONFLICT (date, key) DO UPDATE SET value = stats_history.value + 1",
                        (today, key)
                    )
            finally:
                _put_conn(conn)
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
            conn = _get_conn()
            try:
                cur = conn.cursor()
                cur.execute("SELECT key, value FROM stats WHERE key = ANY(%s)", (list(keys),))
                result = dict(cur.fetchall())
            finally:
                _put_conn(conn)
        else:
            path = os.path.join(DATA_DIR, 'stats.json')
            return engine_stats.counters_from_file(path, keys)
        return {k: result.get(k, 0) for k in keys}

    def get_stats_history(self, days=30):
        """過去N日間の日別プレイ・学習回数を [{date, play, learn}, ...] で返す。"""
        from datetime import date as _date, timedelta
        today = _date.today()
        date_range = [(today - timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]
        if _use_db():
            conn = _get_conn()
            try:
                cur = conn.cursor()
                cur.execute(
                    "SELECT date, key, value FROM stats_history WHERE date >= %s",
                    (date_range[0],)
                )
                raw = {}
                for d, k, v in cur.fetchall():
                    raw.setdefault(d, {})[k] = v
            finally:
                _put_conn(conn)
        else:
            path = os.path.join(DATA_DIR, 'stats_history.json')
            return engine_stats.history_rows_from_file(path, date_range)
        return [{'date': d,
                 'play':    raw.get(d, {}).get('play',    0),
                 'learn':   raw.get(d, {}).get('learn',   0),
                 'correct': raw.get(d, {}).get('correct', 0),
                 'wrong':   raw.get(d, {}).get('wrong',   0)} for d in date_range]

    def get_recent_fetish_ranking(self, days=7, top_n=10):
        """過去N日間に正解/外れフィードバックが多かった性癖TOP n件を返す。"""
        from datetime import date as _date, timedelta
        today = _date.today()
        since = (today - timedelta(days=days - 1)).isoformat()
        totals = {}  # fetish_id -> {'correct': int, 'wrong': int}
        if _use_db():
            conn = _get_conn()
            try:
                cur = conn.cursor()
                cur.execute(
                    "SELECT key, SUM(value) FROM stats_history WHERE date >= %s AND (key LIKE 'f_correct_%%' OR key LIKE 'f_wrong_%%') GROUP BY key",
                    (since,)
                )
                for key, val in cur.fetchall():
                    if key.startswith('f_correct_'):
                        fid = int(key[len('f_correct_'):])
                        totals.setdefault(fid, {'correct': 0, 'wrong': 0})['correct'] += int(val or 0)
                    elif key.startswith('f_wrong_'):
                        fid = int(key[len('f_wrong_'):])
                        totals.setdefault(fid, {'correct': 0, 'wrong': 0})['wrong'] += int(val or 0)
            finally:
                _put_conn(conn)
        else:
            path = os.path.join(DATA_DIR, 'stats_history.json')
            try:
                with open(path, encoding='utf-8') as f:
                    raw = json.load(f)
            except (OSError, json.JSONDecodeError):
                raw = {}
            date_range = [(today - timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]
            for d in date_range:
                for key, val in raw.get(d, {}).items():
                    if key.startswith('f_correct_'):
                        fid = int(key[len('f_correct_'):])
                        totals.setdefault(fid, {'correct': 0, 'wrong': 0})['correct'] += int(val or 0)
                    elif key.startswith('f_wrong_'):
                        fid = int(key[len('f_wrong_'):])
                        totals.setdefault(fid, {'correct': 0, 'wrong': 0})['wrong'] += int(val or 0)
        id_to_name = {f['id']: f['name'] for f in self.fetishes}
        results = []
        for fid, counts in totals.items():
            total = counts['correct'] + counts['wrong']
            if total == 0:
                continue
            results.append({
                'fetish_id': fid,
                'fetish_name': id_to_name.get(fid, f'ID {fid}'),
                'correct': counts['correct'],
                'wrong': counts['wrong'],
                'total': total,
                'acc': round(counts['correct'] / total * 100) if total > 0 else None,
            })
        results.sort(key=lambda x: x['total'], reverse=True)
        return results[:top_n]

    def get_fetish_history(self, fetish_db_id, days=30):
        """指定性癖の日別正解/外れ件数を [{date, correct, wrong}, ...] で返す。"""
        from datetime import date as _date, timedelta
        today = _date.today()
        date_range = [(today - timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]
        ck = f'f_correct_{fetish_db_id}'
        wk = f'f_wrong_{fetish_db_id}'
        if _use_db():
            conn = _get_conn()
            try:
                cur = conn.cursor()
                cur.execute(
                    "SELECT date, key, value FROM stats_history WHERE date >= %s AND key IN (%s, %s)",
                    (date_range[0], ck, wk)
                )
                raw = {}
                for d, k, v in cur.fetchall():
                    raw.setdefault(d, {})[k] = v
            finally:
                _put_conn(conn)
        else:
            path = os.path.join(DATA_DIR, 'stats_history.json')
            try:
                with open(path, encoding='utf-8') as f:
                    raw = json.load(f)
            except (OSError, json.JSONDecodeError):
                raw = {}
        return [{'date': d,
                 'correct': raw.get(d, {}).get(ck, 0),
                 'wrong':   raw.get(d, {}).get(wk, 0)} for d in date_range]

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
            conn = _get_conn()
            try:
                cur = conn.cursor()
                cur.execute(
                    "SELECT key, SUM(value) FROM stats_history WHERE date >= %s AND key = ANY(%s) GROUP BY key",
                    (date_range[0], list(keys))
                )
                for key, value in cur.fetchall():
                    totals[key] = int(value or 0)
            finally:
                _put_conn(conn)
        else:
            path = os.path.join(DATA_DIR, 'stats_history.json')
            try:
                with open(path, encoding='utf-8') as f:
                    raw = json.load(f)
            except (OSError, json.JSONDecodeError):
                raw = {}
            for d in date_range:
                day = raw.get(d, {})
                for key in keys:
                    totals[key] += int(day.get(key, 0) or 0)
        return {
            'days': days,
            'low_confidence': {
                'guesses': totals['q_low_conf_guess'],
                'correct': totals['q_low_conf_correct'],
                'wrong': totals['q_low_conf_wrong'],
            },
            'additional_questions': {
                'guesses': totals['q_additional_guess'],
                'correct': totals['q_additional_correct'],
                'wrong': totals['q_additional_wrong'],
                'questions': totals['q_additional_question'],
            },
        }

    # ── 質問無効化フラグ ───────────────────────────────────
    def _load_disabled_questions(self):
        if _use_db():
            conn = _get_conn()
            try:
                cur = conn.cursor()
                cur.execute("SELECT key FROM stats WHERE key LIKE 'disabled_q_%'")
                return {int(r[0][len('disabled_q_'):]) for r in cur.fetchall()}
            finally:
                _put_conn(conn)
        else:
            path = os.path.join(DATA_DIR, 'question_flags.json')
            return engine_stats.load_disabled_questions_file(path)

    def _save_disabled_questions(self):
        if _use_db():
            conn = _get_conn()
            try:
                with conn:
                    cur = conn.cursor()
                    cur.execute("DELETE FROM stats WHERE key LIKE 'disabled_q_%'")
                    for q_id in self.disabled_questions:
                        cur.execute(
                            "INSERT INTO stats (key, value) VALUES (%s, 1) ON CONFLICT (key) DO UPDATE SET value=1",
                            (f'disabled_q_{q_id}',)
                        )
            finally:
                _put_conn(conn)
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
            conn = _get_conn()
            try:
                with conn:
                    cur = conn.cursor()
                    cur.execute(f'''
                        INSERT INTO fetish_log (fetish_id, {col}) VALUES (%s, 1)
                        ON CONFLICT (fetish_id) DO UPDATE SET {col} = fetish_log.{col} + 1
                    ''', (fetish_db_id,))
            finally:
                _put_conn(conn)
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
            conn = _get_conn()
            try:
                cur = conn.cursor()
                cur.execute('SELECT fetish_id, guessed, correct, wrong FROM fetish_log')
                return {r[0]: {'guessed': r[1], 'correct': r[2], 'wrong': r[3]}
                        for r in cur.fetchall()}
            finally:
                _put_conn(conn)
        else:
            path = get_fetish_log_path()
            return engine_stats.load_fetish_log_file(path)


    def _save_to_db(self, all_updates, idx_to_db_id=None):
        if not all_updates:
            return
        # idx_to_db_id はロック内で取得したスナップショット。
        # None の場合は呼び出し元が古い方式なのでフォールバック（ロック外アクセス）。
        rows = []
        for fetish_idx, updates in all_updates.items():
            if idx_to_db_id is not None:
                db_id = idx_to_db_id.get(fetish_idx)
            elif fetish_idx < len(self.fetishes):
                db_id = self.fetishes[fetish_idx]['id']
            else:
                db_id = None
            if db_id is None:
                continue
            for q_idx, delta_yes, delta_total in updates:
                rows.append((db_id, q_idx, delta_yes, delta_total))
        conn = _get_conn()
        try:
            with conn:
                cur = conn.cursor()
                cur.executemany('''
                    INSERT INTO matrix (fetish_id, question_id, yes_count, total_count)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (fetish_id, question_id) DO UPDATE
                    SET yes_count   = matrix.yes_count   + EXCLUDED.yes_count,
                        total_count = matrix.total_count + EXCLUDED.total_count
                ''', rows)
        finally:
            _put_conn(conn)

    # ── パラメータ設定 ────────────────────────────────────
    _CONFIG_DEFAULTS = {
        'guess_threshold': 0.75,
        'compound_ratio':  0.55,
        'triple_ratio':    0.45,
        'ucb_explore_c':   0.05,
        'focus_threshold': 0.40,
    }

    def _load_config(self):
        defaults = dict(self._CONFIG_DEFAULTS)
        if _use_db():
            conn = _get_conn()
            try:
                cur = conn.cursor()
                cur.execute('SELECT key, value FROM config')
                for k, v in cur.fetchall():
                    if k in defaults:
                        defaults[k] = float(v)
            except Exception:
                pass
            finally:
                _put_conn(conn)
        else:
            path = os.path.join(DATA_DIR, 'config.json')
            try:
                with open(path, encoding='utf-8') as f:
                    stored = json.load(f)
                for k, v in stored.items():
                    if k in defaults:
                        defaults[k] = float(v)
            except (OSError, json.JSONDecodeError):
                pass
        return defaults

    def set_config(self, key, value):
        if key not in self._CONFIG_DEFAULTS:
            raise ValueError(f'未知のパラメータ: {key}')
        fval = float(value)
        self.config[key] = fval
        if _use_db():
            conn = _get_conn()
            try:
                with conn:
                    cur = conn.cursor()
                    cur.execute(
                        "INSERT INTO config (key, value) VALUES (%s, %s) "
                        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                        (key, str(fval))
                    )
            finally:
                _put_conn(conn)
        else:
            path = os.path.join(DATA_DIR, 'config.json')
            try:
                with open(path, encoding='utf-8') as f:
                    stored = json.load(f)
            except (OSError, json.JSONDecodeError):
                stored = {}
            stored[key] = fval
            self._atomic_write(path, stored)

    # ── disc キャッシュ（学習重みスケーリング用） ──────────
    _DISC_CACHE_TTL = 120.0  # 2分ごとに再計算

    def _get_disc_scales(self):
        now = time.monotonic()
        if self._disc_cache and now - self._disc_cache_time < self._DISC_CACHE_TTL:
            return self._disc_cache
        nf = len(self.fetishes)
        nq = len(self.questions)
        discs = [
            sum(abs(self._prob(f, q) - 0.5) for f in range(nf)) / max(nf, 1)
            for q in range(nq)
        ]
        mean_disc = sum(discs) / max(len(discs), 1) or 1e-9
        # 0.5〜2.0 にクランプして正規化（識別力が高い質問を最大2倍重く学習）
        scales = [max(0.5, min(2.0, d / mean_disc)) for d in discs]
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
        # correct が多いほど重みを上げる（Laplace平滑: alpha=2）
        alpha = 2.0
        weights = {}
        for f in self.fetishes:
            fid = f['id']
            entry = log.get(fid, {})
            correct = entry.get('correct', 0)
            guessed = entry.get('guessed', 0)
            # 実績重み: 正解率 + ラプラス平滑、静的重みとの幾何平均
            empirical = (correct + alpha) / (guessed + alpha * 2)
            static    = FETISH_PRIOR_WEIGHTS.get(fid, 1.0)
            # 実績データが少ない間は静的重みを重視（guessed で線形ブレンド）
            trust = min(guessed / 20.0, 1.0)
            blended = static * (1 - trust) + empirical * trust
            weights[fid] = max(blended, 0.1)
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
        nf = len(self.fetishes)
        nq = len(self.questions)
        n_fetishes  = min(n_fetishes,  nf)
        n_questions = min(n_questions, nq)
        weights = [sum(self.matrix['total'][fi]) for fi in range(nf)]
        top_fi = sorted(range(nf), key=lambda i: -weights[i])[:n_fetishes]
        discs  = [sum(abs(self._prob(f, q) - 0.5) for f in range(nf)) / max(nf, 1)
                  for q in range(nq)]
        top_qi = sorted(sorted(range(nq), key=lambda q: -discs[q])[:n_questions])
        rows = [{'name': self.fetishes[fi]['name'][:12], 'id': self.fetishes[fi]['id'],
                 'cells': [round(self._prob(fi, qi), 2) for qi in top_qi]}
                for fi in top_fi]
        q_labels = [f"Q{qi}" for qi in top_qi]
        q_texts  = [self.questions[qi]['text'][:18] for qi in top_qi]
        return {'rows': rows, 'q_labels': q_labels, 'q_texts': q_texts}

    def get_learning_stats(self):
        nq = len(self.questions)
        prior_qs = {}
        for f, q, _ in DOMAIN_PRIORS:
            prior_qs.setdefault(f, set()).add(q)
        stats = []
        for f, fetish in enumerate(self.fetishes):
            n_prior  = len(prior_qs.get(f, set()))
            baseline = n_prior * float(PSEUDO) + (nq - n_prior) * 4.0
            data_weight = sum(self.matrix['total'][f]) - baseline
            stats.append({
                'id':          f,
                'name':        fetish['name'],
                'data_weight': round(data_weight, 1),
            })
        return sorted(stats, key=lambda x: x['data_weight'])

    def get_question_stats(self):
        """各質問の識別力を返す（識別力 = 各性癖でP(yes)が0.5からどれだけ離れているかの平均）。"""
        nf = len(self.fetishes)
        result = []
        for q, qdata in enumerate(self.questions):
            probs = [self._prob(f, q) for f in range(nf)]
            disc  = sum(abs(p - 0.5) for p in probs) / nf  # 0〜0.5; 高いほど識別力あり
            ask_count = sum(self.matrix['total'][f][q] for f in range(nf))
            result.append({
                'id':            q,
                'text':          qdata['text'],
                'disc':          round(disc, 3),
                'disabled':      q in self.disabled_questions,
                'ask_count':     round(ask_count, 1),
                'variants_count': len(qdata.get('variants', [])),
            })
        return sorted(result, key=lambda x: x['disc'])

    def get_axis_stats(self):
        """QUESTION_AXES別の質問数・平均disc・無効化数を返す。"""
        qs = self.get_question_stats()
        disc_map  = {s['id']: s['disc']     for s in qs}
        disab_map = {s['id']: s['disabled'] for s in qs}
        merged = {}
        for axis_name, axis_range in QUESTION_AXES:
            if axis_name not in merged:
                merged[axis_name] = {'name': axis_name, 'ids': []}
            for q in axis_range:
                if q < len(self.questions):
                    merged[axis_name]['ids'].append(q)
        result = []
        for axis_name, info in merged.items():
            ids = info['ids']
            if not ids:
                continue
            avg_disc  = round(sum(disc_map.get(i, 0) for i in ids) / len(ids), 3)
            dis_count = sum(1 for i in ids if disab_map.get(i, False))
            result.append({
                'name':      axis_name,
                'count':     len(ids),
                'avg_disc':  avg_disc,
                'disabled':  dis_count,
            })
        return result

    def fetish_similarity(self, id_a, id_b):
        """2つの性癖のP(yes)ベクトルのコサイン類似度と差異が大きい質問TOP5を返す。"""
        import math
        idx_a = self.index_of(id_a)
        idx_b = self.index_of(id_b)
        if idx_a is None or idx_b is None:
            return None
        nq = len(self.questions)
        va = [self._prob(idx_a, q) - 0.5 for q in range(nq)]
        vb = [self._prob(idx_b, q) - 0.5 for q in range(nq)]
        dot = sum(a * b for a, b in zip(va, vb))
        na  = math.sqrt(sum(x * x for x in va))
        nb  = math.sqrt(sum(x * x for x in vb))
        if na < 1e-9 or nb < 1e-9:
            cos = 0.0
        else:
            cos = round(dot / (na * nb), 3)
        diffs = sorted(range(nq), key=lambda q: abs(va[q] - vb[q]), reverse=True)
        top_diff = [{'q_id': q, 'text': self.questions[q]['text'],
                     'p_a': round(self._prob(idx_a, q), 3),
                     'p_b': round(self._prob(idx_b, q), 3)}
                    for q in diffs[:5]]
        return {
            'cosine':   cos,
            'name_a':   self.fetishes[idx_a]['name'],
            'name_b':   self.fetishes[idx_b]['name'],
            'top_diff': top_diff,
        }

    _CORR_CACHE_TTL = 300.0  # 相関キャッシュ有効期間（秒）

    def get_correlation_stats(self, top_n=30):
        """質問ベクトル間のコサイン類似度を計算し、上位ペアを返す（5分TTLキャッシュ）。"""
        import math
        now = time.monotonic()
        if self._corr_cache and now - self._corr_cache_time < self._CORR_CACHE_TTL:
            return self._corr_cache[:top_n]
        nf = len(self.fetishes)
        nq = len(self.questions)
        vecs = []
        for q in range(nq):
            v = [self._prob(f, q) - 0.5 for f in range(nf)]
            norm = math.sqrt(sum(x*x for x in v)) or 1e-9
            vecs.append((v, norm))

        pairs = []
        for i in range(nq):
            for j in range(i+1, nq):
                vi, ni = vecs[i]
                vj, nj = vecs[j]
                cos = sum(a*b for a, b in zip(vi, vj)) / (ni * nj)
                pairs.append({
                    'q1_id': i, 'q1_text': self.questions[i]['text'],
                    'q2_id': j, 'q2_text': self.questions[j]['text'],
                    'cos': round(cos, 3),
                })
        pairs.sort(key=lambda x: -abs(x['cos']))
        self._corr_cache      = pairs
        self._corr_cache_time = now
        return pairs[:top_n]

    def get_quality_report(self):
        """診断品質改善に使う要注意項目を返す。"""
        return build_quality_report(self)

    def top_guess(self, answers, n=1):
        return engine_inference.top_guess(self, answers, n=n)

    def get_answer_contributions(self, answers, fetish_idx, top_n=3):
        return engine_inference.answer_contributions(self, answers, fetish_idx, top_n=top_n)

    def detect_contradictions(self, answers):
        """高相関な質問ペアで逆方向の回答があれば最大2件返す。"""
        nq = len(self.questions)
        answered = {}
        for q_str, ans in answers.items():
            try:
                q = int(q_str)
            except (ValueError, TypeError):
                continue
            if ans != 0 and 0 <= q < nq:
                answered[q] = ans
        result = []
        for pair in self.get_correlation_stats(top_n=60):
            if abs(pair['cos']) < 0.75:
                break
            q1, q2 = pair['q1_id'], pair['q2_id']
            if q1 in answered and q2 in answered:
                a1, a2 = answered[q1], answered[q2]
                # 正の相関なのに符号が逆 → 矛盾
                if pair['cos'] > 0.75 and a1 * a2 < 0:
                    result.append({
                        'q1': self.questions[q1]['text'], 'a1': a1,
                        'q2': self.questions[q2]['text'], 'a2': a2,
                    })
                    if len(result) >= 2:
                        break
        return result

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
        neg_weight   = 0.3
        all_updates  = {}
        idx_to_db_id = {}

        with self._lock:
            nf = len(self.fetishes)
            nq = len(self.questions)
            if not (0 <= fetish_idx < nf):
                return
            for q_str, ans in answers.items():
                try:
                    q = int(q_str)
                except (ValueError, TypeError):
                    continue
                if ans == 0 or not (0 <= q < nq):
                    continue
                strength = abs(ans)
                if cold_start:
                    scale = 1.0
                else:
                    scale = min(1.0, PSEUDO / max(self.matrix['total'][fetish_idx][q], PSEUDO))
                effective = strength * scale

                delta_yes = effective if ans > 0 else 0.0
                self.matrix['total'][fetish_idx][q] += effective
                self.matrix['yes'][fetish_idx][q]   += delta_yes
                all_updates.setdefault(fetish_idx, []).append((q, delta_yes, effective))

                for f in range(nf):
                    if f == fetish_idx:
                        continue
                    w = neg_weight * effective
                    neg_yes = w * (0.0 if ans > 0 else 1.0)
                    self.matrix['total'][f][q] += w
                    self.matrix['yes'][f][q]   += neg_yes
                    all_updates.setdefault(f, []).append((q, neg_yes, w))

            idx_to_db_id = {i: f['id'] for i, f in enumerate(self.fetishes)}

        self._save_async(all_updates, idx_to_db_id)

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
                conn = _get_conn()
                try:
                    with conn:
                        cur = conn.cursor()
                        cur.execute(
                            'SELECT COALESCE(MAX(id), %s - 1) + 1 FROM fetishes WHERE id >= %s',
                            (PLAYER_FETISH_BASE_ID, PLAYER_FETISH_BASE_ID)
                        )
                        db_id = max(cur.fetchone()[0], PLAYER_FETISH_BASE_ID)
                        cur.execute(
                            'INSERT INTO fetishes (id, name, "desc", works) VALUES (%s, %s, %s, %s)',
                            (db_id, name, desc, '[]')
                        )
                        rows = [(db_id, q, new_yes[q], new_total[q]) for q in range(nq)]
                        psycopg2.extras.execute_values(
                            cur,
                            'INSERT INTO matrix (fetish_id, question_id, yes_count, total_count) VALUES %s',
                            rows
                        )
                finally:
                    _put_conn(conn)
            else:
                player_ids = [f['id'] for f in self.fetishes if f['id'] >= PLAYER_FETISH_BASE_ID]
                db_id = max(player_ids) + 1 if player_ids else PLAYER_FETISH_BASE_ID

            self.fetishes.append({'id': db_id, 'name': name, 'desc': desc})
            self.matrix['yes'].append(new_yes)
            self.matrix['total'].append(new_total)

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
            nq = len(self.questions)
            for q in range(nq):
                self.matrix['yes'][idx_keep][q]   += self.matrix['yes'][idx_rm][q]
                self.matrix['total'][idx_keep][q] += self.matrix['total'][idx_rm][q]
            if new_name:
                self.fetishes[idx_keep]['name'] = new_name
            if new_desc:
                self.fetishes[idx_keep]['desc'] = new_desc
            # pop 前に name/desc を確保（idx_rm < idx_keep の場合、pop 後にインデックスがズレるため）
            keep_name = self.fetishes[idx_keep]['name']
            keep_desc = self.fetishes[idx_keep]['desc']
            self.fetishes.pop(idx_rm)
            self.matrix['yes'].pop(idx_rm)
            self.matrix['total'].pop(idx_rm)
            if _use_db():
                conn = _get_conn()
                try:
                    with conn:
                        cur = conn.cursor()
                        cur.execute('''
                            UPDATE matrix AS m
                            SET yes_count   = m.yes_count   + rm.yes_count,
                                total_count = m.total_count + rm.total_count
                            FROM matrix rm
                            WHERE m.fetish_id = %s AND rm.fetish_id = %s
                              AND m.question_id = rm.question_id
                        ''', (id_keep, id_remove))
                        cur.execute('DELETE FROM fetishes WHERE id = %s', (id_remove,))
                        cur.execute('DELETE FROM matrix WHERE fetish_id = %s', (id_remove,))
                        cur.execute('''
                            INSERT INTO fetish_log (fetish_id, guessed, correct, wrong)
                            SELECT %s, guessed, correct, wrong FROM fetish_log WHERE fetish_id = %s
                            ON CONFLICT (fetish_id) DO UPDATE
                            SET guessed = fetish_log.guessed + EXCLUDED.guessed,
                                correct = fetish_log.correct + EXCLUDED.correct,
                                wrong   = fetish_log.wrong   + EXCLUDED.wrong
                        ''', (id_keep, id_remove))
                        cur.execute('DELETE FROM fetish_log WHERE fetish_id = %s', (id_remove,))
                        if new_name or new_desc:
                            cur.execute(
                                'UPDATE fetishes SET name=%s, "desc"=%s WHERE id=%s',
                                (new_name or keep_name, new_desc or keep_desc, id_keep)
                            )
                finally:
                    _put_conn(conn)
            else:
                self._save_fetishes_file()
                self._save_matrix_file()
                log_path = get_fetish_log_path()
                try:
                    with open(log_path, encoding='utf-8') as f:
                        log = json.load(f)
                except (OSError, json.JSONDecodeError):
                    log = {}
                e_keep = log.get(str(id_keep), {'guessed': 0, 'correct': 0, 'wrong': 0})
                e_rm   = log.get(str(id_remove), {'guessed': 0, 'correct': 0, 'wrong': 0})
                log[str(id_keep)] = {k: e_keep.get(k, 0) + e_rm.get(k, 0)
                                     for k in ('guessed', 'correct', 'wrong')}
                log.pop(str(id_remove), None)
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
            q_path = os.path.join(DATA_DIR, 'questions.json')
            self._atomic_write(q_path, self.questions)
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
        id_map = {i: fid for fid, i in idx_map.items()}
        rows = []
        for fi, qs in updates.items():
            db_id = id_map.get(fi)
            if db_id is None:
                continue
            for qi, y, t in qs:
                rows.append((db_id, qi, y, t))
        if not rows:
            return
        conn = _get_conn()
        try:
            with conn:
                cur = conn.cursor()
                psycopg2.extras.execute_values(cur, '''
                    INSERT INTO matrix (fetish_id, question_id, yes_count, total_count)
                    VALUES %s
                    ON CONFLICT (fetish_id, question_id) DO UPDATE
                        SET yes_count   = EXCLUDED.yes_count,
                            total_count = EXCLUDED.total_count
                ''', rows)
        finally:
            _put_conn(conn)

    def edit_fetish(self, fetish_id, name=None, desc=None, works=None):
        """性癖の名前・説明文・作品リストを更新する。変更したフィールドのみ渡す。"""
        with self._lock:
            idx = self.index_of(fetish_id)
            if idx is None:
                return False
            if name is not None:
                self.fetishes[idx]['name'] = name
            if desc is not None:
                self.fetishes[idx]['desc'] = desc
            if works is not None:
                self.fetishes[idx]['works'] = works
            if _use_db():
                conn = _get_conn()
                try:
                    with conn:
                        cur = conn.cursor()
                        updates = []
                        params = []
                        if name is not None:
                            updates.append('name=%s')
                            params.append(name)
                        if desc is not None:
                            updates.append('"desc"=%s')
                            params.append(desc)
                        if works is not None:
                            updates.append('works=%s')
                            params.append(json.dumps(works, ensure_ascii=False))
                        if updates:
                            params.append(fetish_id)
                            cur.execute(f'UPDATE fetishes SET {", ".join(updates)} WHERE id=%s', params)
                finally:
                    _put_conn(conn)
            else:
                self._save_fetishes_file()
        return True

    def delete_fetish(self, fetish_id):
        """プレイヤー追加性癖（ID >= PLAYER_FETISH_BASE_ID）を削除する。"""
        with self._lock:
            idx = next((i for i, f in enumerate(self.fetishes) if f['id'] == fetish_id), None)
            if idx is None or self.fetishes[idx]['id'] < PLAYER_FETISH_BASE_ID:
                return False
            self.fetishes.pop(idx)
            self.matrix['yes'].pop(idx)
            self.matrix['total'].pop(idx)
            if _use_db():
                conn = _get_conn()
                try:
                    with conn:
                        cur = conn.cursor()
                        cur.execute('DELETE FROM fetishes WHERE id = %s', (fetish_id,))
                        cur.execute('DELETE FROM matrix WHERE fetish_id = %s', (fetish_id,))
                finally:
                    _put_conn(conn)
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
            seed_ids = {f['id'] for f in self.fetishes if f['id'] < PLAYER_FETISH_BASE_ID}
            new_id = next((i for i in range(PLAYER_FETISH_BASE_ID) if i not in seed_ids), None)
            if new_id is None:
                return None
            self.fetishes[idx]['id'] = new_id
            if _use_db():
                conn = _get_conn()
                try:
                    with conn:
                        cur = conn.cursor()
                        cur.execute('UPDATE fetishes  SET id = %s WHERE id = %s', (new_id, old_id))
                        cur.execute('UPDATE matrix    SET fetish_id = %s WHERE fetish_id = %s', (new_id, old_id))
                        cur.execute('UPDATE fetish_log SET fetish_id = %s WHERE fetish_id = %s', (new_id, old_id))
                finally:
                    _put_conn(conn)
            else:
                self._save_fetishes_file()
        return new_id

    def capture_learned_priors(self):
        """現在の P(yes) を learned_priors.json として保存する。
        matrix.json を削除して再初期化する際に DOMAIN_PRIORS の代替として使用される。"""
        nf = len(self.fetishes)
        nq = len(self.questions)
        snapshot = {}
        for fi in range(nf):
            fid = self.fetishes[fi]['id']
            row = {}
            for q in range(nq):
                p = self._prob(fi, q)
                if abs(p - 0.5) > 0.05:
                    row[str(q)] = round(p, 4)
            if row:
                snapshot[str(fid)] = row
        path = os.path.join(DATA_DIR, 'learned_priors.json')
        self._atomic_write(path, snapshot, ensure_ascii=False)

    def get_related(self, fetish_id):
        related_ids = FETISH_RELATIONS.get(fetish_id, [])
        out = []
        for fid in related_ids:
            idx = self.index_of(fid)
            if idx is not None:
                out.append({'fetish_id': fid, 'fetish_name': self.fetishes[idx]['name']})
        return out

    def _entropy(self, probs):
        return -sum(p * math.log2(p) for p in probs if p > 1e-10)
