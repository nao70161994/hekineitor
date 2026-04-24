import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import unittest
from unittest.mock import patch
import engine as eng_module
from engine import Engine

MATRIX_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'matrix.json')

class TestEngine(unittest.TestCase):
    def setUp(self):
        # matrix.json を退避して常にフレッシュな状態でテスト
        self._matrix_backup = None
        if os.path.exists(MATRIX_PATH):
            with open(MATRIX_PATH, 'rb') as f:
                self._matrix_backup = f.read()
            os.remove(MATRIX_PATH)

        # ファイル書き込みをモックして本番データを汚さない
        self._patches = [
            patch.object(Engine, '_save_matrix_file',  return_value=None),
            patch.object(Engine, '_save_fetishes_file', return_value=None),
            patch.object(Engine, '_save_to_db',        return_value=None),
        ]
        for p in self._patches:
            p.start()
        self.e = Engine()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        # matrix.json を元に戻す
        if self._matrix_backup is not None:
            with open(MATRIX_PATH, 'wb') as f:
                f.write(self._matrix_backup)

    # ── posteriors ────────────────────────────────────────
    def test_posteriors_uniform_with_no_answers(self):
        probs = self.e.posteriors({})
        self.assertAlmostEqual(sum(probs), 1.0, places=6)
        mean = 1.0 / len(probs)
        for p in probs:
            self.assertAlmostEqual(p, mean, places=6)

    def test_posteriors_increases_matching_fetish(self):
        probs_before = self.e.posteriors({})
        probs_after  = self.e.posteriors({'8': 1})   # Q8=裏切り → NTR(0) が上がる
        self.assertGreater(probs_after[0], probs_before[0])

    def test_posteriors_sums_to_one(self):
        probs = self.e.posteriors({'0': 1, '3': -1, '9': 0.5, '15': -0.5})
        self.assertAlmostEqual(sum(probs), 1.0, places=6)

    def test_posteriors_ignores_zero_answers(self):
        p_empty = self.e.posteriors({})
        p_zero  = self.e.posteriors({'0': 0, '5': 0})
        for a, b in zip(p_empty, p_zero):
            self.assertAlmostEqual(a, b, places=6)

    # ── top_guess ─────────────────────────────────────────
    def test_top_guess_returns_valid_index(self):
        idx, prob = self.e.top_guess({})
        self.assertGreaterEqual(idx, 0)
        self.assertLess(idx, len(self.e.fetishes))
        self.assertGreater(prob, 0.0)
        self.assertLessEqual(prob, 1.0)

    def test_top_guess_n3_returns_three_descending(self):
        top3 = self.e.top_guess({}, n=3)
        self.assertEqual(len(top3), 3)
        probs = [p for _, p in top3]
        self.assertEqual(probs, sorted(probs, reverse=True))

    # ── best_question ─────────────────────────────────────
    def test_best_question_returns_valid_index(self):
        q = self.e.best_question({}, set())
        self.assertIsNotNone(q)
        self.assertGreaterEqual(q, 0)
        self.assertLess(q, len(self.e.questions))

    def test_best_question_avoids_asked(self):
        asked = set(range(len(self.e.questions) - 1))
        q = self.e.best_question({}, asked)
        self.assertIsNotNone(q)
        self.assertNotIn(q, asked)

    def test_best_question_returns_none_when_all_asked(self):
        asked = set(range(len(self.e.questions)))
        self.assertIsNone(self.e.best_question({}, asked))

    # ── learn ─────────────────────────────────────────────
    def test_learn_increases_yes_count(self):
        before = self.e.matrix['yes'][0][8]
        self.e.learn({'8': 1}, 0)
        self.assertGreater(self.e.matrix['yes'][0][8], before)

    def test_learn_increases_total_count(self):
        before = self.e.matrix['total'][0][8]
        self.e.learn({'8': 1}, 0)
        self.assertGreater(self.e.matrix['total'][0][8], before)

    def test_learn_negative_updates_other_fetishes(self):
        before = self.e.matrix['total'][1][8]  # 百合(1)
        self.e.learn({'8': 1}, 0)              # NTR(0) が正解
        self.assertGreater(self.e.matrix['total'][1][8], before)

    def test_learn_proportional_to_strength(self):
        import engine as eng
        e1 = Engine(); e2 = Engine()
        b1 = e1.matrix['total'][0][9]
        b2 = e2.matrix['total'][0][9]
        e1.learn({'9': 1.0}, 0)
        e2.learn({'9': 0.5}, 0)
        delta1 = e1.matrix['total'][0][9] - b1
        delta2 = e2.matrix['total'][0][9] - b2
        self.assertAlmostEqual(delta1, delta2 * 2, places=5)

    # ── add_fetish ────────────────────────────────────────
    def test_add_fetish_increases_count(self):
        before = len(self.e.fetishes)
        self.e.add_fetish('テスト', '説明', {})
        self.assertEqual(len(self.e.fetishes), before + 1)

    def test_add_fetish_with_template_copies_distribution(self):
        nq = len(self.e.questions)
        self.e.add_fetish('テンプレートテスト', '説明', {}, template_id=3)
        new_id = len(self.e.fetishes) - 1
        for q in range(nq):
            r_new  = self.e.matrix['yes'][new_id][q] / self.e.matrix['total'][new_id][q]
            r_tmpl = self.e.matrix['yes'][3][q]       / self.e.matrix['total'][3][q]
            self.assertAlmostEqual(r_new, r_tmpl, places=5)

if __name__ == '__main__':
    unittest.main()
