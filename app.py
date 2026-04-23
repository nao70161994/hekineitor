from flask import Flask, render_template, request, jsonify, session
from engine import Engine

app = Flask(__name__)
app.secret_key = 'hekineitor_secret_2024'
engine = Engine()

GUESS_THRESHOLD = 0.75
MAX_QUESTIONS   = 20


@app.route('/')
def index():
    return render_template('index.html')


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
    data    = request.json
    q_idx   = int(data['question_id'])
    ans     = int(data['answer'])  # 1=はい, -1=いいえ, 0=わからない

    answers = session.get('answers', {})
    asked   = session.get('asked', [])

    answers[str(q_idx)] = ans
    session['answers']  = answers

    top_f, top_p = engine.top_guess(answers)
    count = len(asked)

    if top_p >= GUESS_THRESHOLD or count >= MAX_QUESTIONS:
        return _make_guess(top_f, top_p)

    next_q = engine.best_question(answers, set(asked))
    if next_q is None:
        return _make_guess(top_f, top_p)

    asked.append(next_q)
    session['asked'] = asked

    return jsonify({
        'action':      'question',
        'question_id': next_q,
        'question':    engine.questions[next_q]['text'],
        'count':       count,
        'total':       MAX_QUESTIONS,
    })


def _make_guess(f_idx, prob):
    f = engine.fetishes[f_idx]
    return jsonify({
        'action':      'guess',
        'fetish_id':   f_idx,
        'fetish_name': f['name'],
        'fetish_desc': f['desc'],
        'probability': round(prob * 100, 1),
    })


@app.route('/api/confirm', methods=['POST'])
def confirm():
    data    = request.json
    correct = data['correct']
    f_idx   = int(data['fetish_id'])
    answers = session.get('answers', {})

    if correct:
        engine.learn(answers, f_idx)
        return jsonify({'status': 'learned'})
    else:
        # 外れ → 全性癖リストを返す（ユーザーが正解を教える）
        return jsonify({
            'status':    'wrong',
            'fetishes':  engine.fetishes,
        })


@app.route('/api/teach', methods=['POST'])
def teach():
    data    = request.json
    f_idx   = int(data['fetish_id'])
    answers = session.get('answers', {})
    engine.learn(answers, f_idx)
    return jsonify({'status': 'learned', 'fetish_name': engine.fetishes[f_idx]['name']})


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
