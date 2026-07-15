# ruff: noqa: F403, F405

from tests._app_test_support import *


class TestLearningFeedbackFlow(APITestCase):
    def test_confirm_correct_true_learns(self):
        res = self.client.post('/api/confirm', json={'correct': True, 'fetish_id': 0})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()['status'], 'learned')

    def test_confirm_correct_is_not_applied_twice(self):
        from app import engine as app_engine

        before = app_engine.get_fetish_log().get(0, {}).get('correct', 0)
        first = self.client.post('/api/confirm', json={'correct': True, 'fetish_id': 0})
        second = self.client.post('/api/confirm', json={'correct': True, 'fetish_id': 0})
        after = app_engine.get_fetish_log().get(0, {}).get('correct', 0)
        self.assertEqual(first.status_code, 200)
        self.assertIn(second.status_code, (409, 440))
        self.assertEqual(after, before + 1)

    def test_confirm_correct_with_compound_ids(self):
        res = self.client.post('/api/confirm', json={'correct': True, 'fetish_id': 0, 'compound_ids': [10, 23]})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()['status'], 'learned')

    def test_confirm_wrong_returns_fetish_list(self):
        res = self.client.post('/api/confirm', json={'correct': False, 'fetish_id': 0, 'compound_ids': []})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['status'], 'wrong')
        self.assertIsInstance(data['fetishes'], list)
        self.assertLessEqual(len(data['fetishes']), 20)
        ids = [f['id'] for f in data['fetishes']]
        self.assertNotIn(0, ids)

    def test_confirm_wrong_excludes_compound(self):
        res = self.client.post('/api/confirm', json={'correct': False, 'fetish_id': 0, 'compound_ids': [10]})
        data = res.get_json()
        ids = [f['id'] for f in data['fetishes']]
        self.assertNotIn(0, ids)
        self.assertNotIn(10, ids)

    def test_confirm_wrong_is_not_applied_twice(self):
        from app import engine as app_engine

        before = app_engine.get_fetish_log().get(0, {}).get('wrong', 0)
        first = self.client.post('/api/confirm', json={'correct': False, 'fetish_id': 0})
        second = self.client.post('/api/confirm', json={'correct': False, 'fetish_id': 0})
        after = app_engine.get_fetish_log().get(0, {}).get('wrong', 0)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 409)
        self.assertEqual(after, before + 1)

    def test_teach_valid(self):
        res = self.client.post('/api/teach', json={'fetish_id': 0})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()['status'], 'learned')

    def test_add_fetish_existing_returns_learned(self):
        res = self.client.post('/api/add_fetish', json={'name': 'ヤンデレ'})
        data = res.get_json()
        self.assertEqual(data['status'], 'learned')
        self.assertEqual(data['fetish_name'], 'ヤンデレ')
        self.assertFalse(data['is_new'])

    def test_add_fetish_new_needs_desc_or_confirmed(self):
        res = self.client.post('/api/add_fetish', json={'name': 'テスト性癖XYZ_unique'})
        data = res.get_json()
        self.assertIn(data['status'], ('needs_desc', 'similar', 'learned'))

    def test_add_fetish_confirmed_creates_entry(self):
        from app import engine as app_engine

        before_count = len(app_engine.fetishes)
        name = f'テスト性癖確定_{before_count}'
        res = self.client.post('/api/add_fetish', json={'name': name, 'desc': 'テスト用', 'confirmed': True})
        data = res.get_json()
        self.assertEqual(data['status'], 'learned')
        self.assertTrue(data['is_new'])
        self.assertGreaterEqual(data['fetish_id'], PLAYER_FETISH_BASE_ID)
        # テスト後ロールバック（DB・JSONファイルも含む完全削除）
        app_engine.delete_fetish(data['fetish_id'])

    def test_delete_owned_added_fetish_endpoint(self):
        from app import engine as app_engine

        idx, db_id = app_engine.add_fetish('テスト削除_owned_endpoint', 'テスト用', {})
        try:
            with self.client.session_transaction() as sess:
                sess['owned_added_fetish_ids'] = [db_id]
            res = self.client.delete(f'/api/fetish/{db_id}')
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.get_json()['status'], 'deleted')
            self.assertIsNone(app_engine.index_of(db_id))
            with self.client.session_transaction() as sess:
                self.assertEqual(sess.get('owned_added_fetish_ids'), [])
        finally:
            cleanup_idx = app_engine.index_of(db_id)
            if cleanup_idx is not None:
                app_engine.fetishes.pop(cleanup_idx)
                app_engine.matrix['yes'].pop(cleanup_idx)
                app_engine.matrix['total'].pop(cleanup_idx)
                app_engine._save_fetishes_file()

    def test_finalize_added_existing_fetish(self):
        res = self.client.post('/api/finalize_added', json={'items': [{'id': 0, 'is_new': False}]})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()['status'], 'done')

    def test_finalize_added_empty_items(self):
        res = self.client.post('/api/finalize_added', json={'items': []})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()['status'], 'done')

    def test_confirm_maybe_learns_weak_positive_without_wrong_bucket(self):
        from app import engine as app_engine

        q = 8
        idx = app_engine.index_of(0)
        before_yes = app_engine.matrix['yes'][idx][q]
        before_total = app_engine.matrix['total'][idx][q]
        with self.client.session_transaction() as sess:
            sess['answers'] = {str(q): 1.0}

        res = self.client.post(
            '/api/confirm',
            json={
                'correct': False,
                'fetish_id': 0,
                'maybe_ids': [0],
                'wrong_ids': [],
            },
        )

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()['status'], 'wrong')
        self.assertGreater(app_engine.matrix['yes'][idx][q], before_yes)
        self.assertGreater(app_engine.matrix['total'][idx][q], before_total)
        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get('wrong_db_ids'), [])
            self.assertEqual(sess.get('near_miss_db_ids'), [0])
            self.assertEqual(sess.get('candidate_negative_factor'), 0.15)
        app_engine.matrix['yes'][idx][q] = before_yes
        app_engine.matrix['total'][idx][q] = before_total

    def test_feedback_factor_reduces_broad_correct_and_boosts_near_miss(self):
        from app import engine as app_engine

        broad_id = self._fetish_id_by_name('共依存')
        concrete_id = 0
        broad_idx = app_engine.index_of(broad_id)
        concrete_idx = app_engine.index_of(concrete_id)

        with patch(
            'services.learning.result_exposure.exposure_factors',
            return_value={
                broad_id: 1.0,
                concrete_id: 1.0,
            },
        ):
            self.assertEqual(learning_service.positive_feedback_factor(app_engine, broad_idx), 0.45)
            self.assertEqual(learning_service.positive_feedback_factor(app_engine, concrete_idx), 0.7)
            self.assertEqual(learning_service.negative_feedback_factor(app_engine, broad_idx), 1.7)
            self.assertEqual(learning_service.negative_feedback_factor(app_engine, concrete_idx), 1.3)
        self.assertEqual(learning_service.near_miss_feedback_factor(app_engine, broad_idx), 1.15)
        self.assertEqual(learning_service.near_miss_feedback_factor(app_engine, concrete_idx), 1.6)

    def test_feedback_factor_uses_exposure_to_weaken_positive_and_boost_negative(self):
        from app import engine as app_engine

        broad_id = self._fetish_id_by_name('共依存')
        concrete_id = 0
        broad_idx = app_engine.index_of(broad_id)
        concrete_idx = app_engine.index_of(concrete_id)

        with patch(
            'services.learning.result_exposure.exposure_factors',
            return_value={
                broad_id: 0.12,
                concrete_id: 0.5,
            },
        ):
            self.assertAlmostEqual(learning_service.positive_feedback_factor(app_engine, broad_idx), 0.45 * 0.2)
            self.assertAlmostEqual(learning_service.negative_feedback_factor(app_engine, broad_idx), 1.7 * 2.5)
            self.assertAlmostEqual(learning_service.positive_feedback_factor(app_engine, concrete_idx), 0.7 * 0.5)
            self.assertAlmostEqual(learning_service.negative_feedback_factor(app_engine, concrete_idx), 1.3 * 2.0)

    def test_feedback_factor_provider_loads_exposure_once_per_context(self):
        from app import engine as app_engine

        broad_id = self._fetish_id_by_name('共依存')
        concrete_id = 0
        broad_idx = app_engine.index_of(broad_id)
        concrete_idx = app_engine.index_of(concrete_id)

        with patch(
            'services.learning.result_exposure.exposure_factors',
            return_value={
                broad_id: 0.12,
                concrete_id: 0.5,
            },
        ) as exposure_factors:
            provider = learning_service.make_feedback_factor_provider(app_engine, environ={})
            self.assertAlmostEqual(provider['positive'](app_engine, broad_idx), 0.45 * 0.2)
            self.assertAlmostEqual(provider['negative'](app_engine, broad_idx), 1.7 * 2.5)
            self.assertAlmostEqual(provider['positive'](app_engine, concrete_idx), 0.7 * 0.5)
            self.assertAlmostEqual(provider['negative'](app_engine, concrete_idx), 1.3 * 2.0)

        exposure_factors.assert_called_once()

    def test_confirm_broad_result_uses_reduced_positive_factor(self):
        from app import BOOTSTRAP
        from app import engine as app_engine

        q = 8
        answers = {str(q): 1.0}
        broad_id = self._fetish_id_by_name('共依存')
        broad_idx = app_engine.index_of(broad_id)
        expected_base = learning_service.learn_factor(
            app_engine,
            inference_service.posteriors,
            answers,
            app_engine.config.get('guess_threshold', BOOTSTRAP.guess_threshold),
            total_n=1,
        )

        with self.client.session_transaction() as sess:
            sess['started'] = True
            sess['answers'] = answers
            sess['last_guess_fetish_id'] = broad_id
            sess['last_guess_compound_ids'] = []
            sess.pop('feedback_status', None)

        with (
            patch('services.learning.result_exposure.exposure_factors', return_value={broad_id: 1.0}),
            patch('services.learning.learn_positive') as learn_positive,
        ):
            res = self.client.post(
                '/api/confirm',
                json={
                    'correct': True,
                    'fetish_id': broad_id,
                },
            )

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()['status'], 'learned')
        learn_positive.assert_called_once()
        self.assertEqual(learn_positive.call_args.args[2], broad_idx)
        self.assertAlmostEqual(
            learn_positive.call_args.kwargs['strength_factor'],
            expected_base * learning_service.BROAD_RESULT_POSITIVE_SCALE,
        )

    def test_confirm_wrong_result_uses_negative_factor_once(self):
        from app import engine as app_engine

        q = 8
        answers = {str(q): 1.0}
        broad_id = self._fetish_id_by_name('共依存')
        broad_idx = app_engine.index_of(broad_id)

        with self.client.session_transaction() as sess:
            sess['started'] = True
            sess['answers'] = answers
            sess['last_guess_fetish_id'] = broad_id
            sess['last_guess_compound_ids'] = []
            sess.pop('feedback_status', None)

        with (
            patch('services.learning.result_exposure.exposure_factors', return_value={broad_id: 1.0}),
            patch('services.learning.learn_negative') as learn_negative,
        ):
            res = self.client.post(
                '/api/confirm',
                json={
                    'correct': False,
                    'fetish_id': broad_id,
                    'wrong_ids': [broad_id],
                },
            )

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()['status'], 'wrong')
        learn_negative.assert_called_once()
        self.assertEqual(learn_negative.call_args.args[2], broad_idx)
        self.assertAlmostEqual(
            learn_negative.call_args.kwargs['strength_factor'],
            learning_service.BROAD_RESULT_NEGATIVE_SCALE,
        )
        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get('negative_learned_db_ids'), [broad_id])

    def test_finalize_added_wrong_result_uses_negative_factor(self):
        from app import engine as app_engine

        q = 8
        answers = {str(q): 1.0}
        broad_id = self._fetish_id_by_name('共依存')
        broad_idx = app_engine.index_of(broad_id)
        correct_id = self._fetish_id_by_name('白衣')

        with self.client.session_transaction() as sess:
            sess['started'] = True
            sess['answers'] = answers
            sess['last_guess_fetish_id'] = broad_id
            sess['last_guess_compound_ids'] = [correct_id]
            sess['wrong_db_ids'] = [broad_id]
            sess['candidate_db_ids'] = [correct_id]
            sess['feedback_status'] = 'pending_correction'

        with (
            patch('services.learning.result_exposure.exposure_factors', return_value={broad_id: 1.0}),
            patch('services.learning.learn_positive'),
            patch('services.learning.learn_negative') as learn_negative,
        ):
            res = self.client.post(
                '/api/finalize_added',
                json={
                    'items': [{'id': correct_id, 'is_new': False}],
                },
            )

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()['status'], 'done')
        learn_negative.assert_called_once()
        self.assertEqual(learn_negative.call_args.args[2], broad_idx)
        self.assertAlmostEqual(
            learn_negative.call_args.kwargs['strength_factor'],
            learning_service.BROAD_RESULT_NEGATIVE_SCALE,
        )

    def test_confirm_maybe_uses_near_miss_factor(self):
        from app import BOOTSTRAP
        from app import engine as app_engine

        q = 8
        answers = {str(q): 1.0}
        guessed_id = 0
        maybe_id = self._fetish_id_by_name('白衣')
        maybe_idx = app_engine.index_of(maybe_id)
        expected_base = learning_service.learn_factor(
            app_engine,
            inference_service.posteriors,
            answers,
            app_engine.config.get('guess_threshold', BOOTSTRAP.guess_threshold),
            total_n=1,
        )

        with self.client.session_transaction() as sess:
            sess['started'] = True
            sess['answers'] = answers
            sess['last_guess_fetish_id'] = guessed_id
            sess['last_guess_compound_ids'] = [maybe_id]
            sess.pop('feedback_status', None)

        with patch('services.learning.learn_near_miss') as learn_near_miss:
            res = self.client.post(
                '/api/confirm',
                json={
                    'correct': False,
                    'fetish_id': guessed_id,
                    'compound_ids': [maybe_id],
                    'maybe_ids': [maybe_id],
                    'wrong_ids': [],
                },
            )

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()['status'], 'wrong')
        learn_near_miss.assert_called_once()
        self.assertEqual(learn_near_miss.call_args.args[2], maybe_idx)
        self.assertAlmostEqual(
            learn_near_miss.call_args.kwargs['strength_factor'],
            expected_base * learning_service.NEAR_MISS_SCALE,
        )

    def test_confirm_defer_learning_returns_candidates_without_matrix_or_pending_penalty(self):
        from app import engine as app_engine

        q = 8
        idx = app_engine.index_of(0)
        before_yes = app_engine.matrix['yes'][idx][q]
        before_total = app_engine.matrix['total'][idx][q]
        before_log = dict(app_engine.get_fetish_log().get(0, {}))
        with self.client.session_transaction() as sess:
            sess['answers'] = {str(q): 1.0}

        res = self.client.post(
            '/api/confirm',
            json={
                'correct': False,
                'fetish_id': 0,
                'maybe_ids': [0],
                'wrong_ids': [],
                'defer_learning': True,
            },
        )

        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['status'], 'wrong')
        self.assertTrue(data['fetishes'])
        self.assertEqual(app_engine.matrix['yes'][idx][q], before_yes)
        self.assertEqual(app_engine.matrix['total'][idx][q], before_total)
        self.assertEqual(app_engine.get_fetish_log().get(0, {}), before_log)
        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get('wrong_db_ids'), [])
            self.assertEqual(sess.get('near_miss_db_ids'), [])
            self.assertTrue(sess.get('candidate_db_ids'))

        app_engine.matrix['yes'][idx][q] = before_yes
        app_engine.matrix['total'][idx][q] = before_total

    def test_log_guessed_increments(self):
        from app import engine as app_engine

        log_before = app_engine.get_fetish_log()
        data = self._force_guess()
        if data.get('action') == 'guess':
            fid = data['fetish_id']
            log_after = app_engine.get_fetish_log()
            before = log_before.get(fid, {}).get('guessed', 0)
            after = log_after.get(fid, {}).get('guessed', 0)
            self.assertGreater(after, before)

    def test_log_correct_increments(self):
        from app import engine as app_engine

        data = self._force_guess()
        fid = data['fetish_id']
        log_before = app_engine.get_fetish_log()
        self.client.post(
            '/api/confirm',
            json={
                'correct': True,
                'fetish_id': fid,
                'compound_ids': [c['fetish_id'] for c in data.get('compound', [])],
            },
        )
        log_after = app_engine.get_fetish_log()
        before = log_before.get(fid, {}).get('correct', 0)
        after = log_after.get(fid, {}).get('correct', 0)
        self.assertGreater(after, before)

    def test_fetish_log_uses_configured_temp_path(self):
        from app import engine as app_engine

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'isolated', 'fetish_log.json')
            with patch.dict(os.environ, {'FETISH_LOG_PATH': path}, clear=False):
                app_engine.log_guessed(0)
                self.assertTrue(os.path.exists(path))
                with open(path, encoding='utf-8') as f:
                    data = json.load(f)
                self.assertEqual(data['0']['guessed'], 1)

    def test_finalize_added_cooccurrence_learns_multiple(self):
        """finalize_added で複数性癖を渡すと両方が学習されること。"""
        from app import engine as app_engine

        start = self._start()
        q = start['question_id']
        self.client.post('/api/answer', json={'question_id': q, 'answer': 1.0})
        f0_id = app_engine.fetishes[0]['id']
        f1_id = app_engine.fetishes[1]['id']
        before0 = sum(app_engine.matrix['total'][0])
        before1 = sum(app_engine.matrix['total'][1])
        self._set_active_guess(0, [f1_id])
        res = self.client.post(
            '/api/finalize_added', json={'items': [{'id': f0_id, 'is_new': False}, {'id': f1_id, 'is_new': False}]}
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()['status'], 'done')
        self.assertGreater(sum(app_engine.matrix['total'][0]), before0)
        self.assertGreater(sum(app_engine.matrix['total'][1]), before1)

    def test_confirm_compound_correct_learns(self):
        """複合正解で2性癖が同時に学習されること。"""
        res = self.client.post('/api/confirm', json={'correct': True, 'fetish_id': 0, 'compound_ids': [1]})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()['status'], 'learned')

    def test_cooccurrence_does_not_crash(self):
        from app import engine as app_engine

        answers = {'0': 1.0, '1': -1.0}
        # same index → no-op
        app_engine.learn_cooccurrence(answers, 0, 0)
        # valid pair
        app_engine.learn_cooccurrence(answers, 0, 1)

    def test_promote_fetish(self):
        """プレイヤー追加性癖をシード格上げするとIDが10000未満になること。"""
        from app import engine as app_engine

        before_count = len(app_engine.fetishes)
        name = f'格上げテスト_{before_count}'
        res = self.client.post('/api/add_fetish', json={'name': name, 'desc': 'テスト用', 'confirmed': True})
        old_id = res.get_json()['fetish_id']
        self.assertGreaterEqual(old_id, PLAYER_FETISH_BASE_ID)
        new_id = None
        try:
            new_id = app_engine.promote_fetish(old_id)
            self.assertIsNotNone(new_id)
            self.assertLess(new_id, PLAYER_FETISH_BASE_ID)
            self.assertIsNone(app_engine.index_of(old_id))
            self.assertIsNotNone(app_engine.index_of(new_id))
        finally:
            cleanup_id = new_id if new_id is not None else old_id
            idx = app_engine.index_of(cleanup_id)
            if idx is not None:
                app_engine.fetishes.pop(idx)
                app_engine.matrix['yes'].pop(idx)
                app_engine.matrix['total'].pop(idx)
                if not _use_db():
                    app_engine._save_fetishes_file()

    def test_unverified_resumed_guess_skips_learning(self):
        from app import engine as app_engine

        q = 8
        idx = app_engine.index_of(0)
        before_yes = app_engine.matrix['yes'][idx][q]
        before_total = app_engine.matrix['total'][idx][q]
        before_log = dict(app_engine.get_fetish_log().get(0, {}))
        with self.client.session_transaction() as sess:
            sess['started'] = True
            sess['answers'] = {str(q): 1.0}
            sess['last_guess_fetish_id'] = 0
            sess['last_guess_compound_ids'] = []
            sess['client_resumed'] = True
            sess['resume_learning_verified'] = False
        res = self.client.post('/api/confirm', json={'correct': True, 'fetish_id': 0})
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['learning_disabled'])
        self.assertEqual(app_engine.matrix['yes'][idx][q], before_yes)
        self.assertEqual(app_engine.matrix['total'][idx][q], before_total)
        self.assertEqual(app_engine.get_fetish_log().get(0, {}), before_log)
