import os
import re
import hmac
import hashlib
import functools
import unicodedata
from flask import Flask, render_template, request, jsonify, session, Response, send_from_directory
from engine import Engine, PLAYER_FETISH_BASE_ID

app = Flask(__name__)
_secret = os.environ.get('SECRET_KEY')
if not _secret:
    if os.environ.get('DATABASE_URL'):
        raise RuntimeError('本番環境では SECRET_KEY 環境変数の設定が必須です')
    import warnings
    warnings.warn('SECRET_KEY が未設定です。本番環境では環境変数に設定してください。', stacklevel=1)
    _secret = 'hekineitor_dev_secret_2024'
app.secret_key = _secret

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
DISPLAY_VERSION = 'v1.0.0'
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
    session.clear()
    session['answers'] = {}
    session['asked']   = []
    session['started'] = True
    q = engine.best_question({}, set())
    session['asked'].append(q)
    return jsonify({
        'question_id': q,
        'question':    engine.questions[q]['text'],
        'count':       0,
        'total':       MAX_QUESTIONS,
    })


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

    top2 = engine.top_guess(answers, n=2)
    top_p  = top2[0][1]
    second_p = top2[1][1] if len(top2) > 1 else 0.0
    count = len(asked)

    # 終了条件: idk連続4回 / 問題数上限 / 通常閾値 / 早期打ち切り（5問以上かつ確信度高）
    early_stop = count >= 5 and top_p >= 0.65 and (top_p - second_p) >= 0.25
    if idk_streak >= 4 or top_p >= GUESS_THRESHOLD or count >= MAX_QUESTIONS or early_stop:
        return _make_guess(answers)

    next_q = engine.best_question(answers, set(asked), idk_streak=idk_streak)
    if next_q is None:
        return _make_guess(answers)

    asked.append(next_q)
    session['asked'] = asked

    return jsonify({
        'action':      'question',
        'question_id': next_q,
        'question':    engine.questions[next_q]['text'],
        'count':       count,
        'total':       MAX_QUESTIONS,
    })


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
    top_p  = max(probs) if probs else GUESS_THRESHOLD
    conf   = max(0.5, min(2.0, GUESS_THRESHOLD / max(top_p, 0.1)))
    n_scale = 1.0 / _math.sqrt(max(total_n, 1))
    return max(0.3, min(2.0, conf * n_scale))


def _compute_guess(answers):
    """診断結果を返す（play_count はインクリメントしない、純粋計算）。
    レスポンスの fetish_id 系は全てDB id（永続的・プレイヤー追加性癖でも安全）。"""
    probs   = engine.posteriors(answers)
    ranked  = sorted(range(len(probs)), key=lambda i: probs[i], reverse=True)
    best_i  = ranked[0]
    best_p  = probs[best_i]
    best_f  = engine.fetishes[best_i]
    best_db = best_f['id']

    compound = []
    compound_db_ids = set()
    if len(ranked) > 1 and probs[ranked[1]] >= best_p * COMPOUND_RATIO:
        c = engine.fetishes[ranked[1]]
        compound.append({'fetish_id': c['id'],
                         'fetish_name': c['name'],
                         'probability': round(probs[ranked[1]] * 100, 1)})
        compound_db_ids.add(c['id'])
        if len(ranked) > 2 and probs[ranked[2]] >= best_p * TRIPLE_RATIO:
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

    return {
        'action':      'guess',
        'fetish_id':   best_db,
        'fetish_name': best_f['name'],
        'fetish_desc': best_f['desc'],
        'probability': round(best_p * 100, 1),
        'compound':    compound,
        'profile':     profile,
        'related':     related,
    }


def _make_guess(answers):
    engine.increment_play_count()
    return jsonify(_compute_guess(answers))


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
        return jsonify({'status': 'learned'})
    else:
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
        sorted_fetishes = [f for _, f in candidates[:20]]
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
    total_n  = max(1, int(data.get('total_n', 1)))
    engine.learn(answers, f_idx, strength_factor=_learn_factor(answers, total_n))
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
            engine.boost_learn_new(idx, answers)  # boost は独自スケーリング済み
        else:
            engine.learn(answers, idx, strength_factor=factor)
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
    return render_template('admin.html', stats=stats, play_count=s['play_count'],
                           learn_count=s['learn_count'], player_fetishes=player_fetishes,
                           question_stats=question_stats, corr_stats=corr_stats)


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
