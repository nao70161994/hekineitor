import os
import hmac
import hashlib
import functools
from flask import Flask, render_template, request, jsonify, session, Response, send_from_directory
from engine import Engine

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

APP_VERSION = _app_version()
engine = Engine()

GUESS_THRESHOLD = 0.75
MAX_QUESTIONS   = 20


@app.route('/')
def index():
    return render_template('index.html')


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

    top_f, top_p = engine.top_guess(answers)
    count = len(asked)

    # わからない4連続 or 通常の終了条件で診断へ
    if idk_streak >= 4 or top_p >= GUESS_THRESHOLD or count >= MAX_QUESTIONS:
        return _make_guess(answers)

    next_q = engine.best_question(answers, set(asked))
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


PROFILE_MIN_RATIO = 0.25   # best_p に対する比率の下限
PROFILE_MIN_PROB  = 0.08   # 絶対確率の下限
COMPOUND_RATIO    = 0.55   # 2位がこの比率以上なら複合
TRIPLE_RATIO      = 0.45   # 3位がこの比率以上なら三重複合

def _make_guess(answers):
    engine.increment_play_count()
    probs   = engine.posteriors(answers)
    ranked  = sorted(range(len(probs)), key=lambda i: probs[i], reverse=True)
    best_f  = ranked[0]
    best_p  = probs[best_f]
    f       = engine.fetishes[best_f]

    # 複合判定
    compound = []
    compound_ids = set()
    if len(ranked) > 1 and probs[ranked[1]] >= best_p * COMPOUND_RATIO:
        compound.append({'fetish_id': ranked[1],
                         'fetish_name': engine.fetishes[ranked[1]]['name'],
                         'probability': round(probs[ranked[1]] * 100, 1)})
        compound_ids.add(ranked[1])
        if len(ranked) > 2 and probs[ranked[2]] >= best_p * TRIPLE_RATIO:
            compound.append({'fetish_id': ranked[2],
                             'fetish_name': engine.fetishes[ranked[2]]['name'],
                             'probability': round(probs[ranked[2]] * 100, 1)})
            compound_ids.add(ranked[2])

    threshold = max(best_p * PROFILE_MIN_RATIO, PROFILE_MIN_PROB)
    profile = [
        {'fetish_id': fi, 'fetish_name': engine.fetishes[fi]['name'],
         'probability': round(probs[fi] * 100, 1)}
        for fi in ranked[1:]
        if probs[fi] >= threshold and fi not in compound_ids
    ]

    profile_ids = {p['fetish_id'] for p in profile}
    related_src = [best_f] + list(compound_ids)
    related_seen = profile_ids | compound_ids | {best_f}
    related = []
    for src in related_src:
        for r in engine.get_related(src):
            if r['fetish_id'] not in related_seen:
                related.append(r)
                related_seen.add(r['fetish_id'])

    return jsonify({
        'action':      'guess',
        'fetish_id':   best_f,
        'fetish_name': f['name'],
        'fetish_desc': f['desc'],
        'probability': round(best_p * 100, 1),
        'compound':    compound,
        'profile':     profile,
        'related':     related,
    })


@app.route('/api/confirm', methods=['POST'])
def confirm():
    data = request.get_json(silent=True) or {}
    if 'correct' not in data or 'fetish_id' not in data:
        return jsonify({'status': 'error', 'message': 'correct と fetish_id が必要です'}), 400
    try:
        f_idx = int(data['fetish_id'])
    except (ValueError, TypeError):
        return jsonify({'status': 'error', 'message': '不正な fetish_id です'}), 400
    if f_idx < 0 or f_idx >= len(engine.fetishes):
        return jsonify({'status': 'error', 'message': '存在しない fetish_id です'}), 400
    correct = data['correct']
    answers = session.get('answers', {})

    if correct:
        learn_ids = [f_idx]
        for cid in data.get('compound_ids', []):
            try:
                cid = int(cid)
                if 0 <= cid < len(engine.fetishes) and cid != f_idx:
                    learn_ids.append(cid)
            except (ValueError, TypeError):
                pass
        for fid in learn_ids:
            engine.learn(answers, fid)
        return jsonify({'status': 'learned'})
    else:
        fetishes_snapshot = list(engine.fetishes)
        probs = engine.posteriors(answers)
        nf = len(probs)
        sorted_fetishes = sorted(
            [f for f in fetishes_snapshot if f['id'] < nf],
            key=lambda f: probs[f['id']], reverse=True,
        )
        return jsonify({'status': 'wrong', 'fetishes': sorted_fetishes})


@app.route('/api/teach', methods=['POST'])
def teach():
    data = request.get_json(silent=True) or {}
    if 'fetish_id' not in data:
        return jsonify({'status': 'error', 'message': 'fetish_id が必要です'}), 400
    try:
        f_idx = int(data['fetish_id'])
    except (ValueError, TypeError):
        return jsonify({'status': 'error', 'message': '不正な fetish_id です'}), 400
    if f_idx < 0 or f_idx >= len(engine.fetishes):
        return jsonify({'status': 'error', 'message': '存在しない fetish_id です'}), 400
    answers = session.get('answers', {})
    engine.learn(answers, f_idx)
    return jsonify({'status': 'learned', 'fetish_name': engine.fetishes[f_idx]['name']})


@app.route('/api/add_fetish', methods=['POST'])
def add_fetish():
    data        = request.get_json(silent=True) or {}
    name        = data.get('name', '').strip()
    desc        = data.get('desc', '').strip()
    template_id = data.get('template_id')
    answers     = session.get('answers', {})
    if not name:
        return jsonify({'status': 'error', 'message': '名前を入力してください'}), 400
    if len(name) > 100:
        return jsonify({'status': 'error', 'message': '名前は100文字以内で入力してください'}), 400
    if not desc:
        desc = name
    if template_id is not None:
        try:
            template_id = int(template_id)
        except (ValueError, TypeError):
            return jsonify({'status': 'error', 'message': '不正な template_id です'}), 400
        if template_id < 0 or template_id >= len(engine.fetishes):
            return jsonify({'status': 'error', 'message': '存在しない template_id です'}), 400
    new_id = engine.add_fetish(name, desc, answers, template_id=template_id)
    return jsonify({'status': 'learned', 'fetish_name': name, 'fetish_id': new_id})


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
    return render_template('admin.html', stats=stats, play_count=s['play_count'], learn_count=s['learn_count'])


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
