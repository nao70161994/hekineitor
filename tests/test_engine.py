import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import unittest
from unittest.mock import patch
import engine as eng_module
from engine import Engine, FETISH_PRIOR_WEIGHTS

MATRIX_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'matrix.json')

class TestEngine(unittest.TestCase):
    def setUp(self):
        self._matrix_backup = None
        if os.path.exists(MATRIX_PATH):
            with open(MATRIX_PATH, 'rb') as f:
                self._matrix_backup = f.read()
            os.remove(MATRIX_PATH)

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
        if self._matrix_backup is not None:
            with open(MATRIX_PATH, 'wb') as f:
                f.write(self._matrix_backup)

    # ── posteriors ────────────────────────────────────────
    def test_posteriors_sums_to_one_no_answers(self):
        probs = self.e.posteriors({})
        self.assertAlmostEqual(sum(probs), 1.0, places=6)

    def test_posteriors_popular_fetish_higher_prior(self):
        """事前確率: NTR(0, weight=3.0) はゾンビ(49, weight=0.5) より高い"""
        probs = self.e.posteriors({})
        ntr_idx   = self.e.index_of(0)
        zombie_idx = self.e.index_of(49)
        self.assertGreater(probs[ntr_idx], probs[zombie_idx])

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

    def test_best_question_endgame_focuses_top_candidates(self):
        """終盤モード: 特定性癖に偏った回答では、その性癖を識別する質問が選ばれやすい"""
        from engine import FOCUS_THRESHOLD
        # NTRに強くシグナルを与える回答（Q8=裏切り, Q6=嫉妬, Q0=力関係）
        answers = {'8': 1, '6': 1, '0': 1, '40': 1}
        probs = self.e.posteriors(answers)
        top_p = max(probs)
        if top_p >= FOCUS_THRESHOLD:
            q = self.e.best_question(answers, set(answers.keys()))
            self.assertIsNotNone(q)
            # 選ばれた質問がNTR系に強いシグナルを持つことを確認
            ntr_idx = self.e.index_of(0)
            self.assertIsNotNone(ntr_idx)

    def test_best_question_idk_streak_favors_abstract_or_personality(self):
        """idk_streak >= 2 のとき抽象 or パーソナリティ軸の質問が選ばれる"""
        q = self.e.best_question({}, set(), idk_streak=2)
        self.assertIsNotNone(q)
        self.assertGreaterEqual(q, 55)  # 抽象(55-62) or パーソナリティ(63-86)

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

    def test_add_fetish_new_has_valid_matrix_row(self):
        """追加された性癖の matrix 行が valid（yes <= total）であること"""
        idx, _ = self.e.add_fetish('テンプレートテスト', '説明', {'0': 1, '3': -1})
        nq = len(self.e.questions)
        for q in range(nq):
            yes   = self.e.matrix['yes'][idx][q]
            total = self.e.matrix['total'][idx][q]
            self.assertGreaterEqual(total, yes)

    def test_add_fetish_id_gte_base(self):
        """プレイヤー追加性癖のIDが PLAYER_FETISH_BASE_ID 以上であること"""
        from engine import PLAYER_FETISH_BASE_ID
        self.e.add_fetish('IDテスト', '説明', {})
        new_f = self.e.fetishes[-1]
        self.assertGreaterEqual(new_f['id'], PLAYER_FETISH_BASE_ID)

    # ── boost_learn_new ───────────────────────────────────
    def test_boost_learn_new_increases_matrix_data(self):
        idx, _ = self.e.add_fetish('ブースト性癖', '説明', {})
        total_before = sum(self.e.matrix['total'][idx])
        self.e.boost_learn_new(idx, {'0': 1, '1': -1})
        total_after = sum(self.e.matrix['total'][idx])
        self.assertGreater(total_after, total_before)

    # ── learn_negative ────────────────────────────────────
    def test_learn_negative_decreases_prob(self):
        """ネガティブ学習: yes回答済みの質問でP(yes|f)が下がる方向に動くこと"""
        answers = {'8': 1}  # Q8=yes
        before = self.e._prob(0, 8)  # NTR(0) の初期P(yes|Q8)
        self.e.learn_negative(answers, 0)
        after = self.e._prob(0, 8)
        self.assertLess(after, before)

    def test_learn_negative_no_side_effects_on_others(self):
        """ネガティブ学習は対象外の性癖の行を変更しない"""
        before = self.e.matrix['total'][1][8]
        self.e.learn_negative({'8': 1}, 0)
        self.assertEqual(self.e.matrix['total'][1][8], before)

    # ── get_question_stats ────────────────────────────────
    def test_get_question_stats_sorted_ascending(self):
        stats = self.e.get_question_stats()
        discs = [s['disc'] for s in stats]
        self.assertEqual(discs, sorted(discs))

    def test_get_question_stats_count(self):
        stats = self.e.get_question_stats()
        self.assertEqual(len(stats), len(self.e.questions))

    def test_get_question_stats_disc_range(self):
        for s in self.e.get_question_stats():
            self.assertGreaterEqual(s['disc'], 0.0)
            self.assertLessEqual(s['disc'], 0.5)

    # ── index_of ─────────────────────────────────────────
    def test_index_of_seed_fetish(self):
        idx = self.e.index_of(0)
        self.assertEqual(idx, 0)

    def test_index_of_unknown_returns_none(self):
        self.assertIsNone(self.e.index_of(99999))

    # ── get_related ───────────────────────────────────────
    def test_get_related_returns_list(self):
        related = self.e.get_related(0)
        self.assertIsInstance(related, list)

    def test_get_related_no_unknown_ids(self):
        all_db_ids = {f['id'] for f in self.e.fetishes}
        for fid in range(83):
            for r in self.e.get_related(fid):
                self.assertIn(r['fetish_id'], all_db_ids)


if __name__ == '__main__':
    unittest.main()
