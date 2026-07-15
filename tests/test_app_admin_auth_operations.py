# ruff: noqa: F403, F405

from tests._app_test_support import *


class TestAdminAuthOperations(APITestCase):
    def test_admin_params_rejects_non_finite_and_out_of_range_values(self):
        headers = self._admin_headers()
        from app import engine as app_engine

        before = app_engine.config.get('guess_threshold')
        res = self.client.post(
            '/api/admin/params', json={'guess_threshold': 'nan', 'compound_ratio': 2}, headers=headers
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['updated'], {})
        self.assertGreaterEqual(len(data['errors']), 2)
        self.assertEqual(app_engine.config.get('guess_threshold'), before)

    def test_admin_read_token_allows_read_only_analytics(self):
        with patch.dict(os.environ, {'ADMIN_READ_TOKEN': 'read-token', 'ADMIN_PASS': 'testpass'}):
            headers = self._admin_read_headers()
            for path in (
                '/api/admin/preflight',
                '/api/admin/read_overview',
                '/api/admin/fetishes_snapshot',
                '/api/admin/learning_stats',
                '/api/admin/question_stats',
                '/api/admin/operations_snapshot',
                '/api/admin/quality_report',
                '/api/admin/works_health',
                '/api/admin/audit_log',
                '/api/admin/maintenance_checklist',
                '/api/admin/matrix_health',
                '/api/admin/funnel_metrics',
                '/api/admin/player_fetishes',
                '/api/admin/promoted_fetish_history',
                '/api/admin/question_events',
                '/api/admin/share_events',
                '/api/admin/fetish_log_rows',
                '/api/admin/recent_fetish_ranking',
                '/api/admin/dry_run_guess?answers=0:1,1:-1',
                '/api/admin/result_exposures',
                '/api/admin/result_exposure_trend',
                '/api/admin/result_exposure_factors',
                '/api/admin/result_exposures/backfill',
                '/api/admin/export_stats_history',
                '/api/admin/matrix_backups',
                '/api/admin/works_link_queue',
                '/api/admin/share_notes',
                '/api/admin/fetish_lookup/0',
            ):
                res = self.client.get(path, headers=headers)
                self.assertEqual(res.status_code, 200, path)

    def test_admin_read_token_cannot_mutate(self):
        with patch.dict(os.environ, {'ADMIN_READ_TOKEN': 'read-token', 'ADMIN_PASS': 'testpass'}):
            res = self.client.post(
                '/api/admin/params', headers=self._admin_read_headers(), json={'guess_threshold': 0.8}
            )
            share_note = self.client.post(
                '/api/admin/share_notes',
                headers=self._admin_read_headers(),
                json={'result_name': 'NTR（寝取られ）', 'note': 'x'},
            )
        self.assertEqual(res.status_code, 401)
        self.assertEqual(share_note.status_code, 401)

    def test_admin_dry_run_guess_is_read_only_and_no_record(self):
        import app as app_module

        with patch.dict(os.environ, {'ADMIN_READ_TOKEN': 'read-token', 'ADMIN_PASS': 'testpass'}):
            with (
                patch('services.result_exposure.safe_record_result') as record_result,
                patch('services.question_events.safe_record_event') as record_question,
            ):
                before_play = app_module.engine.get_stats().get('play_count')
                res = self.client.get(
                    '/api/admin/dry_run_guess?answers=0:1,1:-1,136:1', headers=self._admin_read_headers()
                )
                after_play = app_module.engine.get_stats().get('play_count')

        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['status'], 'ok')
        self.assertEqual(data['mode'], 'dry_run_no_record')
        self.assertFalse(data['recorded'])
        self.assertIn('result', data)
        self.assertIn('fetish_name', data['result'])
        self.assertEqual(before_play, after_play)
        record_result.assert_not_called()
        record_question.assert_not_called()

    def test_admin_dry_run_guess_rejects_bad_answers(self):
        with patch.dict(os.environ, {'ADMIN_READ_TOKEN': 'read-token', 'ADMIN_PASS': 'testpass'}):
            res = self.client.get('/api/admin/dry_run_guess?answers=0:2', headers=self._admin_read_headers())
        self.assertEqual(res.status_code, 400)

    def test_admin_result_exposure_factors_is_read_only_and_aggregate(self):
        with patch.dict(os.environ, {'ADMIN_READ_TOKEN': 'read-token', 'ADMIN_PASS': 'testpass'}):
            res = self.client.get('/api/admin/result_exposure_factors?top_n=5', headers=self._admin_read_headers())
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['status'], 'ok')
        self.assertIn('sample', data)
        self.assertIn('config', data)
        self.assertIn('most_downweighted', data)
        self.assertIn('heavy_results', data)
        body = json.dumps(data, ensure_ascii=False)
        self.assertNotIn('read-token', body)
        self.assertNotIn('ADMIN_PASS', body)
        self.assertNotIn('DATABASE_URL', body)
        self.assertNotIn('events', data)

    def test_admin_read_overview_lists_safe_snapshot_endpoints(self):
        with patch.dict(os.environ, {'ADMIN_READ_TOKEN': 'read-token', 'ADMIN_PASS': 'testpass'}):
            res = self.client.get('/api/admin/read_overview', headers=self._admin_read_headers())
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn('/api/admin/fetishes_snapshot', data['available_endpoints'])
        self.assertIn('/api/admin/funnel_metrics', data['available_endpoints'])
        self.assertIn('/api/admin/operations_snapshot', data['available_endpoints'])
        self.assertIn('/api/admin/compound_works', data['available_endpoints'])
        self.assertIn('/api/admin/low_exposure_fetishes', data['available_endpoints'])
        self.assertIn('/api/admin/added_fetishes', data['available_endpoints'])
        self.assertIn('/api/admin/result_exposures', data['available_endpoints'])
        self.assertIn('/api/admin/result_exposures/recent', data['available_endpoints'])
        self.assertIn('/api/admin/result_exposure_trend', data['available_endpoints'])
        self.assertIn('/api/admin/result_exposure_factors', data['available_endpoints'])
        self.assertIn('/api/admin/result_exposures/backfill', data['available_endpoints'])
        self.assertIn('analysis_log_status', data)
        self.assertIn('share_links_count', data)
        self.assertIsInstance(data['share_links_count'], int)
        self.assertIn('improvement_candidates', data)
        self.assertIn('result_diversity', data['improvement_candidates'])
        self.assertIn('low_learning_candidates', data)
        self.assertIn('least_exposed', data['low_learning_candidates'])

    def test_admin_added_fetishes_reports_db_only_and_player_rows(self):
        from app import engine as app_engine

        original_fetishes = list(app_engine.fetishes)
        try:
            app_engine.fetishes = original_fetishes + [
                {'id': 128, 'name': 'DB追加テスト', 'desc': 'db only', 'works': []},
                {
                    'id': PLAYER_FETISH_BASE_ID + 9,
                    'name': 'プレイヤー追加テスト',
                    'desc': 'player',
                    'works': [{'title': 'A'}],
                },
            ]
            with patch.dict(os.environ, {'ADMIN_READ_TOKEN': 'read-token', 'ADMIN_PASS': 'testpass'}):
                res = self.client.get('/api/admin/added_fetishes', headers=self._admin_read_headers())
        finally:
            app_engine.fetishes = original_fetishes

        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        by_name = {row['name']: row for row in data['added_fetishes']}
        self.assertEqual(by_name['DB追加テスト']['source'], 'promoted_or_db_added')
        self.assertEqual(by_name['プレイヤー追加テスト']['source'], 'player_added')
        self.assertEqual(data['counts']['player_added'], 1)

    def test_operations_snapshot_exposes_admin_analysis_without_secrets(self):
        env = {
            'ADMIN_READ_TOKEN': 'read-token',
            'ADMIN_PASS': 'testpass',
            'SECRET_KEY': 'secret-key-sentinel',
            'DATABASE_URL': 'postgres://secret-db-url',
        }
        with patch.dict(os.environ, env):
            res = self.client.get('/api/admin/operations_snapshot', headers=self._admin_read_headers())
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['status'], 'ok')
        self.assertEqual(data['scope'], 'read_only_operations_snapshot')
        self.assertIn('engine_config', data)
        self.assertIn('questions', data)
        self.assertIn('correlation_stats', data)
        self.assertIn('domain_suggestions', data)
        self.assertIn('matrix_heatmap', data)
        self.assertIn('axis_stats', data)
        self.assertIn('compound_works', data)
        self.assertIn('analysis_logs', data)
        self.assertIn('question_events_summary', data)
        self.assertIn('raw_loaded', data['question_events_summary'])
        self.assertIn('total_available', data['question_events_summary'])
        self.assertIn('quality', data['question_events_summary'])
        body = res.data.decode('utf-8', errors='replace')
        for forbidden in (
            'secret-key-sentinel',
            'postgres://secret-db-url',
            'testpass',
            'csrf_token',
            'session_id',
            'user_agent',
        ):
            self.assertNotIn(forbidden, body)

    def test_admin_read_token_security_contract_for_read_endpoints(self):
        import app as app_module

        old_counts = dict(app_module._ERROR_COUNTS)
        read_paths = (
            '/api/admin/preflight',
            '/api/admin/read_overview',
            '/api/admin/fetishes_snapshot',
            '/api/admin/learning_stats',
            '/api/admin/question_stats',
            '/api/admin/operations_snapshot',
            '/api/admin/quality_report',
            '/api/admin/works_health',
            '/api/admin/audit_log',
            '/api/admin/audit_log?format=csv',
            '/api/admin/maintenance_checklist',
            '/api/admin/matrix_health',
            '/api/admin/funnel_metrics',
            '/api/admin/player_fetishes',
            '/api/admin/promoted_fetish_history',
            '/api/admin/question_events?limit=50',
            '/api/admin/question_events/questions.csv?limit=50',
            '/api/admin/question_events/category.csv?limit=50',
            '/api/admin/share_events?limit=50',
            '/api/admin/share_events/ranking.csv?limit=50',
            '/api/admin/share_events/daily.csv?limit=50',
            '/api/admin/share_events/comparison.csv?limit=50',
            '/api/admin/share_notes',
            '/api/admin/fetish_log_rows?page=1&per_page=10',
            '/api/admin/low_exposure_fetishes?threshold=3&limit=20',
            '/api/admin/recent_fetish_ranking',
            '/api/admin/result_exposures?days=7&top_n=20',
            '/api/admin/result_exposure_trend?days=7&top_n=5',
            '/api/admin/result_exposures/backfill?max_events=50',
            '/api/admin/export_stats_history',
            '/api/admin/matrix_backups',
            '/api/admin/works_link_queue',
            '/api/admin/compound_works',
            '/api/admin/works_review',
            '/api/admin/fetish_lookup/0',
            '/api/admin/fetish_history/0',
            '/api/admin/performance',
        )
        env = {
            'ADMIN_READ_TOKEN': 'read-secret-token',
            'ADMIN_PASS': 'admin-secret-pass',
            'SECRET_KEY': 'secret-key-sentinel',
            'DATABASE_URL': 'postgres://secret-db-url',
        }
        forbidden_values = tuple(env.values()) + (
            'remote_addr',
            'user_agent',
            'session_id',
            'ADMIN_PASS',
            'DATABASE_URL',
            'SECRET_KEY',
        )
        try:
            with patch.dict(os.environ, env):
                headers = {'Authorization': 'Bearer read-secret-token'}
                for path in read_paths:
                    with self.subTest(path=path):
                        unauth = self.client.get(path)
                        self.assertIn(unauth.status_code, (401, 403), path)
                        res = self.client.get(path, headers=headers)
                        self.assertEqual(res.status_code, 200, path)
                        body = res.data.decode('utf-8', errors='replace')
                        for forbidden in forbidden_values:
                            self.assertNotIn(forbidden, body, path)
                        self.assertLess(len(res.data), 1_500_000, path)
        finally:
            app_module._ERROR_COUNTS.clear()
            app_module._ERROR_COUNTS.update(old_counts)

    def test_admin_read_token_rejects_mutation_endpoints(self):
        import app as app_module

        old_counts = dict(app_module._ERROR_COUNTS)
        mutation_paths = (
            ('/admin/test_play/start', {}),
            ('/admin/test_play/stop', {}),
            ('/api/admin/params', {'guess_threshold': 0.8}),
            ('/api/admin/cleanup_sessions', {}),
            ('/api/admin/add_fetish', {'name': 'x', 'desc': 'x'}),
            ('/api/admin/capture_priors', {}),
            ('/api/admin/promote_fetish/10000', {}),
            ('/api/admin/edit_question/0', {'text': 'x'}),
            ('/api/admin/edit_fetish/0', {'name': 'x'}),
            ('/api/admin/merge_fetishes', {'id_keep': 0, 'id_remove': 1}),
            ('/api/admin/import_matrix/dry_run', {'matrix_rows': []}),
            ('/api/admin/share_notes', {'result_name': 'NTR（寝取られ）', 'note': 'x'}),
            ('/api/admin/result_exposures/backfill', {'confirm_text': 'BACKFILL_RESULT_EXPOSURES'}),
        )
        try:
            with patch.dict(os.environ, {'ADMIN_READ_TOKEN': 'read-token', 'ADMIN_PASS': 'testpass'}):
                headers = self._admin_read_headers()
                for path, payload in mutation_paths:
                    with self.subTest(path=path):
                        res = self.client.post(path, headers=headers, json=payload)
                        self.assertIn(res.status_code, (401, 403), path)
        finally:
            app_module._ERROR_COUNTS.clear()
            app_module._ERROR_COUNTS.update(old_counts)

    def test_basic_admin_auth_still_allows_management_read(self):
        with patch.dict(os.environ, {'ADMIN_READ_TOKEN': 'read-token', 'ADMIN_PASS': 'testpass'}):
            res = self.client.get('/api/admin/preflight', headers=self._admin_headers())
            self.assertEqual(res.status_code, 200)
            page = self.client.get('/admin', headers=self._admin_headers())
            self.assertEqual(page.status_code, 200)

    def test_admin_read_token_requires_env(self):
        old_token = os.environ.pop('ADMIN_READ_TOKEN', None)
        try:
            res = self.client.get('/api/admin/preflight', headers={'Authorization': 'Bearer read-token'})
            self.assertIn(res.status_code, (401, 503))
        finally:
            if old_token is not None:
                os.environ['ADMIN_READ_TOKEN'] = old_token

    def test_preflight_includes_ogp_font_check(self):
        headers = self._admin_headers()
        with tempfile.TemporaryDirectory() as tmp:
            q_path = os.path.join(tmp, 'question_events.jsonl')
            s_path = os.path.join(tmp, 'share_events.jsonl')
            question_events_service.record_event('question_shown', question_id=1, path=q_path)
            share_events_service.record_event(
                'result_page_view', result_name='NTR（寝取られ）', channel='result_page', success=True, path=s_path
            )
            with patch.dict(os.environ, {'QUESTION_EVENT_LOG_PATH': q_path, 'SHARE_EVENT_LOG_PATH': s_path}):
                res = self.client.get('/api/admin/preflight', headers=headers)
        self.assertEqual(res.status_code, 200)
        checks = {row['name']: row for row in res.get_json()['checks']}
        self.assertIn('ogp_cjk_font_available', checks)
        self.assertIn('analysis_stats_history_rows', checks)
        self.assertIn('1 question_events rows', checks['analysis_question_events_rows']['detail'])
        self.assertIn('1 share_events rows', checks['analysis_share_events_rows']['detail'])
        self.assertIn(q_path, checks['analysis_question_events_rows']['detail'])
        self.assertIn(s_path, checks['analysis_share_events_rows']['detail'])
        self.assertIn('writable=True', checks['analysis_question_events_rows']['detail'])
        self.assertIn('writable=True', checks['analysis_share_events_rows']['detail'])

    def test_audit_log_export_and_preflight(self):
        headers = self._admin_headers()
        res = self.client.get('/api/admin/audit_log', headers=headers)
        self.assertEqual(res.status_code, 200)
        self.assertIn('audit_log', res.get_json())
        res = self.client.get('/api/admin/audit_log?format=csv', headers=headers)
        self.assertEqual(res.status_code, 200)
        self.assertIn('text/csv', res.content_type)
        self.assertTrue(res.data.decode('utf-8').startswith('ts,action,status'))
        old_keep = os.environ.get('MATRIX_IMPORT_BACKUP_KEEP')
        try:
            os.environ['MATRIX_IMPORT_BACKUP_KEEP'] = 'bad'
            res = self.client.get('/api/admin/preflight', headers=headers)
            self.assertEqual(res.status_code, 200)
            self.assertIn('checks', res.get_json())
        finally:
            if old_keep is None:
                os.environ.pop('MATRIX_IMPORT_BACKUP_KEEP', None)
            else:
                os.environ['MATRIX_IMPORT_BACKUP_KEEP'] = old_keep

    def test_admin_fetish_log_rows_paginates(self):
        headers = self._admin_headers()
        res = self.client.get('/api/admin/fetish_log_rows?page=1&per_page=10&sort=guessed&order=desc', headers=headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertLessEqual(len(data['rows']), 10)
        self.assertIn('total', data)
        self.assertIn('pages', data)

    def test_admin_low_exposure_fetishes_returns_analysis_summary(self):
        from app import engine as app_engine

        headers = self._admin_headers()
        with patch.object(
            app_engine,
            'get_fetish_log',
            return_value={
                0: {'guessed': 0, 'correct': 0, 'wrong': 0},
                1: {'guessed': 2, 'correct': 1, 'wrong': 0},
                2: {'guessed': 10, 'correct': 3, 'wrong': 1},
            },
        ):
            res = self.client.get('/api/admin/low_exposure_fetishes?threshold=3&limit=20', headers=headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['status'], 'ok')
        self.assertEqual(data['threshold'], 3)
        self.assertGreaterEqual(data['zero_count'], 1)
        self.assertGreaterEqual(data['low_count'], 2)
        self.assertIn('low_share', data['summary'])
        guessed_values = [row['guessed'] for row in data['rows']]
        self.assertEqual(guessed_values, sorted(guessed_values))
        self.assertIn('works_count', data['rows'][0])
        self.assertIn('detail_url', data['rows'][0])

    def test_admin_works_link_queue_endpoint(self):
        headers = self._admin_headers()
        res = self.client.get('/api/admin/works_link_queue', headers=headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['status'], 'ok')
        self.assertIn('missing_url', data['counts'])
        self.assertIn('fallback_search_url', data['counts'])
        self.assertIn('search_url', data['counts'])
        self.assertIn('missing_asin', data['counts'])
        self.assertIn('samples', data)

    def test_admin_works_seed_backfill_dry_run_and_apply(self):
        from app import engine as app_engine

        headers = self._admin_headers()
        idx = next(
            i
            for i, fetish in enumerate(app_engine.fetishes)
            if fetish['id'] < PLAYER_FETISH_BASE_ID and fetish.get('works')
        )
        original = [dict(work) for work in app_engine.fetishes[idx].get('works', [])]
        try:
            app_engine.fetishes[idx]['works'] = []
            res = self.client.get('/api/admin/works_seed_backfill?sample_limit=200', headers=headers)
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertEqual(data['status'], 'ok')
            self.assertEqual(data['mode'], 'dry_run')
            self.assertGreaterEqual(data['candidate_count'], 1)
            self.assertIn(app_engine.fetishes[idx]['id'], {row['id'] for row in data['candidates']})

            res = self.client.post('/api/admin/works_seed_backfill', headers=headers, json={})
            self.assertEqual(res.status_code, 400)
            self.assertEqual(res.get_json()['required_confirm_text'], 'BACKFILL_WORKS')

            res = self.client.post(
                '/api/admin/works_seed_backfill', headers=headers, json={'confirm_text': 'BACKFILL_WORKS'}
            )
            self.assertEqual(res.status_code, 200)
            applied = res.get_json()
            self.assertEqual(applied['status'], 'ok')
            self.assertEqual(applied['mode'], 'applied')
            self.assertGreaterEqual(applied['updated_count'], 1)
            self.assertTrue(app_engine.fetishes[idx].get('works'))
        finally:
            app_engine.fetishes[idx]['works'] = original

    def test_admin_performance_endpoint(self):
        headers = self._admin_headers()
        res = self.client.get('/api/admin/performance', headers=headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['status'], 'ok')
        self.assertTrue(data['measurements'])
        self.assertIn('ms', data['measurements'][0])

    def test_admin_csrf_enforced_when_enabled(self):
        app.config['ENFORCE_CSRF'] = True
        try:
            headers = self._admin_headers()
            res = self.client.post('/api/admin/cleanup_sessions', headers=headers)
            self.assertEqual(res.status_code, 403)
            admin = self.client.get('/admin', headers=headers)
            self.assertEqual(admin.status_code, 200)
            match = re.search(r'csrfToken: \"([^\"]+)\"', admin.data.decode('utf-8'))
            self.assertIsNotNone(match)
            headers = {**headers, 'X-CSRF-Token': match.group(1)}
            res = self.client.post('/api/admin/cleanup_sessions', headers=headers)
            self.assertEqual(res.status_code, 200)
        finally:
            app.config.pop('ENFORCE_CSRF', None)

    def test_rate_limit_enforced_when_enabled(self):
        import app as app_module

        app.config['ENFORCE_RATE_LIMIT'] = True
        app.config['RATE_LIMIT_OVERRIDES'] = {'api_start': (2, 60)}
        app_module._RATE_LIMIT_BUCKETS.clear()
        try:
            self.assertEqual(self.client.post('/api/start').status_code, 200)
            self.assertEqual(self.client.post('/api/start').status_code, 200)
            limited = self.client.post('/api/start')
            self.assertEqual(limited.status_code, 429)
            self.assertIn('Retry-After', limited.headers)
            self.assertIn('retry_after', limited.get_json())
        finally:
            app.config.pop('ENFORCE_RATE_LIMIT', None)
            app.config.pop('RATE_LIMIT_OVERRIDES', None)
            app_module._RATE_LIMIT_BUCKETS.clear()

    def test_rate_limit_ignores_untrusted_x_forwarded_for(self):
        import app as app_module

        app.config['ENFORCE_RATE_LIMIT'] = True
        app.config['RATE_LIMIT_OVERRIDES'] = {'api_start': (2, 60)}
        app.config.pop('TRUSTED_PROXY_IPS', None)
        app_module._RATE_LIMIT_BUCKETS.clear()
        try:
            for i in range(2):
                res = self.client.post(
                    '/api/start',
                    headers={'X-Forwarded-For': f'203.0.113.{i}'},
                    environ_base={'REMOTE_ADDR': '198.51.100.10'},
                )
                self.assertEqual(res.status_code, 200)
            limited = self.client.post(
                '/api/start', headers={'X-Forwarded-For': '203.0.113.99'}, environ_base={'REMOTE_ADDR': '198.51.100.10'}
            )
            self.assertEqual(limited.status_code, 429)
        finally:
            app.config.pop('ENFORCE_RATE_LIMIT', None)
            app.config.pop('RATE_LIMIT_OVERRIDES', None)
            app_module._RATE_LIMIT_BUCKETS.clear()

    def test_rate_limit_can_use_environment_settings(self):
        import app as app_module

        app.config['ENFORCE_RATE_LIMIT'] = True
        old_limit = os.environ.get('RATE_LIMIT_API_START_LIMIT')
        old_window = os.environ.get('RATE_LIMIT_API_START_WINDOW')
        app_module._RATE_LIMIT_BUCKETS.clear()
        try:
            os.environ['RATE_LIMIT_API_START_LIMIT'] = '1'
            os.environ['RATE_LIMIT_API_START_WINDOW'] = '60'
            self.assertEqual(self.client.post('/api/start').status_code, 200)
            limited = self.client.post('/api/start')
            self.assertEqual(limited.status_code, 429)
            self.assertGreaterEqual(limited.get_json()['retry_after'], 1)
        finally:
            app.config.pop('ENFORCE_RATE_LIMIT', None)
            app_module._RATE_LIMIT_BUCKETS.clear()
            if old_limit is None:
                os.environ.pop('RATE_LIMIT_API_START_LIMIT', None)
            else:
                os.environ['RATE_LIMIT_API_START_LIMIT'] = old_limit
            if old_window is None:
                os.environ.pop('RATE_LIMIT_API_START_WINDOW', None)
            else:
                os.environ['RATE_LIMIT_API_START_WINDOW'] = old_window

    def test_admin_csrf_token_expires_when_enabled(self):
        app.config['ENFORCE_CSRF'] = True
        old_ttl = os.environ.get('ADMIN_CSRF_TTL_SECONDS')
        try:
            os.environ['ADMIN_CSRF_TTL_SECONDS'] = '1'
            headers = self._admin_headers()
            admin = self.client.get('/admin', headers=headers)
            self.assertEqual(admin.status_code, 200)
            match = re.search(r'csrfToken: \"([^\"]+)\"', admin.data.decode('utf-8'))
            self.assertIsNotNone(match)
            with self.client.session_transaction() as sess:
                sess['admin_csrf_issued_at'] = 0
            res = self.client.post('/api/admin/cleanup_sessions', headers={**headers, 'X-CSRF-Token': match.group(1)})
            self.assertEqual(res.status_code, 403)
        finally:
            app.config.pop('ENFORCE_CSRF', None)
            if old_ttl is None:
                os.environ.pop('ADMIN_CSRF_TTL_SECONDS', None)
            else:
                os.environ['ADMIN_CSRF_TTL_SECONDS'] = old_ttl
