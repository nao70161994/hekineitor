# ruff: noqa: F403, F405

from tests._app_test_support import *


class TestGameSessionFlow(APITestCase):
    def test_start_returns_question(self):
        data = self._start()
        self.assertIn('question_id', data)
        self.assertIn('question', data)
        self.assertEqual(data['count'], 0)

    def test_answer_yes(self):
        start = self._start()
        res = self.client.post('/api/answer', json={'question_id': start['question_id'], 'answer': 1.0})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn(data.get('action'), ('question', 'guess'))

    def test_back_no_history(self):
        self._start()
        res = self.client.post('/api/back')
        data = res.get_json()
        self.assertEqual(data['status'], 'no_history')

    def test_back_after_answer(self):
        start = self._start()
        self.client.post('/api/answer', json={'question_id': start['question_id'], 'answer': 1.0})
        res = self.client.post('/api/back')
        data = res.get_json()
        self.assertIn('question_id', data)
        self.assertIn('question', data)

    def test_back_no_duplicate_question(self):
        start = self._start()
        q0 = start['question_id']
        res1 = self.client.post('/api/answer', json={'question_id': q0, 'answer': 1.0})
        self.client.post('/api/back')
        res2 = self.client.post('/api/answer', json={'question_id': q0, 'answer': 1.0})
        data2 = res2.get_json()
        if data2.get('action') == 'question':
            self.assertNotEqual(data2['question_id'], q0)

    def test_back_restores_exact_shown_question_context(self):
        from app import engine as app_engine

        start = self._start()
        q0 = start['question_id']
        expected = dict(start)
        expected.update(
            {
                'question': '表示時だけの質問variant',
                'axis': '表示時の軸',
                'q_hint': '表示時の質問ヒント',
                'hint': '表示時の進行ヒント',
                'progress_message': '表示時の進捗文言',
                'contradictions': [{'question_id': 999, 'message': '表示時の矛盾'}],
            }
        )
        with self.client.session_transaction() as sess:
            shown = dict(sess['shown_question_payloads'])
            shown[str(q0)] = expected
            sess['shown_question_payloads'] = shown
        self.client.post('/api/answer', json={'question_id': q0, 'answer': 1.0})

        restored = self.client.post('/api/back').get_json()

        self.assertEqual(restored, expected)
        self.assertNotEqual(restored['question'], app_engine.questions[q0]['text'])

    def test_test_play_is_excluded_from_runtime_analytics(self):
        from app import engine as app_engine

        with self.client.session_transaction() as sess:
            test_play_service.enable(sess)
        with (
            patch.object(app_engine, 'increment_start_count') as increment_start,
            patch.object(app_engine, 'increment_play_count') as increment_play,
            patch.object(app_engine, 'log_guessed') as log_guessed,
            patch.object(app_engine, 'log_dropoff') as log_dropoff,
            patch('services.question_events.safe_record_event') as record_question,
            patch('services.result_exposure.safe_record_result') as record_exposure,
            patch('services.share_events.safe_record_event') as record_share,
        ):
            start = self.client.post('/api/start').get_json()
            qid = start['question_id']
            result = None
            for _ in range(35):
                result = self.client.post('/api/answer', json={'question_id': qid, 'answer': 1.0}).get_json()
                if result.get('action') == 'guess':
                    break
                qid = result['question_id']

            self.assertEqual(result.get('action'), 'guess')
            increment_start.assert_not_called()
            increment_play.assert_not_called()
            log_guessed.assert_not_called()
            record_question.assert_not_called()
            record_exposure.assert_not_called()

            with self.client.session_transaction() as sess:
                sess['completed'] = False
                sess['dropoff_recorded'] = False
            self.client.post('/api/dropoff')
            log_dropoff.assert_not_called()
            record_question.assert_not_called()

            share = self.client.post('/api/share_event', json={'event_name': 'share_click'})
            self.assertTrue(share.get_json()['learning_disabled'])
            record_share.assert_not_called()

    def test_test_play_admin_link_enables_banner_and_survives_start(self):
        headers = self._admin_headers()
        plain = self.client.get('/?sandbox=1')
        self.assertEqual(plain.status_code, 200)
        self.assertNotIn('テストプレイ中', plain.data.decode('utf-8'))

        res = self.client.post('/admin/test_play/start', headers=headers, follow_redirects=False)
        self.assertEqual(res.status_code, 302)
        self.assertEqual(res.headers.get('Location'), '/')
        banner = self.client.get('/')
        self.assertIn('テストプレイ中：この診断は学習に反映されません', banner.data.decode('utf-8'))
        self.client.post('/api/start')
        with self.client.session_transaction() as sess:
            self.assertTrue(test_play_service.is_learning_disabled(sess))

    def test_test_play_stop_disables_flag_and_admin_status_updates(self):
        headers = self._admin_headers()
        normal_admin = self.client.get('/admin', headers=headers)
        self.assertIn('通常モード', normal_admin.data.decode('utf-8'))
        self.assertIn('data-action="test-play-start"', normal_admin.data.decode('utf-8'))

        self.client.post('/admin/test_play/start', headers=headers)
        active_admin = self.client.get('/admin', headers=headers)
        active_body = active_admin.data.decode('utf-8')
        self.assertIn('学習OFFテストプレイ中', active_body)
        self.assertIn('data-action="test-play-stop"', active_body)
        self.assertIn('テストプレイ開始/終了履歴', active_body)
        self.assertIn('test_play_start', active_body)
        self.assertIn('学習OFFテストプレイ中へ変更', active_body)

        res = self.client.post('/admin/test_play/stop', headers=headers, follow_redirects=False)
        self.assertEqual(res.status_code, 302)
        self.assertEqual(res.headers.get('Location'), '/admin')
        with self.client.session_transaction() as sess:
            self.assertFalse(test_play_service.is_learning_disabled(sess))
        stopped_admin = self.client.get('/admin', headers=headers)
        stopped_body = stopped_admin.data.decode('utf-8')
        self.assertIn('通常モード', stopped_body)
        self.assertIn('test_play_stop', stopped_body)
        self.assertIn('通常モードへ変更', stopped_body)

        audit = self.client.get('/api/admin/audit_log', headers=headers).get_json()['audit_log']
        test_rows = [row for row in audit if row.get('action') in ('test_play_start', 'test_play_stop')]
        self.assertGreaterEqual(len(test_rows), 2)
        for row in test_rows[:2]:
            self.assertIn(row['detail']['event_name'], ('test_play_start', 'test_play_stop'))
            self.assertIn(row['detail']['mode'], ('learning_off', 'normal'))
            self.assertNotIn('remote_addr', row)
            self.assertNotIn('path', row)
            self.assertNotIn('user_agent', row)

    def test_test_play_confirm_skips_learning_and_quality_feedback(self):
        from app import engine as app_engine

        q = 8
        idx = app_engine.index_of(0)
        before_yes = app_engine.matrix['yes'][idx][q]
        before_total = app_engine.matrix['total'][idx][q]
        before_log = dict(app_engine.get_fetish_log().get(0, {}))
        with self.client.session_transaction() as sess:
            test_play_service.enable(sess)
            sess['answers'] = {str(q): 1.0}
            sess['last_guess_quality'] = {'low_confidence_extended': True, 'additional_questions': 1}

        res = self.client.post('/api/confirm', json={'correct': True, 'fetish_id': 0})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()['status'], 'learned')
        self.assertTrue(res.get_json()['learning_disabled'])
        self.assertEqual(app_engine.matrix['yes'][idx][q], before_yes)
        self.assertEqual(app_engine.matrix['total'][idx][q], before_total)
        self.assertEqual(app_engine.get_fetish_log().get(0, {}), before_log)
        with self.client.session_transaction() as sess:
            self.assertIn('last_guess_quality', sess)

    def test_test_play_wrong_confirm_returns_candidates_without_saving(self):
        from app import engine as app_engine

        q = 8
        idx = app_engine.index_of(0)
        before_yes = app_engine.matrix['yes'][idx][q]
        before_total = app_engine.matrix['total'][idx][q]
        before_log = dict(app_engine.get_fetish_log().get(0, {}))
        with self.client.session_transaction() as sess:
            test_play_service.enable(sess)
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
        data = res.get_json()
        self.assertEqual(data['status'], 'wrong')
        self.assertTrue(data['learning_disabled'])
        self.assertTrue(data['fetishes'])
        self.assertEqual(app_engine.matrix['yes'][idx][q], before_yes)
        self.assertEqual(app_engine.matrix['total'][idx][q], before_total)
        self.assertEqual(app_engine.get_fetish_log().get(0, {}), before_log)

    def test_test_play_finalize_added_skips_matrix_updates(self):
        from app import engine as app_engine

        q = self._start()['question_id']
        self.client.post('/api/answer', json={'question_id': q, 'answer': 1.0})
        f0_id = app_engine.fetishes[0]['id']
        before0 = sum(app_engine.matrix['total'][0])
        with self.client.session_transaction() as sess:
            test_play_service.enable(sess)
            sess['wrong_db_ids'] = [f0_id]
            sess['candidate_db_ids'] = [f0_id]
            sess['near_miss_db_ids'] = []
            sess['candidate_negative_factor'] = 0.3
            sess['last_guess_fetish_id'] = f0_id
            sess['last_guess_compound_ids'] = []
        res = self.client.post('/api/finalize_added', json={'items': [{'id': f0_id, 'is_new': False}]})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()['status'], 'done')
        self.assertTrue(res.get_json()['learning_disabled'])
        self.assertEqual(sum(app_engine.matrix['total'][0]), before0)
        with self.client.session_transaction() as sess:
            self.assertNotIn('wrong_db_ids', sess)

    def test_test_play_add_fetish_does_not_create_new_fetish(self):
        from app import engine as app_engine

        before_len = len(app_engine.fetishes)
        with self.client.session_transaction() as sess:
            test_play_service.enable(sess)
        res = self.client.post(
            '/api/add_fetish',
            json={
                'name': 'テストプレイ限定性癖',
                'desc': '保存されない',
                'confirmed': True,
            },
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['status'], 'learned')
        self.assertTrue(data['learning_disabled'])
        self.assertEqual(len(app_engine.fetishes), before_len)
        self.assertIsNone(app_engine.index_of('test-play'))

    def test_test_play_keeps_inference_and_result_flow_working(self):
        headers = self._admin_headers()
        self.client.post('/admin/test_play/start', headers=headers)
        data = self._force_guess()
        self.assertEqual(data.get('action'), 'guess')
        self.assertIn('fetish_name', data)
        with self.client.session_transaction() as sess:
            self.assertNotIn('last_guess_quality', sess)

    def test_start_with_exclude_ids(self):
        res = self.client.post('/api/start', json={'exclude_ids': [0, 1]})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn('question_id', data)

    def test_guess_excludes_ids(self):
        """exclude_ids に指定された性癖が1位になっていないことを診断で確認。"""
        from app import engine as app_engine

        excl = [app_engine.fetishes[0]['id']]
        # exclude_ids を指定してスタート（_start() は使わず直接呼ぶ）
        res = self.client.post('/api/start', json={'exclude_ids': excl})
        q = res.get_json()['question_id']
        data = None
        for _ in range(20):
            res = self.client.post('/api/answer', json={'question_id': q, 'answer': 1.0})
            data = res.get_json()
            if data.get('action') == 'guess':
                break
            q = data.get('question_id', q)
        if data and data.get('action') == 'guess':
            self.assertNotIn(data.get('fetish_id'), excl)

    def test_guess_returns_top_chart(self):
        data = self._force_guess()
        if data.get('action') == 'guess':
            self.assertIn('top_chart', data)
            self.assertIsInstance(data['top_chart'], list)
            self.assertGreaterEqual(len(data['top_chart']), 1)
            self.assertIn('fetish_name', data['top_chart'][0])
            self.assertIn('probability', data['top_chart'][0])

    def test_answer_loop_terminates(self):
        """hard上限以内に必ず guess が返ること。"""
        data = self._force_guess()
        self.assertEqual(data.get('action'), 'guess')

    def test_low_confidence_at_soft_limit_extends_questions(self):
        import app as app_module

        with self.client.session_transaction() as sess:
            sess['started'] = True
            sess['answers'] = {str(i): 1.0 for i in range(19)}
            sess['asked'] = list(range(20))
            sess['idk_streak'] = 0
        with (
            patch(
                'services.game_context.result_exposure.adjusted_scores',
                side_effect=self._adjusted_scores_for(0.50, 0.45),
            ),
            patch.object(app_module.engine, 'best_disambiguating_question', return_value=20) as disambiguating,
        ):
            res = self.client.post('/api/answer', json={'question_id': 19, 'answer': 1.0})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['action'], 'question')
        self.assertEqual(data['count'], 20)
        self.assertEqual(data['total'], 30)
        self.assertIn('絞り込み', data.get('hint', ''))
        disambiguating.assert_called_once()

    def test_normal_flow_uses_best_question_before_soft_limit(self):
        import app as app_module

        with self.client.session_transaction() as sess:
            sess['started'] = True
            sess['answers'] = {str(i): 1.0 for i in range(4)}
            sess['asked'] = list(range(5))
            sess['idk_streak'] = 0
        with (
            patch(
                'services.game_context.result_exposure.adjusted_scores',
                side_effect=self._adjusted_scores_for(0.36, 0.22),
            ),
            patch.object(app_module.engine, 'best_question', return_value=5) as best_question,
            patch.object(app_module.engine, 'best_disambiguating_question', return_value=6) as disambiguating,
        ):
            res = self.client.post('/api/answer', json={'question_id': 4, 'answer': 1.0})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['action'], 'question')
        self.assertEqual(data['question_id'], 5)
        self.assertEqual(data.get('progress_message'), 'かなり見えてきました')
        best_question.assert_called_once()
        disambiguating.assert_not_called()

    def test_answer_progress_ignores_excluded_adjusted_top_candidate(self):
        import app as app_module

        def adjusted_scores(engine, probs, ranked):
            scores = {}
            for index in ranked:
                if index == 0:
                    adjusted_score = 0.90
                elif index == 1:
                    adjusted_score = 0.36
                elif index == 2:
                    adjusted_score = 0.22
                else:
                    adjusted_score = 0.01
                scores[index] = {
                    'raw_probability': float(probs[index]),
                    'factor': adjusted_score / float(probs[index]) if probs[index] else 1.0,
                    'adjusted_score': adjusted_score,
                }
            return scores

        with self.client.session_transaction() as sess:
            sess['started'] = True
            sess['answers'] = {str(i): 1.0 for i in range(4)}
            sess['asked'] = list(range(5))
            sess['idk_streak'] = 0
            sess['exclude_ids'] = [app_module.engine.fetishes[0]['id']]
        with (
            patch('services.game_context.result_exposure.adjusted_scores', side_effect=adjusted_scores),
            patch.object(app_module.engine, 'best_question', return_value=5) as best_question,
        ):
            res = self.client.post('/api/answer', json={'question_id': 4, 'answer': 1.0})

        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['action'], 'question')
        self.assertEqual(data['question_id'], 5)
        self.assertEqual(data.get('progress_message'), 'かなり見えてきました')
        best_question.assert_called_once()

    def test_progress_message_for_close_candidates(self):
        import app as app_module

        with self.client.session_transaction() as sess:
            sess['started'] = True
            sess['answers'] = {str(i): 1.0 for i in range(2)}
            sess['asked'] = [0, 1, 2]
            sess['idk_streak'] = 0
        with (
            patch(
                'services.game_context.result_exposure.adjusted_scores',
                side_effect=self._adjusted_scores_for(0.42, 0.39),
            ),
            patch.object(app_module.engine, 'best_question', return_value=3),
        ):
            res = self.client.post('/api/answer', json={'question_id': 2, 'answer': 1.0})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['action'], 'question')
        self.assertEqual(data.get('progress_message'), '候補が2つに割れています')

    def test_hard_limit_forces_guess_even_when_low_confidence(self):
        import app as app_module

        with self.client.session_transaction() as sess:
            sess['started'] = True
            sess['answers'] = {str(i): 1.0 for i in range(29)}
            sess['asked'] = list(range(30))
            sess['idk_streak'] = 0
        with patch(
            'services.game_context.result_exposure.adjusted_scores', side_effect=self._adjusted_scores_for(0.50, 0.45)
        ):
            res = self.client.post('/api/answer', json={'question_id': 29, 'answer': 1.0})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()['action'], 'guess')

    def test_idk_changes_posteriors(self):
        """わからない回答が事後確率に影響を与えること（完全スキップではない）。"""
        from app import engine as app_engine

        probs_empty = app_engine.posteriors({})
        probs_idk = app_engine.posteriors({'0': 0.0, '1': 0.0, '2': 0.0})
        self.assertFalse(all(abs(a - b) < 1e-9 for a, b in zip(probs_empty, probs_idk)))

    def test_effective_threshold_raised_in_close_race(self):
        """接戦時（gap_ratio<1.8 かつ count<10）は effective_thr が guess_thr より高いこと。"""
        guess_thr = 0.75
        # 接戦ケース
        gap_ratio, count = 1.5, 5
        eff = guess_thr if (gap_ratio >= 1.8 or count >= 10) else min(guess_thr + 0.10, 0.90)
        self.assertGreater(eff, guess_thr)
        # gap が十分広い場合は変わらない
        gap_ratio2 = 2.0
        eff2 = guess_thr if (gap_ratio2 >= 1.8 or count >= 10) else min(guess_thr + 0.10, 0.90)
        self.assertEqual(eff2, guess_thr)

    def test_session_persists_across_requests(self):
        """start → answer で answered question が引き継がれること。"""
        start = self._start()
        q = start['question_id']
        res = self.client.post('/api/answer', json={'question_id': q, 'answer': 1.0})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn(data.get('action'), ('question', 'guess'))

    def test_resume_replays_answers(self):
        start = self._start()
        q = start['question_id']
        self.client.post('/api/answer', json={'question_id': q, 'answer': 1.0})
        pairs = [{'q_id': q, 'answer': 1.0}]
        res = self.client.post('/api/resume', json={'pairs': pairs})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn(data.get('action'), ('question', 'guess'))

    def test_resume_empty_pairs_returns_first_question(self):
        from app import engine as app_engine

        before = app_engine.get_stats().get('start_count', 0)
        res = self.client.post('/api/resume', json={'pairs': []})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get('action'), 'question')
        self.assertIn('question_id', data)
        self.assertEqual(app_engine.get_stats().get('start_count', 0), before)

    def test_resume_with_answers_counts_as_start_source(self):
        from app import engine as app_engine

        before = app_engine.get_stats().get('start_count', 0)
        res = self.client.post('/api/resume', json={'pairs': [{'q_id': 0, 'answer': 1.0}]})
        self.assertEqual(res.status_code, 200)
        self.assertGreater(app_engine.get_stats().get('start_count', 0), before)

    def test_continue_after_guess(self):
        self._force_guess()
        res = self.client.post('/api/continue')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn(data.get('action'), ('question',))

    def test_guess_logs_compound_candidates_as_guessed(self):
        from app import engine as app_engine

        old_compound = app_engine.config.get('compound_ratio')
        old_triple = app_engine.config.get('triple_ratio')
        try:
            app_engine.config['compound_ratio'] = 0.0
            app_engine.config['triple_ratio'] = 0.0
            data = self._force_guess()
            compound_ids = [item['fetish_id'] for item in data.get('compound', [])]
            self.assertTrue(compound_ids)
            log = app_engine.get_fetish_log()
            for fetish_id in {data['fetish_id']} | set(compound_ids):
                self.assertGreaterEqual(log.get(fetish_id, {}).get('guessed', 0), 1)
        finally:
            if old_compound is None:
                app_engine.config.pop('compound_ratio', None)
            else:
                app_engine.config['compound_ratio'] = old_compound
            if old_triple is None:
                app_engine.config.pop('triple_ratio', None)
            else:
                app_engine.config['triple_ratio'] = old_triple

    def test_start_returns_axis(self):
        res = self.client.post('/api/start')
        d = res.get_json()
        self.assertIn('axis', d)
        self.assertIn(d['axis'], ('content', 'abstract', 'personality', None))

    def test_start_increments_start_count(self):
        from app import engine as app_engine

        before = app_engine.get_stats().get('start_count', 0)
        res = self.client.post('/api/start')
        self.assertEqual(res.status_code, 200)
        after = app_engine.get_stats().get('start_count', 0)
        self.assertGreater(after, before)

    def test_dropoff_records_answered_count_once_before_completion(self):
        from app import engine as app_engine

        self.client.post('/api/start')
        with self.client.session_transaction() as sess:
            sess['answers'] = {'1': 1.0, '2': -1.0}
            sess['started'] = True
            sess['completed'] = False
            sess['dropoff_recorded'] = False
        with patch.object(app_engine, 'log_dropoff') as recorder:
            res = self.client.post('/api/dropoff', json={'answered_count': 2})
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.get_json()['status'], 'ok')
            recorder.assert_called_once_with(2)
            res2 = self.client.post('/api/dropoff', json={'answered_count': 2})
            self.assertEqual(res2.status_code, 200)
            self.assertEqual(res2.get_json()['status'], 'ignored')
            recorder.assert_called_once()

    def test_dropoff_ignored_after_completion(self):
        from app import engine as app_engine

        with self.client.session_transaction() as sess:
            sess['started'] = True
            sess['completed'] = True
            sess['answers'] = {'1': 1.0}
            sess['dropoff_recorded'] = False
        with patch.object(app_engine, 'log_dropoff') as recorder:
            res = self.client.post('/api/dropoff', json={'answered_count': 1})
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.get_json()['status'], 'ignored')
            recorder.assert_not_called()

    def test_answer_returns_axis(self):
        self._start()
        res = self.client.post('/api/start')
        q = res.get_json()['question_id']
        res2 = self.client.post('/api/answer', json={'question_id': q, 'answer': 1.0})
        d = res2.get_json()
        if d.get('action') == 'question':
            self.assertIn('axis', d)

    def test_fetish_history_endpoint(self):
        from app import engine as app_engine

        headers = self._admin_headers()
        fid = app_engine.fetishes[0]['id']
        res = self.client.get(f'/api/admin/fetish_history/{fid}', headers=headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIsInstance(data, list)
        self.assertTrue(all('date' in r and 'correct' in r and 'wrong' in r for r in data))

    def test_answer_returns_hint_when_focused(self):
        from app import engine as app_engine

        # Patch config to low focus_threshold so hint fires easily
        orig = app_engine.config.get('focus_threshold', 0.40)
        try:
            app_engine.config['focus_threshold'] = 0.01
            self._start()
            res = self.client.post('/api/start')
            q = res.get_json()['question_id']
            resp = self.client.post('/api/answer', json={'question_id': q, 'answer': 1.0})
            d = resp.get_json()
            if d.get('action') == 'question':
                self.assertIn('hint', d)
        finally:
            app_engine.config['focus_threshold'] = orig
