import os
import re
import hmac
import hashlib
import functools
import unicodedata
import uuid
import json as _json
import time as _time
import random as _random
from flask import Flask, render_template, request, jsonify, session, Response, send_from_directory
from flask.sessions import SessionInterface, SessionMixin
from werkzeug.datastructures import CallbackDict
from engine import (Engine, PLAYER_FETISH_BASE_ID, _get_conn, _put_conn, _use_db,
                    FOCUS_THRESHOLD, get_compound_works,
                    list_compound_works, set_compound_works, delete_compound_works)

# ── サーバーサイドセッション ──────────────────────────────
_SESSION_TTL    = 86400  # 24時間
_LOCAL_SESSIONS = {}     # ローカル用インメモリストア {sid: (data, updated_at)}

def _session_load(sid):
    if _use_db():
        conn = _get_conn()
        try:
            cur = conn.cursor()
            cur.execute('SELECT data, updated_at FROM sessions WHERE session_id = %s', (sid,))
            row = cur.fetchone()
            if row and _time.time() - row[1] < _SESSION_TTL:
                return _json.loads(row[0])
        finally:
            _put_conn(conn)
    else:
        entry = _LOCAL_SESSIONS.get(sid)
        if entry and _time.time() - entry[1] < _SESSION_TTL:
            return dict(entry[0])
    return None

def _session_save(sid, data):
    now = _time.time()
    if _use_db():
        conn = _get_conn()
        try:
            with conn:
                cur = conn.cursor()
                cur.execute('''
                    INSERT INTO sessions (session_id, data, updated_at) VALUES (%s, %s, %s)
                    ON CONFLICT (session_id) DO UPDATE
                    SET data = EXCLUDED.data, updated_at = EXCLUDED.updated_at
                ''', (sid, _json.dumps(data, ensure_ascii=False), now))
                # 1%の確率で期限切れセッションを掃除
                if _random.random() < 0.01:
                    cur.execute('DELETE FROM sessions WHERE updated_at < %s',
                                (now - _SESSION_TTL,))
        finally:
            _put_conn(conn)
    else:
        _LOCAL_SESSIONS[sid] = (data, now)
        if len(_LOCAL_SESSIONS) > 2000:
            cutoff = now - _SESSION_TTL
            for k in [k for k, v in _LOCAL_SESSIONS.items() if v[1] < cutoff]:
                del _LOCAL_SESSIONS[k]

def cleanup_sessions():
    """期限切れセッションを全削除（管理APIから呼び出し可）。"""
    cutoff = _time.time() - _SESSION_TTL
    if _use_db():
        conn = _get_conn()
        try:
            with conn:
                cur = conn.cursor()
                cur.execute('DELETE FROM sessions WHERE updated_at < %s', (cutoff,))
                return cur.rowcount
        finally:
            _put_conn(conn)
    else:
        old = [k for k, v in _LOCAL_SESSIONS.items() if v[1] < cutoff]
        for k in old:
            del _LOCAL_SESSIONS[k]
        return len(old)

class _ServerSession(CallbackDict, SessionMixin):
    def __init__(self, initial=None, sid=None, is_new=False):
        def on_update(self):
            self.modified = True
        super().__init__(initial or {}, on_update)
        self.sid      = sid
        self.is_new   = is_new
        self.modified = False

class _ServerSessionInterface(SessionInterface):
    _cookie = 'heki_sid'

    def open_session(self, app, request):
        sid = request.cookies.get(self._cookie)
        if sid:
            data = _session_load(sid)
            if data is not None:
                return _ServerSession(data, sid=sid)
        return _ServerSession(sid=str(uuid.uuid4()), is_new=True)

    def save_session(self, app, session, response):
        if not session.modified and not session.is_new:
            return
        _session_save(session.sid, dict(session))
        secure = bool(os.environ.get('DATABASE_URL'))
        response.set_cookie(
            self._cookie, session.sid,
            httponly=True, secure=secure, samesite='Lax',
            max_age=_SESSION_TTL,
        )

# ─────────────────────────────────────────────────────────
app = Flask(__name__)
_secret = os.environ.get('SECRET_KEY')
if not _secret:
    if os.environ.get('DATABASE_URL'):
        raise RuntimeError('本番環境では SECRET_KEY 環境変数の設定が必須です')
    import sys, warnings
    print('WARNING: SECRET_KEY が未設定です。本番環境では環境変数に設定してください。', file=sys.stderr)
    warnings.warn('SECRET_KEY が未設定です。本番環境では環境変数に設定してください。', stacklevel=1)
    _secret = 'hekineitor_dev_secret_2024'
elif len(_secret) < 16:
    import sys
    print('WARNING: SECRET_KEY が短すぎます（16文字以上推奨）。', file=sys.stderr)
app.secret_key = _secret
app.session_interface = _ServerSessionInterface()

def _app_version():
    h = hashlib.md5()
    for path in ['app.py', 'engine.py', 'templates/index.html']:
        try:
            with open(os.path.join(os.path.dirname(__file__), path), 'rb') as f:
                h.update(f.read())
        except OSError:
            pass
    return h.hexdigest()[:8]

APP_VERSION    = _app_version()
DISPLAY_VERSION = 'v1.3.0'
engine = Engine()

GUESS_THRESHOLD = 0.75
MAX_QUESTIONS   = 20


def _normalize_name(s):
    s = unicodedata.normalize('NFKC', s)
    s = s.lower()
    s = re.sub(r'[\s\u3000・･（）()「」『』【】〔〕\-_～~、。×]', '', s)
    return s

def _levenshtein(a, b):
    if len(a) < len(b):
        a, b = b, a
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for ca in a:
        curr = [prev[0] + 1]
        for j, cb in enumerate(b):
            curr.append(min(prev[j] + (ca != cb), curr[-1] + 1, prev[j + 1] + 1))
        prev = curr
    return prev[-1]

def _find_similar(name, fetishes):
    norm_new = _normalize_name(name)
    results = []
    for f in fetishes:
        norm_f = _normalize_name(f['name'])
        if norm_new == norm_f:
            continue
        if norm_new in norm_f or norm_f in norm_new:
            results.append(f)
            continue
        if len(norm_new) <= 12 and len(norm_f) <= 12 and _levenshtein(norm_new, norm_f) <= 2:
            results.append(f)
    return results[:5]


@app.route('/')
def index():
    return render_template('index.html', display_version=DISPLAY_VERSION)


@app.route('/r')
def result_share():
    name = request.args.get('f', '')[:60]
    prob = request.args.get('p', '')[:5]
    desc = request.args.get('d', '')[:120]
    return render_template('result_share.html',
                           fetish_name=name, probability=prob, desc=desc,
                           display_version=DISPLAY_VERSION)


@app.route('/manifest.json')
def manifest():
    return send_from_directory(app.static_folder, 'manifest.json'), 200, {
        'Content-Type': 'application/manifest+json',
        'Cache-Control': 'no-cache',
    }


@app.route('/sw.js')
def sw():
    return render_template('sw.js', version=APP_VERSION), 200, {
        'Content-Type': 'application/javascript',
        'Cache-Control': 'no-cache',
    }


@app.route('/api/start', methods=['POST'])
def start():
    data = request.get_json(silent=True) or {}
    exclude_ids = []
    for eid in data.get('exclude_ids', []):
        try:
            exclude_ids.append(int(eid))
        except (ValueError, TypeError):
            pass
    session.clear()
    session['answers']     = {}
    session['asked']       = []
    session['started']     = True
    session['exclude_ids'] = exclude_ids
    q = engine.best_question({}, set())
    session['asked'].append(q)
    q_data = engine.questions[q]
    q_variants = q_data.get('variants', [])
    q_text = _random.choice([q_data['text']] + q_variants) if q_variants else q_data['text']
    return jsonify({
        'question_id': q,
        'question':    q_text,
        'count':       0,
        'total':       MAX_QUESTIONS,
        'axis':        engine._question_axis(q),
        'q_hint':      q_data.get('hint', ''),
    })


@app.route('/api/resume', methods=['POST'])
def resume():
    """localStorageに保存した回答ペアからセッションを復元して次の質問を返す。"""
    data  = request.get_json(silent=True) or {}
    pairs = data.get('pairs', [])
    exclude_ids = []
    for eid in data.get('exclude_ids', []):
        try:
            exclude_ids.append(int(eid))
        except (ValueError, TypeError):
            pass
    session.clear()
    session['started']     = True
    session['answers']     = {}
    session['asked']       = []
    session['idk_streak']  = 0
    session['exclude_ids'] = exclude_ids
    for item in pairs:
        try:
            q_idx = int(item['q_id'])
            ans   = float(item['answer'])
        except (KeyError, ValueError, TypeError):
            continue
        if ans not in (1, 0.5, 0, -0.5, -1):
            continue
        if q_idx < 0 or q_idx >= len(engine.questions):
            continue
        session['answers'][str(q_idx)] = ans
        if q_idx not in session['asked']:
            session['asked'].append(q_idx)
        session['idk_streak'] = session['idk_streak'] + 1 if ans == 0 else 0
    answers = session['answers']
    asked   = session['asked']
    if not answers:
        q = engine.best_question({}, set())
        session['asked'].append(q)
        q_data = engine.questions[q]
        q_variants = q_data.get('variants', [])
        q_text = _random.choice([q_data['text']] + q_variants) if q_variants else q_data['text']
        return jsonify({'action': 'question', 'question_id': q,
                        'question': q_text,
                        'count': 0, 'total': MAX_QUESTIONS,
                        'axis': engine._question_axis(q),
                        'q_hint': q_data.get('hint', '')})
    next_q = engine.best_question(answers, set(asked), idk_streak=session['idk_streak'])
    if next_q is None:
        return _make_guess(answers)
    asked.append(next_q)
    session['asked'] = asked
    nq_data = engine.questions[next_q]
    nq_variants = nq_data.get('variants', [])
    nq_text = _random.choice([nq_data['text']] + nq_variants) if nq_variants else nq_data['text']
    return jsonify({'action': 'question', 'question_id': next_q,
                    'question': nq_text,
                    'count': len(asked) - 1, 'total': MAX_QUESTIONS,
                    'axis': engine._question_axis(next_q),
                    'q_hint': nq_data.get('hint', '')})


@app.route('/api/continue', methods=['POST'])
def continue_game():
    """診断確定後に「もう少し続ける」ボタンで追加質問を開始する。"""
    if not session.get('started'):
        return jsonify({'status': 'session_expired'}), 440
    answers = session.get('answers', {})
    asked   = session.get('asked', [])
    top2    = engine.top_guess(answers, n=2)
    top_p   = top2[0][1] if top2 else 0.0
    session['continue_thr'] = min(top_p + 0.20, 0.95)
    session['continued']    = True
    next_q = engine.best_question(answers, set(asked), idk_streak=0)
    if next_q is None:
        return jsonify({'status': 'no_question'})
    asked.append(next_q)
    session['asked'] = asked
    cq_data = engine.questions[next_q]
    cq_variants = cq_data.get('variants', [])
    cq_text = _random.choice([cq_data['text']] + cq_variants) if cq_variants else cq_data['text']
    return jsonify({'action': 'question', 'question_id': next_q,
                    'question': cq_text,
                    'count': len(asked) - 1, 'total': MAX_QUESTIONS,
                    'axis': engine._question_axis(next_q),
                    'q_hint': cq_data.get('hint', '')})


@app.route('/api/answer', methods=['POST'])
def answer():
    if not session.get('started'):
        return jsonify({'status': 'session_expired'}), 440
    data = request.get_json(silent=True) or {}
    if 'question_id' not in data or 'answer' not in data:
        return jsonify({'status': 'error', 'message': 'question_id と answer が必要です'}), 400
    try:
        q_idx = int(data['question_id'])
        ans   = float(data['answer'])
    except (ValueError, TypeError):
        return jsonify({'status': 'error', 'message': '不正な値です'}), 400
    if ans not in (1, 0.5, 0, -0.5, -1):
        return jsonify({'status': 'error', 'message': '不正な回答値です'}), 400
    if q_idx < 0 or q_idx >= len(engine.questions):
        return jsonify({'status': 'error', 'message': '不正な質問IDです'}), 400

    answers = session.get('answers', {})
    asked   = session.get('asked', [])

    answers[str(q_idx)] = ans
    session['answers']  = answers

    # back() 後の再回答でも q_idx を asked に含める（重複質問防止）
    if q_idx not in asked:
        asked.append(q_idx)

    # 「わからない」連続カウント
    idk_streak = session.get('idk_streak', 0)
    idk_streak = idk_streak + 1 if ans == 0 else 0
    session['idk_streak'] = idk_streak

    try:
        top2 = engine.top_guess(answers, n=2)
        top_p    = top2[0][1]
        second_p = top2[1][1] if len(top2) > 1 else 0.0
        count = len(asked)

        # 終了条件: idk連続4回 / 問題数上限 / 通常閾値 / 早期打ち切り（比率ベース）
        guess_thr = engine.config.get('guess_threshold', GUESS_THRESHOLD)
        if session.get('continued'):
            guess_thr = session.get('continue_thr', min(guess_thr + 0.20, 0.95))
        gap_ratio  = top_p / max(second_p, 0.001)
        early_stop = (count >= 4 and top_p >= 0.70 and gap_ratio >= 3.0) or \
                     (count >= 8 and top_p >= 0.55 and gap_ratio >= 2.5)
        # 接戦（1位と2位が近い）かつ問数が少ない場合は閾値を引き上げて続行
        effective_thr = guess_thr if (gap_ratio >= 1.8 or count >= 10) \
                        else min(guess_thr + 0.10, 0.90)
        if idk_streak >= 4 or top_p >= effective_thr or count >= MAX_QUESTIONS or early_stop:
            return _make_guess(answers)

        next_q = engine.best_question(answers, set(asked), idk_streak=idk_streak)
        if next_q is None:
            return _make_guess(answers)

        asked.append(next_q)
        session['asked'] = asked

        focus_thr = engine.config.get('focus_threshold', FOCUS_THRESHOLD)
        hint = '答えが見えてきました…もう少しです' if top_p >= focus_thr else None

        aq_data = engine.questions[next_q]
        aq_variants = aq_data.get('variants', [])
        aq_text = _random.choice([aq_data['text']] + aq_variants) if aq_variants else aq_data['text']

        resp = {
            'action':      'question',
            'question_id': next_q,
            'question':    aq_text,
            'count':       count,
            'total':       MAX_QUESTIONS,
            'axis':        engine._question_axis(next_q),
            'q_hint':      aq_data.get('hint', ''),
        }
        if hint:
            resp['hint'] = hint
        contradictions = engine.detect_contradictions(answers)
        if contradictions:
            resp['contradictions'] = contradictions
        return jsonify(resp)
    except Exception:
        app.logger.exception('answer() 推論エラー')
        return jsonify({'status': 'session_expired', 'restart': True}), 440


@app.route('/api/back', methods=['POST'])
def back():
    if not session.get('started'):
        return jsonify({'status': 'session_expired'}), 440
    asked   = session.get('asked', [])
    answers = session.get('answers', {})

    if len(asked) < 2:
        return jsonify({'status': 'no_history'})

    # asked[-1] = 現在表示中（未回答）、asked[-2] = 直前に回答済み
    asked.pop()                          # 現在の質問を除去
    prev_q = asked[-1]
    answers.pop(str(prev_q), None)       # 直前の回答を取り消し
    asked.pop()                          # 直前の質問も除去（再回答時に再追加）

    session['asked']      = asked
    session['answers']    = answers
    session['idk_streak'] = 0

    return jsonify({
        'question_id': prev_q,
        'question':    engine.questions[prev_q]['text'],
        'count':       len(asked),
        'total':       MAX_QUESTIONS,
    })


import math as _math

PROFILE_MIN_RATIO = 0.25   # best_p に対する比率の下限
PROFILE_MIN_PROB  = 0.08   # 絶対確率の下限
COMPOUND_RATIO    = 0.55   # 2位がこの比率以上なら複合
TRIPLE_RATIO      = 0.45   # 3位がこの比率以上なら三重複合

def _learn_factor(answers, total_n=1):
    """確信度スケーリング × √n 分散: 不確実なほど強く、多く選ぶほど弱く。"""
    probs  = engine.posteriors(answers)
    thr    = engine.config.get('guess_threshold', GUESS_THRESHOLD)
    top_p  = max(probs) if probs else thr
    if top_p >= thr:
        # 診断閾値以上: top_p=thr→1.0、top_p=1.0→0.5 に線形マッピング
        conf = max(0.5, 1.0 - 0.5 * (top_p - thr) / max(1.0 - thr, 1e-9))
    else:
        # 閾値未満（max_questions 到達など）: 不確実なほど強く（最大2.0）
        conf = min(2.0, thr / max(top_p, 0.1))
    n_scale = 1.0 / _math.sqrt(max(total_n, 1))
    return max(0.3, min(2.0, conf * n_scale))


def _compute_guess(answers):
    """診断結果を返す（play_count はインクリメントしない、純粋計算）。
    レスポンスの fetish_id 系は全てDB id（永続的・プレイヤー追加性癖でも安全）。"""
    probs   = engine.posteriors(answers)
    exclude_ids = set(session.get('exclude_ids', []))
    ranked  = sorted(range(len(probs)), key=lambda i: probs[i], reverse=True)
    # exclude_ids に該当するものを末尾に退ける（除外優先、0件なら通常通り）
    if exclude_ids:
        ranked = [i for i in ranked if engine.fetishes[i]['id'] not in exclude_ids] + \
                 [i for i in ranked if engine.fetishes[i]['id'] in exclude_ids]
    best_i  = ranked[0]
    best_p  = probs[best_i]
    best_f  = engine.fetishes[best_i]
    best_db = best_f['id']

    compound_ratio = engine.config.get('compound_ratio', COMPOUND_RATIO)
    triple_ratio   = engine.config.get('triple_ratio',   TRIPLE_RATIO)
    compound = []
    compound_db_ids = set()
    if len(ranked) > 1 and probs[ranked[1]] >= best_p * compound_ratio:
        c = engine.fetishes[ranked[1]]
        compound.append({'fetish_id': c['id'],
                         'fetish_name': c['name'],
                         'probability': round(probs[ranked[1]] * 100, 1)})
        compound_db_ids.add(c['id'])
        if len(ranked) > 2 and probs[ranked[2]] >= best_p * triple_ratio:
            c = engine.fetishes[ranked[2]]
            compound.append({'fetish_id': c['id'],
                             'fetish_name': c['name'],
                             'probability': round(probs[ranked[2]] * 100, 1)})
            compound_db_ids.add(c['id'])

    threshold = max(best_p * PROFILE_MIN_RATIO, PROFILE_MIN_PROB)
    profile = []
    for fi in ranked[1:]:
        f_dict = engine.fetishes[fi]
        if f_dict['id'] == best_db or f_dict['id'] in compound_db_ids:
            continue
        if probs[fi] >= threshold:
            profile.append({'fetish_id': f_dict['id'],
                            'fetish_name': f_dict['name'],
                            'probability': round(probs[fi] * 100, 1)})

    profile_db_ids = {p['fetish_id'] for p in profile}
    related_seen   = profile_db_ids | compound_db_ids | {best_db}
    related        = []
    for src_db in [best_db] + list(compound_db_ids):
        for r in engine.get_related(src_db):
            if r['fetish_id'] not in related_seen:
                related.append(r)
                related_seen.add(r['fetish_id'])

    # 上位5件の確率バー用
    top_chart = []
    for fi in ranked[:5]:
        f_dict = engine.fetishes[fi]
        top_chart.append({'fetish_name': f_dict['name'], 'probability': round(probs[fi] * 100, 1)})

    reasons = engine.get_answer_contributions(answers, best_i)

    # 作品レコメンド: 複合特化作品を優先し、その後各性癖の個別作品をマージ
    seen_works: set = set()
    cross_works: list = []   # 複合に特化した作品（複数性癖の要素を兼ね備えた作品）
    merged_works: list = []  # 個別作品のマージ

    if compound:
        for c in compound:
            for w in get_compound_works(best_db, c['fetish_id']):
                if w not in seen_works:
                    cross_works.append(w)
                    seen_works.add(w)
        # 三重複合の場合、compound同士のペアも確認
        c_ids = [c['fetish_id'] for c in compound]
        for i in range(len(c_ids)):
            for j in range(i + 1, len(c_ids)):
                for w in get_compound_works(c_ids[i], c_ids[j]):
                    if w not in seen_works:
                        cross_works.append(w)
                        seen_works.add(w)

    for w in best_f.get('works', []):
        if w not in seen_works:
            merged_works.append(w)
            seen_works.add(w)
    for c in compound:
        ci = engine.index_of(c['fetish_id'])
        if ci is not None:
            for w in engine.fetishes[ci].get('works', []):
                if w not in seen_works:
                    merged_works.append(w)
                    seen_works.add(w)

    return {
        'action':       'guess',
        'fetish_id':    best_db,
        'fetish_name':  best_f['name'],
        'fetish_desc':  best_f['desc'],
        'probability':  round(best_p * 100, 1),
        'compound':     compound,
        'profile':      profile,
        'related':      related,
        'top_chart':    top_chart,
        'reasons':      reasons,
        'works':        merged_works,
        'cross_works':  cross_works,
    }


def _make_guess(answers):
    engine.increment_play_count()
    result = _compute_guess(answers)
    engine.log_guessed(result['fetish_id'])
    return jsonify(result)


@app.route('/api/confirm', methods=['POST'])
def confirm():
    data = request.get_json(silent=True) or {}
    if 'correct' not in data or 'fetish_id' not in data:
        return jsonify({'status': 'error', 'message': 'correct と fetish_id が必要です'}), 400
    try:
        f_db_id = int(data['fetish_id'])
    except (ValueError, TypeError):
        return jsonify({'status': 'error', 'message': '不正な fetish_id です'}), 400
    f_idx = engine.index_of(f_db_id)
    if f_idx is None:
        return jsonify({'status': 'error', 'message': '存在しない fetish_id です'}), 400
    correct = data['correct']
    answers = session.get('answers', {})

    if correct:
        learn_idxs = [f_idx]
        for cid in data.get('compound_ids', []):
            try:
                c_idx = engine.index_of(int(cid))
                if c_idx is not None and c_idx != f_idx:
                    learn_idxs.append(c_idx)
            except (ValueError, TypeError):
                pass
        factor = _learn_factor(answers, total_n=len(learn_idxs))
        for idx in learn_idxs:
            engine.learn(answers, idx, strength_factor=factor)
            engine.log_correct(engine.fetishes[idx]['id'])
        # 複合正解: 共起パターンを相互強化
        for i in range(len(learn_idxs)):
            for j in range(i + 1, len(learn_idxs)):
                engine.learn_cooccurrence(answers, learn_idxs[i], learn_idxs[j], factor * 0.3)
        return jsonify({'status': 'learned'})
    else:
        if not data.get('add_only', False):
            engine.log_wrong(f_db_id)
        probs = engine.posteriors(answers)
        excluded_db_ids = {f_db_id}
        for cid in data.get('compound_ids', []):
            try:
                excluded_db_ids.add(int(cid))
            except (ValueError, TypeError):
                pass
        candidates = []
        for i, f in enumerate(engine.fetishes):
            if f['id'] in excluded_db_ids:
                continue
            candidates.append((probs[i], f))
        candidates.sort(key=lambda t: t[0], reverse=True)
        sorted_fetishes = [dict(f, prob=round(p * 100, 1)) for p, f in candidates[:20]]
        # add_only=True は正解追加目的のリスト取得なので wrong_db_ids を設定しない
        if not data.get('add_only', False):
            session['wrong_db_ids'] = list(excluded_db_ids)
        else:
            session['wrong_db_ids'] = []
        return jsonify({'status': 'wrong', 'fetishes': sorted_fetishes})


@app.route('/api/teach', methods=['POST'])
def teach():
    data = request.get_json(silent=True) or {}
    if 'fetish_id' not in data:
        return jsonify({'status': 'error', 'message': 'fetish_id が必要です'}), 400
    try:
        f_db_id = int(data['fetish_id'])
    except (ValueError, TypeError):
        return jsonify({'status': 'error', 'message': '不正な fetish_id です'}), 400
    f_idx = engine.index_of(f_db_id)
    if f_idx is None:
        return jsonify({'status': 'error', 'message': '存在しない fetish_id です'}), 400
    answers  = session.get('answers', {})
    try:
        total_n = max(1, int(data.get('total_n', 1)))
    except (ValueError, TypeError):
        return jsonify({'status': 'error', 'message': '不正な total_n です'}), 400
    engine.learn(answers, f_idx, strength_factor=_learn_factor(answers, total_n))
    engine.log_correct(engine.fetishes[f_idx]['id'])
    return jsonify({'status': 'learned', 'fetish_name': engine.fetishes[f_idx]['name']})


@app.route('/api/add_fetish', methods=['POST'])
def add_fetish():
    data        = request.get_json(silent=True) or {}
    name      = data.get('name', '').strip()
    desc      = data.get('desc', '').strip()
    confirmed = data.get('confirmed', False)
    answers   = session.get('answers', {})
    if not name:
        return jsonify({'status': 'error', 'message': '名前を入力してください'}), 400
    if len(name) > 100:
        return jsonify({'status': 'error', 'message': '名前は100文字以内で入力してください'}), 400
    if len(desc) > 500:
        return jsonify({'status': 'error', 'message': '説明は500文字以内で入力してください'}), 400
    existing = next((f for f in engine.fetishes if f['name'] == name), None)
    if existing:
        # 学習は /api/finalize_added にまとめる（完了ボタン押下時）
        return jsonify({'status': 'learned', 'fetish_name': existing['name'],
                        'fetish_id': existing['id'], 'is_new': False})
    if confirmed:
        if not desc:
            desc = name
        _, db_id = engine.add_fetish(name, desc, answers)
        return jsonify({'status': 'learned', 'fetish_name': name,
                        'fetish_id': db_id, 'is_new': True})
    similar = _find_similar(name, engine.fetishes)
    if similar:
        return jsonify({'status': 'similar', 'candidates': similar})
    return jsonify({'status': 'needs_desc'})


@app.route('/api/finalize_added', methods=['POST'])
def finalize_added():
    data  = request.get_json(silent=True) or {}
    items = data.get('items', [])
    if not isinstance(items, list):
        return jsonify({'status': 'error', 'message': 'items はリストで指定してください'}), 400
    answers  = session.get('answers', {})
    total_n  = max(1, len([i for i in items if isinstance(i, dict)]))
    factor   = _learn_factor(answers, total_n)
    correct_db_ids = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            db_id  = int(item.get('id'))
            is_new = bool(item.get('is_new'))
        except (ValueError, TypeError):
            continue
        idx = engine.index_of(db_id)
        if idx is None:
            continue
        correct_db_ids.add(db_id)
        if is_new:
            engine.boost_learn_new(idx, answers)
        else:
            engine.learn(answers, idx, strength_factor=factor)
    # 複合正解の共起強化
    correct_idxs = [engine.index_of(db_id) for db_id in correct_db_ids
                    if engine.index_of(db_id) is not None]
    for i in range(len(correct_idxs)):
        for j in range(i + 1, len(correct_idxs)):
            engine.learn_cooccurrence(answers, correct_idxs[i], correct_idxs[j], factor * 0.3)
    # 外れた診断に対するネガティブ学習（正解として選ばれなかったもののみ）
    wrong_db_ids = session.pop('wrong_db_ids', [])
    for wid in wrong_db_ids:
        if wid not in correct_db_ids:
            w_idx = engine.index_of(wid)
            if w_idx is not None:
                engine.learn_negative(answers, w_idx)
    return jsonify({'status': 'done'})


@app.route('/api/fetish/<int:fetish_id>', methods=['DELETE'])
def delete_fetish(fetish_id):
    if fetish_id < PLAYER_FETISH_BASE_ID:
        return jsonify({'status': 'error', 'message': 'シード性癖は削除できません'}), 403
    ok = engine.delete_fetish(fetish_id)
    if not ok:
        return jsonify({'status': 'error', 'message': '見つかりません'}), 404
    return jsonify({'status': 'deleted'})


def _require_admin(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        admin_user = os.environ.get('ADMIN_USER', 'admin')
        admin_pass = os.environ.get('ADMIN_PASS', '')
        if not admin_pass:
            return Response('ADMIN_PASS が未設定です', 503)
        auth = request.authorization
        if not auth or not hmac.compare_digest(auth.username, admin_user) \
                or not hmac.compare_digest(auth.password, admin_pass):
            return Response('認証が必要です', 401,
                            {'WWW-Authenticate': 'Basic realm="Admin"'})
        return f(*args, **kwargs)
    return decorated


@app.route('/admin')
@_require_admin
def admin():
    stats = engine.get_learning_stats()
    s = engine.get_stats()
    player_fetishes = [f for f in engine.fetishes if f['id'] >= PLAYER_FETISH_BASE_ID]
    question_stats   = engine.get_question_stats()
    corr_stats       = engine.get_correlation_stats(top_n=30)
    fetish_log       = engine.get_fetish_log()
    fetish_log_rows  = []
    for f in engine.fetishes:
        lg = fetish_log.get(f['id'], {'guessed': 0, 'correct': 0, 'wrong': 0})
        guessed = lg['guessed']
        correct = lg['correct']
        wrong   = lg['wrong']
        acc = round(correct / guessed * 100) if guessed else None
        fetish_log_rows.append({
            'id': f['id'], 'name': f['name'],
            'guessed': guessed, 'correct': correct, 'wrong': wrong, 'acc': acc,
        })
    fetish_log_rows.sort(key=lambda r: -r['guessed'])
    domain_suggestions = engine.get_top_questions_per_fetish(top_n=5)
    stats_history  = engine.get_stats_history(days=30)
    matrix_heatmap = engine.get_matrix_heatmap(n_fetishes=20, n_questions=20)
    axis_stats     = engine.get_axis_stats()
    return render_template('admin.html', stats=stats, play_count=s['play_count'],
                           learn_count=s['learn_count'], player_fetishes=player_fetishes,
                           question_stats=question_stats, corr_stats=corr_stats,
                           fetish_log_rows=fetish_log_rows,
                           domain_suggestions=domain_suggestions,
                           engine_config=engine.config,
                           config_defaults=engine._CONFIG_DEFAULTS,
                           stats_history=stats_history,
                           matrix_heatmap=matrix_heatmap,
                           axis_stats=axis_stats)


@app.route('/api/admin/toggle_question/<int:q_id>', methods=['POST'])
@_require_admin
def toggle_question(q_id):
    if q_id < 0 or q_id >= len(engine.questions):
        return jsonify({'status': 'error', 'message': '不正な質問IDです'}), 400
    disabled = engine.toggle_question_disabled(q_id)
    return jsonify({'status': 'ok', 'disabled': disabled})


@app.route('/api/admin/params', methods=['POST'])
@_require_admin
def update_params():
    data = request.get_json(silent=True) or {}
    updated = {}
    errors  = []
    for key, val in data.items():
        try:
            engine.set_config(key, val)
            updated[key] = engine.config[key]
        except (ValueError, KeyError) as e:
            errors.append(str(e))
    return jsonify({'status': 'ok', 'updated': updated, 'errors': errors})


@app.route('/api/admin/cleanup_sessions', methods=['POST'])
@_require_admin
def admin_cleanup_sessions():
    deleted = cleanup_sessions()
    return jsonify({'status': 'ok', 'deleted': deleted})


@app.route('/api/admin/add_fetish', methods=['POST'])
@_require_admin
def admin_add_fetish():
    data = request.get_json(silent=True) or {}
    name = data.get('name', '').strip()
    desc = data.get('desc', '').strip()
    if not name:
        return jsonify({'status': 'error', 'message': '名前を入力してください'}), 400
    if len(name) > 100:
        return jsonify({'status': 'error', 'message': '名前は100文字以内'}), 400
    if len(desc) > 500:
        return jsonify({'status': 'error', 'message': '説明は500文字以内'}), 400
    existing = next((f for f in engine.fetishes if f['name'] == name), None)
    if existing:
        return jsonify({'status': 'exists', 'fetish_id': existing['id'], 'fetish_name': existing['name']})
    if not desc:
        desc = name
    _, db_id = engine.add_fetish(name, desc, {})
    return jsonify({'status': 'created', 'fetish_id': db_id, 'fetish_name': name})


@app.route('/api/admin/capture_priors', methods=['POST'])
@_require_admin
def admin_capture_priors():
    engine.capture_learned_priors()
    return jsonify({'status': 'ok'})


@app.route('/api/admin/promote_fetish/<int:fetish_id>', methods=['POST'])
@_require_admin
def admin_promote_fetish(fetish_id):
    if fetish_id < PLAYER_FETISH_BASE_ID:
        return jsonify({'status': 'error', 'message': 'シード性癖は格上げ不要です'}), 400
    new_id = engine.promote_fetish(fetish_id)
    if new_id is None:
        return jsonify({'status': 'error', 'message': '見つかりません'}), 404
    return jsonify({'status': 'promoted', 'old_id': fetish_id, 'new_id': new_id})


@app.route('/api/admin/edit_question/<int:q_idx>', methods=['POST'])
@_require_admin
def admin_edit_question(q_idx):
    data = request.get_json(silent=True) or {}
    text = (data.get('text') or '').strip()
    if not text:
        return jsonify({'status': 'error', 'message': 'text が必要です'}), 400
    if len(text) > 120:
        return jsonify({'status': 'error', 'message': '質問は120文字以内'}), 400
    ok = engine.edit_question(q_idx, text)
    if not ok:
        return jsonify({'status': 'error', 'message': '不正なインデックスです'}), 404
    return jsonify({'status': 'ok', 'q_idx': q_idx, 'text': text})


@app.route('/api/admin/edit_fetish/<int:fetish_id>', methods=['POST'])
@_require_admin
def admin_edit_fetish(fetish_id):
    data = request.get_json(silent=True) or {}
    name = data.get('name', '').strip() or None
    desc = data.get('desc', '').strip() if 'desc' in data else None
    works = None
    if 'works' in data:
        raw = data['works']
        if isinstance(raw, list):
            works = [str(w).strip() for w in raw if str(w).strip()]
        else:
            works = [w.strip() for w in str(raw).split(',') if w.strip()]
    if name is not None and len(name) > 50:
        return jsonify({'status': 'error', 'message': '名前は50文字以内'}), 400
    if works is not None and len(works) > 10:
        return jsonify({'status': 'error', 'message': '作品は10件以内'}), 400
    ok = engine.edit_fetish(fetish_id, name=name, desc=desc, works=works)
    if not ok:
        return jsonify({'status': 'error', 'message': '見つかりません'}), 404
    idx = engine.index_of(fetish_id)
    f = engine.fetishes[idx]
    return jsonify({'status': 'ok', 'name': f['name'], 'desc': f['desc'], 'works': f.get('works', [])})


@app.route('/api/admin/compound_works', methods=['GET'])
@_require_admin
def admin_list_compound_works():
    items = list_compound_works()
    # 各ペアに性癖名を付与
    result = []
    for item in items:
        ia = engine.index_of(item['id_a'])
        ib = engine.index_of(item['id_b'])
        name_a = engine.fetishes[ia]['name'] if ia is not None else f"id={item['id_a']}"
        name_b = engine.fetishes[ib]['name'] if ib is not None else f"id={item['id_b']}"
        result.append({**item, 'name_a': name_a, 'name_b': name_b})
    return jsonify(result)


@app.route('/api/admin/compound_works', methods=['POST'])
@_require_admin
def admin_set_compound_works():
    data = request.get_json(silent=True) or {}
    try:
        id_a = int(data['id_a'])
        id_b = int(data['id_b'])
    except (KeyError, ValueError, TypeError):
        return jsonify({'status': 'error', 'message': 'id_a と id_b が必要です'}), 400
    if id_a == id_b:
        return jsonify({'status': 'error', 'message': '同じIDは指定できません'}), 400
    raw = data.get('works', [])
    if isinstance(raw, str):
        works = [w.strip() for w in raw.split(',') if w.strip()]
    else:
        works = [str(w).strip() for w in raw if str(w).strip()]
    if not works:
        return jsonify({'status': 'error', 'message': '作品を1件以上入力してください'}), 400
    if len(works) > 10:
        return jsonify({'status': 'error', 'message': '作品は10件以内'}), 400
    key = set_compound_works(id_a, id_b, works)
    return jsonify({'status': 'ok', 'key': key, 'works': works})


@app.route('/api/admin/compound_works/<path:key>', methods=['DELETE'])
@_require_admin
def admin_delete_compound_works(key):
    parts = key.split(',')
    if len(parts) != 2:
        return jsonify({'status': 'error', 'message': '不正なキーです'}), 400
    try:
        id_a, id_b = int(parts[0]), int(parts[1])
    except ValueError:
        return jsonify({'status': 'error', 'message': '不正なキーです'}), 400
    ok = delete_compound_works(id_a, id_b)
    if not ok:
        return jsonify({'status': 'error', 'message': '見つかりません'}), 404
    return jsonify({'status': 'deleted', 'key': key})


@app.route('/health')
def health():
    db_ok = False
    if _use_db():
        conn = None
        try:
            conn = _get_conn()
            conn.cursor().execute('SELECT 1')
            db_ok = True
        except Exception:
            pass
        finally:
            if conn is not None:
                _put_conn(conn)
    return jsonify({'status': 'ok', 'db': db_ok,
                    'fetishes': len(engine.fetishes),
                    'questions': len(engine.questions)})


@app.route('/api/admin/merge_fetishes', methods=['POST'])
@_require_admin
def admin_merge_fetishes():
    data     = request.get_json(silent=True) or {}
    id_keep  = data.get('id_keep')
    id_rm    = data.get('id_remove')
    new_name = (data.get('new_name') or '').strip() or None
    new_desc = (data.get('new_desc') or '').strip() or None
    if id_keep is None or id_rm is None:
        return jsonify({'status': 'error', 'message': 'id_keep と id_remove が必要です'}), 400
    ok = engine.merge_fetishes(int(id_keep), int(id_rm), new_name=new_name, new_desc=new_desc)
    if not ok:
        return jsonify({'status': 'error', 'message': '性癖が見つかりません'}), 404
    idx  = engine.index_of(int(id_keep))
    name = engine.fetishes[idx]['name'] if idx is not None else '(unknown)'
    return jsonify({'status': 'merged', 'id_keep': id_keep, 'name': name})


@app.route('/api/admin/export_matrix', methods=['GET'])
@_require_admin
def admin_export_matrix():
    fetishes  = engine.fetishes
    questions = engine.questions
    rows = []
    for fi, f in enumerate(fetishes):
        for qi, q in enumerate(questions):
            y = engine.matrix['yes'][fi][qi]
            t = engine.matrix['total'][fi][qi]
            rows.append({'fetish_id': f['id'], 'fetish_name': f['name'],
                         'question_id': qi, 'question_text': q['text'],
                         'yes': round(y, 4), 'total': round(t, 4)})
    payload = _json.dumps({'fetishes': fetishes, 'matrix_rows': rows}, ensure_ascii=False, indent=2)
    return Response(payload, mimetype='application/json',
                    headers={'Content-Disposition': 'attachment; filename="matrix_export.json"'})


@app.route('/api/admin/export_log', methods=['GET'])
@_require_admin
def admin_export_log():
    log = engine.get_fetish_log()
    fetish_map = {f['id']: f['name'] for f in engine.fetishes}
    lines = ['id,name,guessed,correct,wrong,accuracy']
    for fid, entry in sorted(log.items(), key=lambda kv: -kv[1].get('guessed', 0)):
        name    = fetish_map.get(fid, str(fid))
        guessed = entry.get('guessed', 0)
        correct = entry.get('correct', 0)
        wrong   = entry.get('wrong', 0)
        acc     = f"{round(correct/guessed*100,1)}" if guessed else ''
        name_esc = '"' + name.replace('"', '""') + '"'
        lines.append(f'{fid},{name_esc},{guessed},{correct},{wrong},{acc}')
    csv_body = '\n'.join(lines)
    return Response(csv_body, mimetype='text/csv; charset=utf-8',
                    headers={'Content-Disposition': 'attachment; filename="fetish_log.csv"'})


@app.route('/api/admin/fetish_history/<int:fetish_id>', methods=['GET'])
@_require_admin
def admin_fetish_history(fetish_id):
    days = request.args.get('days', 30, type=int)
    history = engine.get_fetish_history(fetish_id, days=min(days, 90))
    return jsonify(history)


@app.route('/api/admin/export_stats_history', methods=['GET'])
@_require_admin
def admin_export_stats_history():
    history = engine.get_stats_history(days=90)
    lines = ['date,play,learn,correct,wrong']
    for row in history:
        lines.append(f"{row['date']},{row.get('play',0)},{row.get('learn',0)},"
                     f"{row.get('correct',0)},{row.get('wrong',0)}")
    return Response('\n'.join(lines), mimetype='text/csv; charset=utf-8',
                    headers={'Content-Disposition': 'attachment; filename="stats_history.csv"'})


@app.route('/api/admin/fetish_similarity', methods=['POST'])
@_require_admin
def admin_fetish_similarity():
    data = request.get_json(silent=True) or {}
    id_a = data.get('id_a')
    id_b = data.get('id_b')
    if id_a is None or id_b is None:
        return jsonify({'status': 'error', 'message': 'id_a と id_b が必要です'}), 400
    result = engine.fetish_similarity(int(id_a), int(id_b))
    if result is None:
        return jsonify({'status': 'error', 'message': '性癖が見つかりません'}), 404
    return jsonify({'status': 'ok', **result})


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
