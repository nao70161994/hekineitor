import json
import math
import os

try:
    import psycopg2
    import psycopg2.extras
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False

DATA_DIR     = os.path.join(os.path.dirname(__file__), 'data')
DATABASE_URL = os.environ.get('DATABASE_URL', '')

# (fetish_idx, question_idx, probability)
DOMAIN_PRIORS = [
    # NTR(0)
    (0,0,0.95),(0,3,0.45),(0,9,0.4),(0,16,0.35),(0,1,0.05),(0,2,0.05),(0,5,0.05),
    # 百合(1)
    (1,1,0.95),(1,0,0.1),(1,2,0.02),(1,4,0.15),(1,12,0.05),(1,13,0.15),
    # BL(2)
    (2,2,0.95),(2,1,0.02),(2,3,0.5),(2,0,0.1),(2,19,0.2),
    # SM(3)
    (3,3,0.95),(3,10,0.4),(3,18,0.6),(3,17,0.3),(3,5,0.3),
    # ケモノ(4)
    (4,4,0.95),(4,14,0.5),(4,5,0.15),(4,12,0.3),
    # 触手(5)
    (5,5,0.95),(5,4,0.4),(5,3,0.5),(5,14,0.3),(5,18,0.4),
    # 年上攻め(6)
    (6,6,0.9),(6,7,0.05),(6,9,0.5),(6,17,0.4),(6,3,0.3),
    # 年下攻め(7)
    (7,7,0.9),(7,6,0.05),(7,3,0.4),(7,17,0.3),
    # 義兄妹(8)
    (8,8,0.95),(8,16,0.5),(8,9,0.25),(8,17,0.5),(8,0,0.2),
    # 師弟(9)
    (9,9,0.95),(9,6,0.5),(9,3,0.4),(9,8,0.1),(9,17,0.3),
    # ヤンデレ(10)
    (10,10,0.95),(10,17,0.7),(10,3,0.5),(10,18,0.4),(10,0,0.2),
    # TSF(11)
    (11,11,0.95),(11,19,0.3),(11,12,0.3),(11,2,0.2),
    # ハーレム(12)
    (12,12,0.95),(12,13,0.05),(12,17,0.5),(12,1,0.3),(12,16,0.3),
    # 逆ハーレム(13)
    (13,13,0.95),(13,12,0.05),(13,17,0.6),(13,2,0.3),(13,16,0.3),
    # モンスター娘(14)
    (14,14,0.95),(14,4,0.7),(14,1,0.4),(14,12,0.4),(14,15,0.3),
    # 吸血鬼(15)
    (15,15,0.95),(15,4,0.5),(15,14,0.4),(15,6,0.4),(15,3,0.3),(15,17,0.4),
    # 幼馴染(16)
    (16,16,0.95),(16,8,0.3),(16,17,0.6),(16,0,0.15),(16,6,0.2),
    # 溺愛(17)
    (17,17,0.95),(17,10,0.4),(17,3,0.2),(17,16,0.4),(17,13,0.3),
    # 調教洗脳(18)
    (18,18,0.95),(18,3,0.8),(18,10,0.4),(18,5,0.3),(18,0,0.2),
    # 女装(19)
    (19,19,0.95),(19,11,0.3),(19,2,0.3),(19,3,0.3),
]

PSEUDO = 20


def _use_db():
    return bool(DATABASE_URL) and HAS_PSYCOPG2


def _get_conn():
    url = DATABASE_URL
    # Render は postgres:// で来るので修正
    if url.startswith('postgres://'):
        url = url.replace('postgres://', 'postgresql://', 1)
    return psycopg2.connect(url, sslmode='require')


def _build_initial_matrix(nf, nq):
    alpha = 2.0
    yes   = [[alpha]       * nq for _ in range(nf)]
    total = [[alpha * 2.0] * nq for _ in range(nf)]
    for f, q, p in DOMAIN_PRIORS:
        yes[f][q]   = p * PSEUDO
        total[f][q] = float(PSEUDO)
    return yes, total


class Engine:
    def __init__(self):
        self.fetishes  = self._load_json('fetishes.json')
        self.questions = self._load_json('questions.json')
        if _use_db():
            self._ensure_db()
            self.matrix = self._load_from_db()
        else:
            self.matrix = self._load_matrix_file()

    # ── JSON ローカル ──────────────────────────────────────
    def _load_json(self, fname):
        with open(os.path.join(DATA_DIR, fname), encoding='utf-8') as f:
            return json.load(f)

    def _load_matrix_file(self):
        path = os.path.join(DATA_DIR, 'matrix.json')
        if os.path.exists(path):
            with open(path, encoding='utf-8') as f:
                return json.load(f)
        return self._init_matrix_file()

    def _init_matrix_file(self):
        nf = len(self.fetishes)
        nq = len(self.questions)
        yes, total = _build_initial_matrix(nf, nq)
        m = {'yes': yes, 'total': total}
        with open(os.path.join(DATA_DIR, 'matrix.json'), 'w', encoding='utf-8') as f:
            json.dump(m, f)
        return m

    def _save_matrix_file(self):
        with open(os.path.join(DATA_DIR, 'matrix.json'), 'w', encoding='utf-8') as f:
            json.dump(self.matrix, f)

    # ── PostgreSQL ─────────────────────────────────────────
    def _ensure_db(self):
        conn = _get_conn()
        try:
            with conn:
                cur = conn.cursor()
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS matrix (
                        fetish_id   INTEGER,
                        question_id INTEGER,
                        yes_count   REAL NOT NULL,
                        total_count REAL NOT NULL,
                        PRIMARY KEY (fetish_id, question_id)
                    )
                ''')
                cur.execute('SELECT COUNT(*) FROM matrix')
                if cur.fetchone()[0] == 0:
                    self._seed_db(cur)
        finally:
            conn.close()

    def _seed_db(self, cur):
        nf = len(self.fetishes)
        nq = len(self.questions)
        yes, total = _build_initial_matrix(nf, nq)
        rows = [
            (f, q, yes[f][q], total[f][q])
            for f in range(nf) for q in range(nq)
        ]
        psycopg2.extras.execute_values(
            cur,
            'INSERT INTO matrix (fetish_id, question_id, yes_count, total_count) VALUES %s',
            rows
        )

    def _load_from_db(self):
        nf = len(self.fetishes)
        nq = len(self.questions)
        yes   = [[0.0] * nq for _ in range(nf)]
        total = [[0.0] * nq for _ in range(nf)]
        conn = _get_conn()
        try:
            cur = conn.cursor()
            cur.execute('SELECT fetish_id, question_id, yes_count, total_count FROM matrix')
            for f, q, y, t in cur.fetchall():
                yes[f][q]   = y
                total[f][q] = t
        finally:
            conn.close()
        return {'yes': yes, 'total': total}

    def _save_to_db(self, fetish_idx, updates):
        conn = _get_conn()
        try:
            with conn:
                cur = conn.cursor()
                for q_idx, delta_yes, delta_total in updates:
                    cur.execute('''
                        UPDATE matrix
                        SET yes_count   = yes_count   + %s,
                            total_count = total_count + %s
                        WHERE fetish_id = %s AND question_id = %s
                    ''', (delta_yes, delta_total, fetish_idx, q_idx))
        finally:
            conn.close()

    # ── 推論 ───────────────────────────────────────────────
    def _prob(self, f, q):
        y = self.matrix['yes'][f][q]
        t = self.matrix['total'][f][q]
        return max(min(y / t, 0.999), 0.001)

    def posteriors(self, answers):
        nf = len(self.fetishes)
        log_p = [0.0] * nf
        for q_str, ans in answers.items():
            q = int(q_str)
            if ans == 0:
                continue
            weight = abs(ans)
            for f in range(nf):
                p = self._prob(f, q)
                log_p[f] += weight * (math.log(p) if ans > 0 else math.log(1 - p))
        mx = max(log_p)
        probs = [math.exp(lp - mx) for lp in log_p]
        s = sum(probs)
        return [p / s for p in probs]

    def best_question(self, answers, asked):
        probs = self.posteriors(answers)
        h0    = self._entropy(probs)
        nf    = len(self.fetishes)
        best_q, best_gain = None, -1.0
        for q in range(len(self.questions)):
            if q in asked:
                continue
            p_yes = sum(probs[f] * self._prob(f, q) for f in range(nf))
            p_no  = 1.0 - p_yes
            if p_yes < 0.01 or p_no < 0.01:
                continue
            py = [probs[f] * self._prob(f, q) for f in range(nf)]
            sy = sum(py)
            py = [v / sy for v in py]
            pn = [probs[f] * (1 - self._prob(f, q)) for f in range(nf)]
            sn = sum(pn)
            pn = [v / sn for v in pn]
            gain = h0 - (p_yes * self._entropy(py) + p_no * self._entropy(pn))
            if gain > best_gain:
                best_gain = gain
                best_q = q
        return best_q

    def top_guess(self, answers):
        probs  = self.posteriors(answers)
        best_f = max(range(len(probs)), key=lambda i: probs[i])
        return best_f, probs[best_f]

    def learn(self, answers, fetish_idx):
        updates = []
        for q_str, ans in answers.items():
            q = int(q_str)
            delta_yes = 1 if ans == 1 else 0
            self.matrix['total'][fetish_idx][q] += 1
            self.matrix['yes'][fetish_idx][q]   += delta_yes
            updates.append((q, delta_yes, 1))
        if _use_db():
            self._save_to_db(fetish_idx, updates)
        else:
            self._save_matrix_file()

    def _entropy(self, probs):
        return -sum(p * math.log2(p) for p in probs if p > 1e-10)
