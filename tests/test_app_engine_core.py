# ruff: noqa: F403, F405

from tests._app_test_support import *


class TestEngine(FileSnapshotMixin, unittest.TestCase):
    """engine.py のコア推論ロジックを直接テスト。"""

    def setUp(self):
        from app import engine as app_engine

        self.eng = app_engine
        self._patches = [
            patch.object(self.eng, '_save_async', return_value=None),
            patch.object(self.eng, '_save_matrix_file', return_value=None),
            patch.object(self.eng, '_save_fetishes_file', return_value=None),
            patch.object(self.eng, '_save_to_db', return_value=None),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in reversed(self._patches):
            p.stop()

    def test_posteriors_sum_to_one(self):
        probs = self.eng.posteriors({})
        self.assertAlmostEqual(sum(probs), 1.0, places=5)

    def test_posteriors_yes_answer_increases_probability(self):
        nq = len(self.eng.questions)
        # Find a question with some disc (not totally flat)
        stats = self.eng.get_question_stats()
        high = max(stats, key=lambda s: s['disc'])
        q_id = high['id']
        base = self.eng.posteriors({})
        after = self.eng.posteriors({str(q_id): 1.0})
        # Best-prob fetish after 'yes' answer should be >= base best-prob
        self.assertGreaterEqual(max(after), max(base))

    def test_posteriors_is_list_of_floats(self):
        probs = self.eng.posteriors({})
        self.assertEqual(len(probs), len(self.eng.fetishes))
        self.assertTrue(all(isinstance(p, float) for p in probs))
        self.assertTrue(all(0.0 <= p <= 1.0 for p in probs))

    def test_learn_shifts_matrix(self):
        nf = len(self.eng.fetishes)
        nq = len(self.eng.questions)
        idx = 0
        q = 0
        before_yes = self.eng.matrix['yes'][idx][q]
        before_total = self.eng.matrix['total'][idx][q]
        self.eng.learn({str(q): 1.0}, idx, strength_factor=1.0)
        self.assertGreater(self.eng.matrix['yes'][idx][q], before_yes)
        self.assertGreater(self.eng.matrix['total'][idx][q], before_total)
        # Restore to avoid affecting other tests
        self.eng.matrix['yes'][idx][q] = before_yes
        self.eng.matrix['total'][idx][q] = before_total

    def test_best_question_not_in_asked(self):
        asked = set(range(10))
        q = self.eng.best_question({}, asked)
        self.assertNotIn(q, asked)

    def test_best_question_returns_none_when_all_asked(self):
        all_q = set(range(len(self.eng.questions)))
        q = self.eng.best_question({}, all_q)
        self.assertIsNone(q)

    def test_top_guess_returns_valid_index(self):
        idx, prob = self.eng.top_guess({}, n=1)
        self.assertGreaterEqual(idx, 0)
        self.assertLess(idx, len(self.eng.fetishes))
        self.assertGreater(prob, 0.0)

    def test_get_question_stats_has_ask_count(self):
        stats = self.eng.get_question_stats()
        self.assertTrue(all('ask_count' in s for s in stats))
        self.assertTrue(all(s['ask_count'] >= 0 for s in stats))

    def test_early_stop_condition(self):
        """高確率かつ大差なら early_stop が効いてアンサーが guess を返す。"""
        from app import app as flask_app

        client = flask_app.test_client()
        client.post('/api/start')
        orig_thr = self.eng.config.get('focus_threshold', 0.40)
        # Force posteriors to be dominated by a single fetish via answers
        # by answering all questions yes (will hit MAX_QUESTIONS or early_stop)
        res = client.post('/api/start')
        q = res.get_json()['question_id']
        action = 'question'
        for _ in range(30):
            r = client.post('/api/answer', json={'question_id': q, 'answer': 1.0})
            d = r.get_json()
            action = d.get('action')
            if action == 'guess':
                break
            q = d.get('question_id', q)
        self.assertEqual(action, 'guess')

    def test_learn_negative_weakens_matrix(self):
        idx = 0
        q = 0
        before_total = self.eng.matrix['total'][idx][q]
        self.eng.learn_negative({str(q): 1.0}, idx)
        after_total = self.eng.matrix['total'][idx][q]
        self.assertGreater(after_total, before_total)
        # yes_count increases less than total (net negative signal)
        before_yes = self.eng.matrix['yes'][idx][q]
        self.eng.matrix['total'][idx][q] = before_total
        self.eng.matrix['yes'][idx][q] = before_yes

    def test_learn_cooccurrence_strengthens_both(self):
        idx_a = 0
        idx_b = 1
        # q=9 は NTR・百合ともP(yes)>0.5 なので ans=1.0 で確実に eff が発生する
        q = 9
        before_tot_a = self.eng.matrix['total'][idx_a][q]
        before_tot_b = self.eng.matrix['total'][idx_b][q]
        self.eng.learn_cooccurrence({str(q): 1.0}, idx_a, idx_b, factor=1.0)
        # At least one of the two totals should have increased
        increased = (
            self.eng.matrix['total'][idx_a][q] > before_tot_a or self.eng.matrix['total'][idx_b][q] > before_tot_b
        )
        self.assertTrue(increased)
        # Restore
        self.eng.matrix['total'][idx_a][q] = before_tot_a
        self.eng.matrix['total'][idx_b][q] = before_tot_b

    def test_add_fetish_appends_to_list(self):
        n_before = len(self.eng.fetishes)
        try:
            idx, db_id = self.eng.add_fetish('テスト追加_unit_xyz', 'テスト', {})
            self.assertEqual(len(self.eng.fetishes), n_before + 1)
            self.assertGreaterEqual(db_id, 10000)
            self.assertEqual(self.eng.fetishes[idx]['name'], 'テスト追加_unit_xyz')
        finally:
            new_idx = self.eng.index_of(db_id)
            if new_idx is not None:
                self.eng.fetishes.pop(new_idx)
                self.eng.matrix['yes'].pop(new_idx)
                self.eng.matrix['total'].pop(new_idx)
                self.eng._save_fetishes_file()

    def test_boost_learn_new_increases_weight(self):
        try:
            idx, db_id = self.eng.add_fetish('テストブースト_unit_xyz', 'テスト', {'0': 1.0})
            before_total = sum(self.eng.matrix['total'][idx])
            self.eng.boost_learn_new(idx, {'0': 1.0})
            after_total = sum(self.eng.matrix['total'][idx])
            self.assertGreater(after_total, before_total)
        finally:
            new_idx = self.eng.index_of(db_id)
            if new_idx is not None:
                self.eng.fetishes.pop(new_idx)
                self.eng.matrix['yes'].pop(new_idx)
                self.eng.matrix['total'].pop(new_idx)
                self.eng._save_fetishes_file()

    def test_idk_streak_triggers_guess(self):
        from app import app as flask_app

        client = flask_app.test_client()
        res = client.post('/api/start')
        q = res.get_json()['question_id']
        for _ in range(4):
            r = client.post('/api/answer', json={'question_id': q, 'answer': 0})
            d = r.get_json()
            if d.get('action') == 'guess':
                break
            q = d.get('question_id', q)
        self.assertEqual(d.get('action'), 'guess')
