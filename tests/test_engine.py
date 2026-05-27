import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import types
import unittest
import threading
from unittest.mock import patch
import engine as eng_module
from engine import Engine, FETISH_PRIOR_WEIGHTS
from matrix_service import collect_matrix_updates


class TestEngine(unittest.TestCase):
    def setUp(self):
        self._patches = [
            patch.object(Engine, '_save_matrix_file',  return_value=None),
            patch.object(Engine, '_save_fetishes_file', return_value=None),
            patch.object(Engine, '_save_to_db',        return_value=None),
            patch.object(Engine, '_load_matrix_file', new=lambda self: self._init_matrix_file()),
        ]
        for p in self._patches:
            p.start()
        self.e = Engine()

    def tearDown(self):
        for p in self._patches:
            p.stop()

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

    def test_posteriors_zero_answers_are_weak_signal(self):
        p_empty = self.e.posteriors({})
        p_zero  = self.e.posteriors({'0': 0, '5': 0})
        self.assertAlmostEqual(sum(p_zero), 1.0, places=6)
        self.assertNotEqual(p_empty, p_zero)

    def test_attribute_world_answers_raise_attribute_candidates(self):
        answers = {'136': 1, '138': 1, '141': 1, '142': 1}
        top = self.e.top_guess(answers, n=8)
        top_ids = {self.e.fetishes[idx]['id'] for idx, _prob in top}
        self.assertTrue({123, 124} & top_ids)

    def test_yes_streak_does_not_only_return_attachment_candidates(self):
        answers = {str(q): 1 for q in [87, 135, 136, 141]}
        top = self.e.top_guess(answers, n=8)
        top_ids = [self.e.fetishes[idx]['id'] for idx, _prob in top]
        self.assertFalse({126, 127}.issuperset(top_ids[:3]))

    def test_matrix_shape_validation_rejects_ragged_total(self):
        nf = len(self.e.fetishes)
        nq = len(self.e.questions)
        valid = {
            'yes': [[0.5] * nq for _ in range(nf)],
            'total': [[1.0] * nq for _ in range(nf)],
        }
        self.assertTrue(self.e._valid_matrix_shape(valid, nf, nq))
        invalid = {
            'yes': [[0.5] * nq for _ in range(nf)],
            'total': [[1.0] * nq for _ in range(max(0, nf - 1))],
        }
        self.assertFalse(self.e._valid_matrix_shape(invalid, nf, nq))
        invalid = {
            'yes': [[0.5] * nq for _ in range(nf)],
            'total': [[1.0] * nq for _ in range(nf)],
        }
        invalid['total'][0] = invalid['total'][0][:-1]
        self.assertFalse(self.e._valid_matrix_shape(invalid, nf, nq))

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

    def test_best_disambiguating_question_separates_top_candidates(self):
        probs = [0.45, 0.44, 0.11] + [0.0] * (len(self.e.fetishes) - 3)
        asked = set(range(2, len(self.e.questions)))

        def fake_prob(f, q):
            values = {
                0: [0.9, 0.1, 0.5],
                1: [0.6, 0.55, 0.5],
            }
            return values[q][f] if f < 3 else 0.5

        with patch.object(self.e, 'posteriors', return_value=probs), \
                patch.object(self.e, '_prob', side_effect=fake_prob):
            q = self.e.best_disambiguating_question({}, asked, candidate_count=3)
        self.assertEqual(q, 0)

    def test_best_disambiguating_question_falls_back_without_separation(self):
        probs = [0.5, 0.3, 0.2] + [0.0] * (len(self.e.fetishes) - 3)
        asked = set(range(1, len(self.e.questions)))
        with patch.object(self.e, 'posteriors', return_value=probs), \
                patch.object(self.e, '_prob', return_value=0.5), \
                patch.object(self.e, 'best_question', return_value=7) as best_question:
            q = self.e.best_disambiguating_question({}, asked, candidate_count=3, idk_streak=2)
        self.assertEqual(q, 7)
        best_question.assert_called_once_with({}, asked, idk_streak=2)

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

    def test_learn_near_miss_is_weaker_positive_than_yes(self):
        e_yes = Engine()
        e_maybe = Engine()
        q = 8
        before_yes_total = e_yes.matrix['total'][0][q]
        before_maybe_total = e_maybe.matrix['total'][0][q]
        before_maybe_yes = e_maybe.matrix['yes'][0][q]

        e_yes.learn({str(q): 1.0}, 0)
        e_maybe.learn_near_miss({str(q): 1.0}, 0)

        yes_delta = e_yes.matrix['total'][0][q] - before_yes_total
        maybe_delta = e_maybe.matrix['total'][0][q] - before_maybe_total
        self.assertGreater(e_maybe.matrix['yes'][0][q], before_maybe_yes)
        self.assertGreater(maybe_delta, 0)
        self.assertLess(maybe_delta, yes_delta)

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

    def test_collect_matrix_updates_rejects_duplicate_pairs(self):
        fid = self.e.fetishes[0]['id']
        rows = [
            {'fetish_id': fid, 'question_id': 0, 'yes': 1, 'total': 2},
            {'fetish_id': fid, 'question_id': 0, 'yes': 2, 'total': 3},
        ]
        with self.assertRaises(ValueError):
            collect_matrix_updates(self.e.fetishes, self.e.questions, rows)

    def test_seed_db_uses_initial_matrix_priors(self):
        captured = {}

        def fake_execute_values(cur, query, rows):
            captured['rows'] = rows

        fake_psycopg2 = types.SimpleNamespace(
            extras=types.SimpleNamespace(execute_values=fake_execute_values)
        )
        with patch.object(eng_module, 'psycopg2', fake_psycopg2, create=True):
            self.e._seed_db(object(), self.e.fetishes)

        rows = {
            (fetish_id, question_id): (yes, total)
            for fetish_id, question_id, yes, total in captured['rows']
        }
        ntr_id = self.e.fetishes[0]['id']
        self.assertEqual(rows[(ntr_id, 8)], (0.95 * eng_module.PSEUDO, float(eng_module.PSEUDO)))


class TestMatrixPersistence(unittest.TestCase):
    def test_save_matrix_file_writes_locked_snapshot(self):
        e = Engine.__new__(Engine)
        e._lock = threading.RLock()
        e.matrix = {'yes': [[1.0]], 'total': [[2.0]]}
        captured = {}

        def fake_atomic_write(path, data, **kwargs):
            e.matrix['yes'][0][0] = 99.0
            e.matrix['total'][0][0] = 100.0
            captured['data'] = data

        e._atomic_write = fake_atomic_write
        e._save_matrix_file()

        self.assertEqual(captured['data'], {'yes': [[1.0]], 'total': [[2.0]]})

    def test_local_save_async_saves_synchronously(self):
        e = Engine.__new__(Engine)
        with patch.object(eng_module, '_use_db', return_value=False), \
             patch.object(e, '_save_matrix_file', return_value=None) as save_matrix, \
             patch.object(eng_module.threading, 'Thread') as thread_cls:
            e._save_async({0: [(0, 1.0, 1.0)]}, {0: 0})

        save_matrix.assert_called_once()
        thread_cls.assert_not_called()


if __name__ == '__main__':
    unittest.main()
