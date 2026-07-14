# ruff: noqa: F403, F405

from tests._app_test_support import *


class TestGameSecurityAndErrors(APITestCase):
    def test_answer_invalid_value(self):
        start = self._start()
        res = self.client.post('/api/answer', json={'question_id': start['question_id'], 'answer': 999})
        self.assertEqual(res.status_code, 400)

    def test_answer_missing_fields(self):
        res = self.client.post('/api/answer', json={'question_id': 0})
        self.assertEqual(res.status_code, 400)

    def test_answer_invalid_question_id(self):
        res = self.client.post('/api/answer', json={'question_id': 99999, 'answer': 1.0})
        self.assertEqual(res.status_code, 400)

    def test_confirm_missing_fields(self):
        res = self.client.post('/api/confirm', json={'correct': True})
        self.assertEqual(res.status_code, 400)

    def test_confirm_invalid_fetish_id(self):
        res = self.client.post('/api/confirm', json={'correct': False, 'fetish_id': 99999})
        self.assertEqual(res.status_code, 400)

    def test_teach_invalid_fetish_id(self):
        res = self.client.post('/api/teach', json={'fetish_id': 99999})
        self.assertEqual(res.status_code, 400)

    def test_add_fetish_empty_name(self):
        res = self.client.post('/api/add_fetish', json={'name': ''})
        self.assertEqual(res.status_code, 400)

    def test_add_fetish_name_too_long(self):
        res = self.client.post('/api/add_fetish', json={'name': 'a' * 101})
        self.assertEqual(res.status_code, 400)

    def test_delete_seed_fetish_rejected_even_for_admin(self):
        headers = self._admin_headers()
        res = self.client.delete('/api/fetish/0', json={'confirm_text': 'DELETE'}, headers=headers)
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.get_json()['status'], 'error')

    def test_test_play_route_requires_admin(self):
        res = self.client.post('/admin/test_play/start')
        self.assertEqual(res.status_code, 401)
        stop = self.client.post('/admin/test_play/stop')
        self.assertEqual(stop.status_code, 401)
        with self.client.session_transaction() as sess:
            self.assertFalse(test_play_service.is_learning_disabled(sess))

    def test_finalize_added_invalid_id_rejected(self):
        res = self.client.post('/api/finalize_added', json={'items': [{'id': 2, 'is_new': False}]})
        self.assertEqual(res.status_code, 409)

    def test_finalize_added_limits_items(self):
        items = [{'id': 0, 'is_new': False} for _ in range(11)]
        res = self.client.post('/api/finalize_added', json={'items': items})
        self.assertEqual(res.status_code, 400)

    def test_ads_txt_reflects_env_client(self):
        import app as app_module

        original_client = app_module.BOOTSTRAP.adsense_client
        try:
            app_module.BOOTSTRAP.adsense_client = 'ca-pub-test-ads'
            res = self.client.get('/ads.txt')
        finally:
            app_module.BOOTSTRAP.adsense_client = original_client
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.mimetype, 'text/plain')
        self.assertIn(b'google.com, pub-test-ads, DIRECT, f08c47fec0942fa0', res.data)

    def test_answer_without_start_returns_440(self):
        """セッション未開始で answer を呼ぶと 440 が返ること。"""
        fresh = app.test_client()  # 新しいクライアント（セッションなし）
        res = fresh.post('/api/answer', json={'question_id': 0, 'answer': 1.0})
        self.assertEqual(res.status_code, 440)

    def test_back_without_start_returns_440(self):
        fresh = app.test_client()
        res = fresh.post('/api/back')
        self.assertEqual(res.status_code, 440)

    def test_learning_endpoints_without_start_return_440(self):
        fresh = app.test_client()
        cases = [
            ('/api/confirm', {'correct': True, 'fetish_id': 0}),
            ('/api/teach', {'fetish_id': 0}),
            ('/api/add_fetish', {'name': '未開始テスト', 'confirmed': True}),
            ('/api/finalize_added', {'items': []}),
        ]
        for url, payload in cases:
            with self.subTest(url=url):
                res = fresh.post(url, json=payload)
                self.assertEqual(res.status_code, 440)

    def test_answer_rejects_non_current_question_id(self):
        start = self._start()
        current = start['question_id']
        other = 0 if current != 0 else 1
        res = self.client.post('/api/answer', json={'question_id': other, 'answer': 1.0})
        self.assertEqual(res.status_code, 409)

    def test_disabled_question_not_asked(self):
        """無効化した質問が asked リストに含まれないこと。"""
        from app import engine as app_engine

        # Q0 を無効化
        app_engine.disabled_questions.add(0)
        try:
            start = self._start()
            q = start['question_id']
            asked = [q]
            for _ in range(10):
                res = self.client.post('/api/answer', json={'question_id': q, 'answer': 1.0})
                d = res.get_json()
                if d.get('action') == 'guess':
                    break
                q = d.get('question_id', q)
                asked.append(q)
            self.assertNotIn(0, asked)
        finally:
            app_engine.disabled_questions.discard(0)

    def test_health_endpoint(self):
        res = self.client.get('/health')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers['X-Content-Type-Options'], 'nosniff')
        self.assertIn('Content-Security-Policy', res.headers)
        self.assertIn('https://pagead2.googlesyndication.com', res.headers['Content-Security-Policy'])
        data = res.get_json()
        self.assertEqual(data['status'], 'ok')
        self.assertIn('fetishes', data)
        self.assertIn('questions', data)
        self.assertIn('matrix', data)
        self.assertIn('runtime', data)
        self.assertIn('persistence', data)
        self.assertTrue(data['matrix']['ok'])
        self.assertIn('error_counts', data['runtime'])
        self.assertIn('matrix_saved_mtime', data['persistence'])
        self.assertGreater(data['fetishes'], 0)
        self.assertGreater(data['questions'], 0)

    def test_health_ignores_invalid_threshold_env(self):
        old_threshold = os.environ.get('HEALTH_5XX_DEGRADED_THRESHOLD')
        try:
            os.environ['HEALTH_5XX_DEGRADED_THRESHOLD'] = 'bad'
            res = self.client.get('/health')
            self.assertEqual(res.status_code, 200)
            self.assertIn('status', res.get_json())
        finally:
            if old_threshold is None:
                os.environ.pop('HEALTH_5XX_DEGRADED_THRESHOLD', None)
            else:
                os.environ['HEALTH_5XX_DEGRADED_THRESHOLD'] = old_threshold

    def test_health_degrades_on_5xx_threshold(self):
        import app as app_module

        old_counts = dict(app_module._ERROR_COUNTS)
        old_threshold = os.environ.get('HEALTH_5XX_DEGRADED_THRESHOLD')
        try:
            app_module._ERROR_COUNTS['5xx'] = 1
            os.environ['HEALTH_5XX_DEGRADED_THRESHOLD'] = '1'
            res = self.client.get('/health')
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertEqual(data['status'], 'degraded')
            self.assertIn('5xx_threshold', data['degraded_reasons'])
        finally:
            app_module._ERROR_COUNTS.clear()
            app_module._ERROR_COUNTS.update(old_counts)
            if old_threshold is None:
                os.environ.pop('HEALTH_5XX_DEGRADED_THRESHOLD', None)
            else:
                os.environ['HEALTH_5XX_DEGRADED_THRESHOLD'] = old_threshold

    def test_funnel_metrics_marks_impossible_completion_rate_unavailable(self):
        from services.admin_helpers import build_completion_metrics

        metrics = build_completion_metrics(
            {'start_count': 10, 'completion_count': 12},
            [{'start': 5, 'completion': 7}],
            {},
        )
        self.assertIsNone(metrics['completion_rate'])
        self.assertFalse(metrics['completion_rate_reliable'])
        self.assertIn('参考不可', metrics['completion_rate_note'])
        self.assertIsNone(metrics['recent_7_days']['completion_rate'])
        self.assertFalse(metrics['recent_7_days']['completion_rate_reliable'])

    def test_funnel_metrics_default_is_lightweight(self):
        headers = self._admin_headers()
        res = self.client.get('/api/admin/funnel_metrics', headers=headers)

        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertFalse(data['details_included'])
        self.assertIn('completion', data)
        self.assertIn('stats_history', data)
        self.assertNotIn('share_metrics', data)
        self.assertNotIn('question_summary', data)

    def test_funnel_metrics_can_include_details_explicitly(self):
        headers = self._admin_headers()
        res = self.client.get('/api/admin/funnel_metrics?include_details=1', headers=headers)

        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data['details_included'])
        self.assertIn('share_metrics', data)
        self.assertIn('question_summary', data)

    def test_dropoff_rejects_invalid_question_id(self):
        from app import engine as app_engine

        with self.client.session_transaction() as sess:
            sess['started'] = True
            sess['completed'] = False
            sess['answers'] = {'1': 1.0}
            sess['dropoff_recorded'] = False
        with patch.object(app_engine, 'log_dropoff') as recorder:
            res = self.client.post('/api/dropoff', json={'question_id': 'not-a-number'})
            self.assertEqual(res.status_code, 400)
            self.assertEqual(res.get_json()['status'], 'error')
            recorder.assert_not_called()
