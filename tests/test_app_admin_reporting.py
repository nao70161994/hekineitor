# ruff: noqa: F403, F405

from tests._app_test_support import *


class TestAdminReporting(APITestCase):
    def test_admin_promote_fetish_reassigns_result_exposure_events(self):
        import app as app_module

        headers = self._admin_headers()
        with (
            patch.object(app_module.engine, 'promote_fetish', return_value=3),
            patch(
                'routes.admin.result_exposure_service.safe_reassign_fetish_id',
                return_value={
                    'status': 'ok',
                    'storage': 'postgres',
                    'updated_count': 2,
                },
            ) as reassign,
        ):
            res = self.client.post('/api/admin/promote_fetish/10000', headers=headers)

        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['status'], 'promoted')
        self.assertEqual(data['result_exposure_reassign']['updated_count'], 2)
        reassign.assert_called_once()
        args, kwargs = reassign.call_args
        self.assertEqual(args[:2], (10000, 3))
        self.assertIn('fetish_name', kwargs)

    def test_export_log_returns_csv(self):
        headers = self._admin_headers()
        res = self.client.get('/api/admin/export_log', headers=headers)
        self.assertEqual(res.status_code, 200)
        self.assertIn('text/csv', res.content_type)
        body = res.data.decode('utf-8')
        self.assertTrue(
            body.startswith(
                'id,name,guessed,correct,wrong,feedback_total,feedback_accuracy,unfeedback,guess_confirm_rate'
            )
        )

    def test_export_log_escapes_formula_names(self):
        headers = self._admin_headers()
        from app import engine as app_engine

        fid = app_engine.fetishes[0]['id']
        original_name = app_engine.fetishes[0]['name']
        try:
            app_engine.fetishes[0]['name'] = '=cmd'
            with patch.object(
                app_engine, 'get_fetish_log', return_value={fid: {'guessed': 1, 'correct': 1, 'wrong': 0}}
            ):
                res = self.client.get('/api/admin/export_log', headers=headers)
            self.assertEqual(res.status_code, 200)
            self.assertIn("'=cmd", res.data.decode('utf-8'))
        finally:
            app_engine.fetishes[0]['name'] = original_name

    def test_recent_ranking_bounds_query_params(self):
        headers = self._admin_headers()
        res = self.client.get('/api/admin/recent_fetish_ranking?days=-1&top_n=999', headers=headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['days'], 1)
        self.assertIn(data['source'], ('recent', 'all_time_fallback'))

    def test_result_exposures_backfill_requires_confirm_and_inserts_synthetic_events(self):
        headers = self._admin_headers()
        from app import engine as app_engine

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'result_exposures.jsonl')
            with (
                patch.dict(os.environ, {'RESULT_EXPOSURE_LOG_PATH': path}, clear=False),
                patch.object(app_engine, 'get_fetish_log', return_value={0: {'guessed': 8}, 1: {'guessed': 2}}),
            ):
                dry = self.client.get('/api/admin/result_exposures/backfill?max_events=5', headers=headers)
                self.assertEqual(dry.status_code, 200)
                self.assertEqual(dry.get_json()['mode'], 'dry_run')
                missing = self.client.post(
                    '/api/admin/result_exposures/backfill', headers=headers, json={'max_events': 5}
                )
                self.assertEqual(missing.status_code, 400)
                self.assertEqual(missing.get_json()['required_confirm_text'], 'BACKFILL_RESULT_EXPOSURES')
                applied = self.client.post(
                    '/api/admin/result_exposures/backfill',
                    headers=headers,
                    json={
                        'max_events': 5,
                        'confirm_text': 'BACKFILL_RESULT_EXPOSURES',
                    },
                )
                self.assertEqual(applied.status_code, 200)
                payload = applied.get_json()
                self.assertEqual(payload['mode'], 'applied')
                self.assertEqual(payload['inserted_count'], 5)
                ranked = self.client.get(
                    '/api/admin/result_exposures?include_backfill=1&top_n=5', headers=headers
                ).get_json()

        self.assertGreaterEqual(ranked['total'], 5)
        self.assertTrue(ranked['include_backfill'])

    def test_result_exposures_endpoint_reports_displayed_result_ranking(self):
        from app import engine as app_engine

        headers = self._admin_headers()
        primary = app_engine.fetishes[0]
        secondary = app_engine.fetishes[1]
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'result_exposures.jsonl')
            with patch.dict(os.environ, {'RESULT_EXPOSURE_LOG_PATH': path}, clear=False):
                result_exposure_service.record_result(primary['id'], '古い名前', 91, path=path)
                result_exposure_service.record_result(primary['id'], 'さらに古い名前', 89, path=path)
                result_exposure_service.record_result(secondary['id'], secondary['name'], 75, path=path)
                res = self.client.get('/api/admin/result_exposures?top_n=2', headers=headers)

        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['source'], 'result_exposures')
        self.assertEqual(data['total'], 3)
        self.assertEqual(data['ranking'][0]['fetish_id'], primary['id'])
        self.assertEqual(data['ranking'][0]['fetish_name'], primary['name'])
        self.assertEqual(data['ranking'][0]['count'], 2)

    def test_result_exposures_endpoint_can_include_top_chart_candidates(self):
        from app import engine as app_engine

        headers = self._admin_headers()
        primary = app_engine.fetishes[0]
        candidate = app_engine.fetishes[1]
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'result_exposures.jsonl')
            with patch.dict(os.environ, {'RESULT_EXPOSURE_LOG_PATH': path}, clear=False):
                result_exposure_service.record_result(primary['id'], primary['name'], 91, path=path)
                result_exposure_service.record_result(
                    candidate['id'],
                    candidate['name'],
                    75,
                    rank=102,
                    source=result_exposure_service.TOP_CHART_SOURCE,
                    path=path,
                )
                default = self.client.get('/api/admin/result_exposures?include_secondary=1&top_n=5', headers=headers)
                with_candidates = self.client.get(
                    '/api/admin/result_exposures?include_secondary=1&include_candidates=1&top_n=5', headers=headers
                )

        self.assertEqual(default.status_code, 200)
        self.assertEqual(with_candidates.status_code, 200)
        self.assertEqual(default.get_json()['total'], 1)
        self.assertEqual(with_candidates.get_json()['total'], 2)
        self.assertTrue(with_candidates.get_json()['include_candidates'])

    def test_result_exposure_trend_endpoint_reports_daily_heavy_ratio(self):
        from app import engine as app_engine

        headers = self._admin_headers()
        primary = app_engine.fetishes[0]
        secondary = app_engine.fetishes[1]
        old_now = type(
            'Now',
            (),
            {
                'astimezone': lambda self, tz: self,
                'isoformat': lambda self, timespec='seconds': '2026-06-01T00:00:00+00:00',
            },
        )()
        new_now = type(
            'Now',
            (),
            {
                'astimezone': lambda self, tz: self,
                'isoformat': lambda self, timespec='seconds': '2026-06-02T00:00:00+00:00',
            },
        )()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'result_exposures.jsonl')
            with patch.dict(os.environ, {'RESULT_EXPOSURE_LOG_PATH': path}, clear=False):
                result_exposure_service.record_result(
                    primary['id'], primary['name'], 91, path=path, now_fn=lambda: old_now
                )
                result_exposure_service.record_result(
                    secondary['id'], secondary['name'], 75, path=path, now_fn=lambda: new_now
                )
                res = self.client.get('/api/admin/result_exposure_trend?days=7&date=2026-06-02', headers=headers)

        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['status'], 'ok')
        self.assertEqual(data['source'], 'result_exposures')
        self.assertEqual([row['date'] for row in data['rows']], ['2026-06-01', '2026-06-02'])
        self.assertIn('heavy_result_ratio', data['rows'][0])
        self.assertIn('top_results', data['rows'][0])

    def test_result_exposures_recent_endpoint_reports_safe_timestamped_events(self):
        headers = self._admin_headers()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'result_exposures.jsonl')
            with patch.dict(
                os.environ, {'RESULT_EXPOSURE_LOG_PATH': path, 'ANALYTICS_EVENT_STORAGE': 'jsonl'}, clear=False
            ):
                result_exposure_service.record_result(1, '激重感情', 91, path=path)
                result_exposure_service.record_result(2, '白衣', 75, path=path)
                res = self.client.get('/api/admin/result_exposures/recent?limit=1', headers=headers)

        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['status'], 'ok')
        self.assertEqual(data['source'], 'result_exposures')
        self.assertEqual(len(data['events']), 1)
        self.assertEqual(data['events'][0]['fetish_name'], '白衣')
        self.assertIn('timestamp', data['events'][0])
        body = json.dumps(data, ensure_ascii=False)
        self.assertNotIn('remote_addr', body)
        self.assertNotIn('user_agent', body)
        self.assertNotIn('session_id', body)

    def test_quality_report_endpoint(self):
        headers = self._admin_headers()
        res = self.client.get('/api/admin/quality_report', headers=headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn('low_questions', data)
        self.assertIn('high_correlation_questions', data)
        self.assertIn('weak_fetishes', data)
        self.assertIn('feedback_summary', data)
        self.assertIn('confusion_summary', data)
        self.assertIn('low_confidence_summary', data)
        self.assertIn('action_items', data)

    def test_quality_report_includes_low_confidence_effectiveness(self):
        import app as app_module
        from app import engine as app_engine

        fid = app_engine.fetishes[0]['id']
        quality_stats_service.record_quality_stat(app_engine, 'q_low_conf_guess')
        quality_stats_service.record_quality_stat(app_engine, 'q_additional_guess')
        quality_stats_service.record_quality_stat(app_engine, 'q_additional_question', 2)
        with self.client.session_transaction() as sess:
            sess['answers'] = {}
            sess['last_guess_quality'] = {
                'low_confidence_extended': True,
                'additional_questions': 2,
            }
        res = self.client.post('/api/confirm', json={'correct': True, 'fetish_id': fid})
        self.assertEqual(res.status_code, 200)

        headers = self._admin_headers()
        res = self.client.get('/api/admin/quality_report', headers=headers)
        self.assertEqual(res.status_code, 200)
        summary = res.get_json()['low_confidence_summary']
        self.assertGreaterEqual(summary['low_confidence_guesses'], 1)
        self.assertGreaterEqual(summary['low_confidence_correct'], 1)
        self.assertGreaterEqual(summary['additional_questions_asked'], 2)

    def test_maintenance_checklist_endpoint(self):
        headers = self._admin_headers()
        res = self.client.get('/api/admin/maintenance_checklist', headers=headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        admin_page = self.client.get('/admin', headers=headers)
        self.assertEqual(admin_page.status_code, 200)
        self.assertIn(b'apply-works-seed-backfill', admin_page.data)
        self.assertIn(b'repair-promoted-stats-dry-run', admin_page.data)
        self.assertIn(b'repair-promoted-stats-apply', admin_page.data)
        self.assertIn(b'move-stats-history-dry-run', admin_page.data)
        self.assertIn(b'move-stats-history-apply', admin_page.data)
        self.assertIn(b'lookup-fetish-id', admin_page.data)
        self.assertIn('checklist', data)
        self.assertIn('weak_fetishes', data)
        self.assertIn('duplicate_questions', data)
        self.assertIn('low_questions', data)
        self.assertIn('works', data)
        ids = {item['id'] for item in data['checklist']}
        self.assertIn('weak_fetishes', ids)
        self.assertIn('duplicate_questions', ids)
        self.assertIn('low_questions', ids)
        self.assertIn('works', ids)
        self.assertIn('missing_url_work_count', data['works'])
        self.assertIn('direct_url_work_count', data['works'])
        self.assertIn('search_url_work_count', data['works'])
        self.assertIn('missing_asin_work_count', data['works'])
        self.assertIn('duplicate_work_title_count', data['works'])
        if data['weak_fetishes']:
            row = data['weak_fetishes'][0]
            self.assertIn('edit_anchor', row)
            self.assertIn('similarity_anchor', row)
            self.assertIn('hint', row)
        if data['duplicate_questions']:
            self.assertIn('suggested_action', data['duplicate_questions'][0])

    def test_edit_question(self):
        headers = self._admin_headers()
        from app import engine as app_engine

        orig = app_engine.questions[0]['text']
        try:
            res = self.client.post('/api/admin/edit_question/0', json={'text': 'テスト用質問文'}, headers=headers)
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.get_json()['text'], 'テスト用質問文')
            self.assertEqual(app_engine.questions[0]['text'], 'テスト用質問文')
        finally:
            app_engine.edit_question(0, orig)

    def test_admin_fetish_lookup_returns_name(self):
        headers = self._admin_headers()
        res = self.client.get('/api/admin/fetish_lookup/0', headers=headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['status'], 'ok')
        self.assertEqual(data['id'], 0)
        self.assertIn('name', data)
        self.assertFalse(data['is_player_fetish'])

        missing = self.client.get('/api/admin/fetish_lookup/999999', headers=headers)
        self.assertEqual(missing.status_code, 404)

    def test_repair_promoted_stats_history_requires_mapping_and_confirm(self):
        headers = self._admin_headers()
        res = self.client.get('/api/admin/repair_promoted_stats_history', headers=headers)
        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertEqual(data['required_confirm_text'], 'REPAIR_PROMOTED_STATS')

        with (
            patch('engine.facade._use_db', return_value=True),
            patch(
                'engine.db.promoted_stats_history_repair_report',
                return_value={'mapping_count': 1, 'rows': [], 'total_value': 0, 'storage': 'postgres'},
            ),
            patch(
                'engine.db.repair_promoted_stats_history',
                return_value={'mapping_count': 1, 'rows': [], 'total_value': 3, 'applied': True, 'storage': 'postgres'},
            ),
        ):
            dry = self.client.get(
                '/api/admin/repair_promoted_stats_history',
                headers=headers,
                json={'mappings': [{'old_id': 10000, 'new_id': 3}]},
            )
            self.assertEqual(dry.status_code, 200)
            self.assertEqual(dry.get_json()['mode'], 'dry_run')

            post_dry = self.client.post(
                '/api/admin/repair_promoted_stats_history',
                headers=headers,
                json={
                    'dry_run': True,
                    'mappings': [{'old_id': 10000, 'new_id': 3}],
                },
            )
            self.assertEqual(post_dry.status_code, 200)
            self.assertEqual(post_dry.get_json()['mode'], 'dry_run')

            missing_confirm = self.client.post(
                '/api/admin/repair_promoted_stats_history',
                headers=headers,
                json={'mappings': [{'old_id': 10000, 'new_id': 3}]},
            )
            self.assertEqual(missing_confirm.status_code, 400)
            self.assertEqual(missing_confirm.get_json()['required_confirm_text'], 'REPAIR_PROMOTED_STATS')

            applied = self.client.post(
                '/api/admin/repair_promoted_stats_history',
                headers=headers,
                json={
                    'mappings': [{'old_id': 10000, 'new_id': 3}],
                    'confirm_text': 'REPAIR_PROMOTED_STATS',
                },
            )
            self.assertEqual(applied.status_code, 200)
            self.assertEqual(applied.get_json()['mode'], 'applied')
            self.assertEqual(applied.get_json()['total_value'], 3)

    def test_move_stats_history_allows_seed_id_correction_with_confirm(self):
        headers = self._admin_headers()
        with (
            patch('engine.facade._use_db', return_value=True),
            patch(
                'engine.db.promoted_stats_history_repair_report',
                return_value={'mapping_count': 4, 'rows': [], 'total_value': 12, 'storage': 'postgres'},
            ),
            patch(
                'engine.db.repair_promoted_stats_history',
                return_value={
                    'mapping_count': 4,
                    'rows': [],
                    'total_value': 12,
                    'applied': True,
                    'storage': 'postgres',
                },
            ),
        ):
            dry = self.client.post(
                '/api/admin/move_stats_history',
                headers=headers,
                json={
                    'dry_run': True,
                    'mappings': [
                        {'old_id': 129, 'new_id': 128},
                        {'old_id': 130, 'new_id': 129},
                        {'old_id': 131, 'new_id': 130},
                        {'old_id': 132, 'new_id': 131},
                    ],
                },
            )
            self.assertEqual(dry.status_code, 200)
            self.assertEqual(dry.get_json()['mode'], 'dry_run')

            rejected = self.client.post(
                '/api/admin/move_stats_history',
                headers=headers,
                json={
                    'mappings': [{'old_id': 129, 'new_id': 128}],
                },
            )
            self.assertEqual(rejected.status_code, 400)
            self.assertEqual(rejected.get_json()['required_confirm_text'], 'MOVE_STATS_HISTORY')

            applied = self.client.post(
                '/api/admin/move_stats_history',
                headers=headers,
                json={
                    'confirm_text': 'MOVE_STATS_HISTORY',
                    'mappings': [{'old_id': 129, 'new_id': 128}],
                },
            )
            self.assertEqual(applied.status_code, 200)
            self.assertEqual(applied.get_json()['mode'], 'applied')

    def test_high_yes_rate_questions_are_more_selective(self):
        with open(os.path.join(DATA_DIR, 'questions.json'), encoding='utf-8') as f:
            questions = json.load(f)

        self.assertEqual(questions[5]['id'], 5)
        self.assertIn('少し波がある関係の方が好き', questions[5]['text'])
        self.assertNotIn('甘くて幸せ', questions[5]['text'])
        self.assertEqual(questions[111]['id'], 111)
        self.assertIn('たまに余裕をなくす人の方が好き', questions[111]['text'])
        self.assertEqual(questions[124]['id'], 124)
        self.assertIn('礼儀を保ったまま少しずつ近づく関係が好き', questions[124]['text'])
        self.assertEqual(questions[135]['id'], 135)
        self.assertIn('身近にいそうな相手より、少し現実離れした相手の方が好き', questions[135]['text'])

    def test_edit_question_empty_text_rejected(self):
        headers = self._admin_headers()
        res = self.client.post('/api/admin/edit_question/0', json={'text': '  '}, headers=headers)
        self.assertEqual(res.status_code, 400)

    def test_admin_question_events_report_and_csv(self):
        headers = self._admin_headers()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'question_events.jsonl')
            question_events_service.record_event(
                'question_shown',
                question_id=1,
                question_text='返信が遅いと気になる？',
                category='attachment',
                axis='abstract',
                path=path,
            )
            question_events_service.record_event(
                'question_answered', question_id=1, answer=1.0, category='attachment', axis='abstract', path=path
            )
            question_events_service.record_event(
                'question_dropoff', question_id=1, answered_count=1, category='attachment', axis='abstract', path=path
            )
            question_events_service.record_event(
                'question_shown',
                question_id=2,
                question_text='現実寄りより、少し非現実感がある方が惹かれる？',
                category='world',
                axis='abstract',
                path=path,
            )
            question_events_service.record_event(
                'question_result_contribution',
                question_id=1,
                result_name='共依存',
                answer=1.0,
                result_rank=1,
                path=path,
            )
            with patch.dict(os.environ, {'QUESTION_EVENT_LOG_PATH': path}):
                report = self.client.get('/api/admin/question_events', headers=headers)
                questions_csv = self.client.get('/api/admin/question_events/questions.csv', headers=headers)
                category_csv = self.client.get('/api/admin/question_events/category.csv', headers=headers)
        self.assertEqual(report.status_code, 200)
        data = report.get_json()
        self.assertEqual(data['status'], 'ok')
        self.assertEqual(data['metrics']['shown'], 2)
        self.assertEqual(data['metrics']['answered'], 1)
        self.assertEqual(data['metrics']['dropoffs'], 1)
        self.assertEqual(data['questions'][0]['question_id'], 1)
        self.assertEqual(data['questions'][0]['yes_rate'], 100.0)
        self.assertEqual(data['contribution_ranking'][0]['top_results'][0]['result_name'], '共依存')
        self.assertIn('text/csv', questions_csv.content_type)
        self.assertIn('question_id,category,axis,shown', questions_csv.data.decode('utf-8').splitlines()[0])
        self.assertIn('category,shown,shown_share', category_csv.data.decode('utf-8').splitlines()[0])

    def test_admin_question_events_can_include_suspicious_events_for_diffing(self):
        headers = self._admin_headers()

        def fixed_now(value):
            return type(
                'Now',
                (),
                {
                    'astimezone': lambda self, tz: self,
                    'isoformat': lambda self, timespec='seconds': value,
                },
            )()

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'question_events.jsonl')
            timestamp = '2026-06-21T00:00:00+00:00'
            question_events_service.record_event(
                'question_shown', question_id=1, path=path, now_fn=lambda: fixed_now(timestamp)
            )
            for _ in range(12):
                question_events_service.record_event(
                    'question_answered', question_id=1, answer=1.0, path=path, now_fn=lambda: fixed_now(timestamp)
                )
            with patch.dict(os.environ, {'QUESTION_EVENT_LOG_PATH': path}):
                filtered = self.client.get('/api/admin/question_events?exclude_suspicious=1', headers=headers)
                raw = self.client.get('/api/admin/question_events?exclude_suspicious=0', headers=headers)

        self.assertEqual(filtered.status_code, 200)
        self.assertEqual(raw.status_code, 200)
        self.assertEqual(filtered.get_json()['total'], 0)
        self.assertEqual(filtered.get_json()['quality']['excluded_suspicious_events'], 13)
        self.assertEqual(raw.get_json()['total'], 13)
        self.assertEqual(raw.get_json()['quality']['excluded_suspicious_events'], 0)

    def test_high_yes_rate_questions_are_reworded_to_tradeoffs(self):
        from app import engine as app_engine

        self.assertEqual(
            app_engine.questions[35]['text'],
            '言葉が少ないのに、気持ちが伝わる人が気になる？',
        )
        self.assertEqual(app_engine.questions[35].get('category'), 'tone')
        self.assertEqual(
            app_engine.questions[141]['text'],
            '生活感のある賑やかさより、余白が多く整った静けさの方が落ち着く？',
        )
        self.assertEqual(app_engine.questions[141].get('category'), 'aesthetic')
        self.assertEqual(
            app_engine.questions[135]['text'],
            '身近にいそうな相手より、少し現実離れした相手の方が好き？',
        )
        self.assertEqual(app_engine.questions[135].get('category'), 'world')

    def test_question_events_are_recorded_without_personal_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'question_events.jsonl')
            with patch.dict(os.environ, {'QUESTION_EVENT_LOG_PATH': path}):
                start = self.client.post('/api/start').get_json()
                self.client.post('/api/answer', json={'question_id': start['question_id'], 'answer': 1.0})
                with self.client.session_transaction() as sess:
                    sess['completed'] = False
                    sess['dropoff_recorded'] = False
                self.client.post('/api/dropoff', json={'question_id': start['question_id']})
                events = question_events_service.read_events(path=path, limit=10)
        names = [event['event_name'] for event in events]
        self.assertIn('question_shown', names)
        self.assertIn('question_answered', names)
        self.assertIn('question_dropoff', names)
        self.assertTrue(
            all('ip' not in event and 'user_agent' not in event and 'session' not in event for event in events)
        )

    def test_admin_page_shows_analysis_log_status(self):
        headers = self._admin_headers()
        with tempfile.TemporaryDirectory() as tmp:
            q_path = os.path.join(tmp, 'question_events.jsonl')
            s_path = os.path.join(tmp, 'share_events.jsonl')
            question_events_service.record_event('question_shown', question_id=1, path=q_path)
            share_events_service.record_event(
                'result_page_view', result_name='NTR（寝取られ）', channel='result_page', success=True, path=s_path
            )
            with patch.dict(os.environ, {'QUESTION_EVENT_LOG_PATH': q_path, 'SHARE_EVENT_LOG_PATH': s_path}):
                res = self.client.get('/admin', headers=headers)
        self.assertEqual(res.status_code, 200)
        body = res.data.decode('utf-8')
        self.assertIn('分析ログ蓄積状況', body)
        self.assertIn('question_events が少ないため', body)
        self.assertIn('share_events が少ないため', body)
        self.assertIn('取得元: JSONL question_events', body)

    def test_admin_share_events_report(self):
        headers = self._admin_headers()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'share_events.jsonl')
            old_now = type(
                'Now',
                (),
                {
                    'astimezone': lambda self, tz: self,
                    'isoformat': lambda self, timespec='seconds': '2026-05-23T00:00:00+00:00',
                },
            )()
            new_now = type(
                'Now',
                (),
                {
                    'astimezone': lambda self, tz: self,
                    'isoformat': lambda self, timespec='seconds': '2026-05-24T00:00:00+00:00',
                },
            )()
            share_events_service.record_event(
                'share_button_click',
                result_name='OLD',
                channel='button',
                success=True,
                path=path,
                now_fn=lambda: old_now,
            )
            share_events_service.record_event(
                'copy_success',
                result_name='NTR（寝取られ）',
                channel='clipboard',
                success=True,
                path=path,
                now_fn=lambda: new_now,
            )
            share_events_service.record_event(
                'copy_failure',
                result_name='NTR（寝取られ）',
                channel='clipboard',
                success=False,
                path=path,
                now_fn=lambda: new_now,
            )
            share_events_service.record_event(
                'share_button_click',
                result_name='NTR（寝取られ）',
                channel='button',
                success=True,
                path=path,
                now_fn=lambda: new_now,
            )
            share_events_service.record_event(
                'result_page_view',
                result_name='NTR（寝取られ）',
                channel='result_page',
                success=True,
                path=path,
                now_fn=lambda: new_now,
            )
            share_events_service.record_event(
                'work_click',
                result_name='NTR（寝取られ）',
                channel='work',
                success=True,
                work_title='作品A',
                page='result_works',
                path=path,
                now_fn=lambda: new_now,
            )
            with patch.dict(os.environ, {'SHARE_EVENT_LOG_PATH': path}):
                res = self.client.get('/api/admin/share_events?since=2026-05-24&until=2026-05-24', headers=headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['status'], 'ok')
        self.assertEqual(data['total'], 5)
        self.assertEqual(data['by_event']['copy_success'], 1)
        self.assertEqual(data['by_channel']['clipboard'], 2)
        self.assertEqual(data['success']['true'], 4)
        self.assertEqual(data['success']['false'], 1)
        self.assertEqual(data['metrics']['copy_successes'], 1)
        self.assertEqual(data['metrics']['copy_failures'], 1)
        self.assertEqual(data['daily'][0]['copy_successes'], 1)
        self.assertEqual(data['daily'][0]['work_clicks'], 1)
        self.assertEqual(data['ranking'][0]['result_name'], 'NTR（寝取られ）')
        self.assertEqual(data['ranking'][0]['copy_successes'], 1)
        self.assertEqual(data['ranking'][0]['share_actions'], 1)
        self.assertEqual(data['ranking'][0]['share_success_rate'], 100.0)
        self.assertEqual(data['ranking'][0]['work_clicks'], 1)
        self.assertEqual(data['work_ranking'][0]['work_title'], '作品A')
        self.assertTrue(data['comparison']['enabled'])
        self.assertEqual(data['comparison']['metrics']['total']['current'], 5)
        self.assertEqual(data['comparison']['metrics']['total']['previous'], 1)
        self.assertEqual(data['filters']['since'], '2026-05-24')
        self.assertEqual(data['filters']['compare_since'], '2026-05-23')
        self.assertIn('share_actions_delta', data['ranking'][0])

    def test_admin_share_events_ranking_filters_unknown_result_names(self):
        headers = self._admin_headers()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'share_events.jsonl')
            for result_name in ('白衣', 'health', 'abc', 'へきネイター'):
                share_events_service.record_event(
                    'result_page_view',
                    result_name=result_name,
                    channel='result_page',
                    success=True,
                    path=path,
                )
            with patch.dict(os.environ, {'SHARE_EVENT_LOG_PATH': path}):
                res = self.client.get('/api/admin/share_events', headers=headers)

        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['total'], 4)
        ranking_names = [row['result_name'] for row in data['ranking']]
        self.assertIn('白衣', ranking_names)
        self.assertNotIn('health', ranking_names)
        self.assertNotIn('abc', ranking_names)
        self.assertNotIn('へきネイター', ranking_names)

    def test_admin_share_events_csv_exports(self):
        headers = self._admin_headers()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'share_events.jsonl')
            now = type(
                'Now',
                (),
                {
                    'astimezone': lambda self, tz: self,
                    'isoformat': lambda self, timespec='seconds': '2026-05-24T00:00:00+00:00',
                },
            )()
            share_events_service.record_event(
                'share_button_click',
                result_name='NTR（寝取られ）',
                channel='button',
                success=True,
                path=path,
                now_fn=lambda: now,
            )
            share_events_service.record_event(
                'result_page_view',
                result_name='NTR（寝取られ）',
                channel='result_page',
                success=True,
                path=path,
                now_fn=lambda: now,
            )
            with patch.dict(os.environ, {'SHARE_EVENT_LOG_PATH': path}):
                ranking = self.client.get('/api/admin/share_events/ranking.csv?since=2026-05-24', headers=headers)
                daily = self.client.get('/api/admin/share_events/daily.csv?since=2026-05-24', headers=headers)
                comparison = self.client.get(
                    '/api/admin/share_events/comparison.csv?since=2026-05-24&compare_since=2026-05-23', headers=headers
                )
        self.assertEqual(ranking.status_code, 200)
        self.assertIn('text/csv', ranking.content_type)
        ranking_header = ranking.data.decode('utf-8').splitlines()[0]
        self.assertIn('result_name,total,share_button_clicks', ranking_header)
        self.assertIn('filter_since', ranking_header)
        self.assertIn('NTR（寝取られ）', ranking.data.decode('utf-8'))
        self.assertIn('2026-05-24', ranking.data.decode('utf-8'))
        self.assertEqual(daily.status_code, 200)
        daily_header = daily.data.decode('utf-8').splitlines()[0]
        self.assertIn('date,total,share_button_clicks', daily_header)
        self.assertIn('filter_since', daily_header)
        self.assertIn('2026-05-24', daily.data.decode('utf-8'))
        self.assertEqual(comparison.status_code, 200)
        comparison_header = comparison.data.decode('utf-8').splitlines()[0]
        self.assertIn('metric,current,previous,delta,growth_rate', comparison_header)
        self.assertIn('compare_since', comparison_header)

    def test_admin_page_renders_share_event_summary(self):
        headers = self._admin_headers()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'share_events.jsonl')
            share_events_service.record_event(
                'share_button_click', result_name='NTR（寝取られ）', channel='button', success=True, path=path
            )
            share_events_service.record_event(
                'web_share_success', result_name='NTR（寝取られ）', channel='web_share', success=True, path=path
            )
            share_events_service.record_event(
                'x_share_click', result_name='NTR（寝取られ）', channel='x', success=True, path=path
            )
            share_events_service.record_event(
                'ogp_png_view', result_name='NTR（寝取られ）', channel='ogp', success=True, path=path
            )
            share_events_service.record_event(
                'result_page_view', result_name='NTR（寝取られ）', channel='result_page', success=True, path=path
            )
            share_events_service.record_event(
                'share_button_click', result_name='眼鏡', channel='button', success=True, path=path
            )
            with patch.dict(os.environ, {'SHARE_EVENT_LOG_PATH': path}):
                res = self.client.get('/admin?compare_since=2026-05-20&compare_until=2026-05-20', headers=headers)
        self.assertEqual(res.status_code, 200)
        body = res.data.decode('utf-8')
        self.assertIn('拡散イベント', body)
        self.assertIn('共有ボタン押下', body)
        self.assertIn('Web Share成功', body)
        self.assertIn('Xクリック', body)
        self.assertIn('OGP表示', body)
        self.assertIn('期間適用', body)
        self.assertIn('比較since', body)
        self.assertIn('総イベント', body)
        self.assertIn('サンプルが少ない', body)
        self.assertIn('ランキングCSV', body)
        self.assertIn('比較CSV', body)
        self.assertIn('日次CSV', body)
        self.assertIn('結果別シェアランキング', body)
        self.assertIn('伸び', body)
        self.assertIn('結果→共有', body)
        self.assertIn('共有成功', body)
        self.assertIn('眼鏡', body)
        self.assertIn('/api/admin/share_events', body)

    def test_admin_share_notes_api_saves_without_personal_identifiers(self):
        headers = self._admin_headers()
        with tempfile.TemporaryDirectory() as tmp:
            notes_path = os.path.join(tmp, 'share_notes.json')
            with patch.dict(os.environ, {'SHARE_NOTES_PATH': notes_path}):
                res = self.client.post(
                    '/api/admin/share_notes',
                    headers=headers,
                    json={'result_name': 'NTR（寝取られ）', 'note': 'OGP称号を強める'},
                )
                self.assertEqual(res.status_code, 200)
                data = res.get_json()
                self.assertEqual(data['status'], 'ok')
                self.assertEqual(data['note']['note'], 'OGP称号を強める')
                get_res = self.client.get('/api/admin/share_notes', headers=headers)
                self.assertEqual(get_res.status_code, 200)
                self.assertEqual(get_res.get_json()['notes']['NTR（寝取られ）']['note'], 'OGP称号を強める')
        self.assertNotIn('remote_addr', json.dumps(data, ensure_ascii=False))

    def test_admin_share_notes_csrf_enforced_when_enabled(self):
        app.config['ENFORCE_CSRF'] = True
        try:
            headers = self._admin_headers()
            with tempfile.TemporaryDirectory() as tmp:
                notes_path = os.path.join(tmp, 'share_notes.json')
                with patch.dict(os.environ, {'SHARE_NOTES_PATH': notes_path}):
                    blocked = self.client.post(
                        '/api/admin/share_notes',
                        headers=headers,
                        json={'result_name': 'NTR（寝取られ）', 'note': 'blocked'},
                    )
                    self.assertEqual(blocked.status_code, 403)
                    admin = self.client.get('/admin', headers=headers)
                    self.assertEqual(admin.status_code, 200)
                    match = re.search(r'csrfToken: "([^"]+)"', admin.data.decode('utf-8'))
                    self.assertIsNotNone(match)
                    ok = self.client.post(
                        '/api/admin/share_notes',
                        headers={**headers, 'X-CSRF-Token': match.group(1)},
                        json={'result_name': 'NTR（寝取られ）', 'note': 'saved'},
                    )
                    self.assertEqual(ok.status_code, 200)
        finally:
            app.config.pop('ENFORCE_CSRF', None)

    def test_admin_page_renders_escaped_share_note_form(self):
        headers = self._admin_headers()
        with tempfile.TemporaryDirectory() as tmp:
            events_path = os.path.join(tmp, 'share_events.jsonl')
            notes_path = os.path.join(tmp, 'share_notes.json')
            share_events_service.record_event(
                'share_button_click', result_name='NTR（寝取られ）', channel='button', success=True, path=events_path
            )
            share_notes_service.save_note('NTR（寝取られ）', '<script>alert(1)</script>', path=notes_path)
            with patch.dict(os.environ, {'SHARE_EVENT_LOG_PATH': events_path, 'SHARE_NOTES_PATH': notes_path}):
                res = self.client.get('/admin', headers=headers)
        self.assertEqual(res.status_code, 200)
        body = res.data.decode('utf-8')
        self.assertIn('改善メモあり', body)
        self.assertIn('data-action="save-share-note"', body)
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', body)
        self.assertNotIn('<script>alert(1)</script>', body)

    def test_edit_fetish(self):
        from app import engine as app_engine

        headers = self._admin_headers()
        fid = app_engine.fetishes[0]['id']
        orig_name = app_engine.fetishes[0]['name']
        try:
            res = self.client.post(f'/api/admin/edit_fetish/{fid}', json={'name': 'テスト編集名'}, headers=headers)
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.get_json()['name'], 'テスト編集名')
            self.assertEqual(app_engine.fetishes[0]['name'], 'テスト編集名')
        finally:
            app_engine.edit_fetish(fid, name=orig_name)

    def test_merge_fetishes(self):
        # Add two player fetishes to merge
        import os

        from app import engine as app_engine

        os.environ['ADMIN_PASS'] = 'testpass'
        r1 = self.client.post(
            '/api/add_fetish', json={'name': 'マージテストA_xyz', 'desc': 'テストA', 'confirmed': True}
        )
        r2 = self.client.post(
            '/api/add_fetish', json={'name': 'マージテストB_xyz', 'desc': 'テストB', 'confirmed': True}
        )
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)
        id_a = r1.get_json()['fetish_id']
        id_b = r2.get_json()['fetish_id']
        idx_a = app_engine.index_of(id_a)
        idx_b = app_engine.index_of(id_b)
        # Save matrix values before merge
        nq = len(app_engine.questions)
        yes_a = list(app_engine.matrix['yes'][idx_a])
        yes_b = list(app_engine.matrix['yes'][idx_b])
        try:
            ok = app_engine.merge_fetishes(id_a, id_b, new_name='マージ済み_xyz')
            self.assertTrue(ok)
            # id_b should be gone
            self.assertIsNone(app_engine.index_of(id_b))
            # id_a should still exist with summed matrix
            new_idx_a = app_engine.index_of(id_a)
            self.assertIsNotNone(new_idx_a)
            for q in range(min(5, nq)):
                self.assertAlmostEqual(app_engine.matrix['yes'][new_idx_a][q], yes_a[q] + yes_b[q], places=5)
            # New name applied
            self.assertEqual(app_engine.fetishes[new_idx_a]['name'], 'マージ済み_xyz')
        finally:
            # Cleanup: remove remaining merged fetish
            idx = app_engine.index_of(id_a)
            if idx is not None:
                app_engine.fetishes.pop(idx)
                app_engine.matrix['yes'].pop(idx)
                app_engine.matrix['total'].pop(idx)
                app_engine._save_fetishes_file()

    def test_fetish_similarity(self):
        from app import engine as app_engine

        headers = self._admin_headers()
        id_a = app_engine.fetishes[0]['id']
        id_b = app_engine.fetishes[1]['id']
        res = self.client.post('/api/admin/fetish_similarity', json={'id_a': id_a, 'id_b': id_b}, headers=headers)
        self.assertEqual(res.status_code, 200)
        d = res.get_json()
        self.assertIn('cosine', d)
        self.assertIn('top_diff', d)
        self.assertEqual(len(d['top_diff']), 5)
        self.assertGreaterEqual(d['cosine'], -1.0)
        self.assertLessEqual(d['cosine'], 1.0)

    def test_fetish_similarity_invalid_id(self):
        headers = self._admin_headers()
        res = self.client.post('/api/admin/fetish_similarity', json={'id_a': 999999, 'id_b': 0}, headers=headers)
        self.assertEqual(res.status_code, 404)

    def test_fetish_similarity_rejects_non_integer_ids(self):
        headers = self._admin_headers()
        res = self.client.post('/api/admin/fetish_similarity', json={'id_a': 'x', 'id_b': 0}, headers=headers)
        self.assertEqual(res.status_code, 400)

    def test_axis_stats_in_admin(self):
        headers = self._admin_headers()
        res = self.client.get('/admin', headers=headers)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'content', res.data)
        self.assertIn(b'personality', res.data)

    def test_export_stats_history_returns_csv(self):
        headers = self._admin_headers()
        res = self.client.get('/api/admin/export_stats_history', headers=headers)
        self.assertEqual(res.status_code, 200)
        self.assertIn('text/csv', res.content_type)
        first_line = res.data.decode('utf-8').split('\n')[0]
        self.assertEqual(first_line, 'date,start,completion,play,learn,correct,wrong,dropoff')
