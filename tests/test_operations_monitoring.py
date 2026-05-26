import unittest
from unittest.mock import patch
from urllib.request import Request

from scripts import daily_analytics_report, ntfy_notifier, operations_check


class FakeResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return b'{}'


class OperationsMonitoringTests(unittest.TestCase):
    def test_ntfy_skips_when_topic_is_unset(self):
        result = ntfy_notifier.notify(
            'title',
            'message',
            environ={},
            opener=lambda request, timeout=10: self.fail('opener should not be called'),
        )
        self.assertFalse(result['sent'])
        self.assertTrue(result['skipped'])

    def test_ntfy_builds_topic_url_and_headers(self):
        calls = []

        def fake_open(request, timeout=10):
            calls.append((request, timeout))
            return FakeResponse()

        result = ntfy_notifier.notify(
            'Ops\nTitle',
            'hello',
            priority='high',
            tags='warning',
            environ={'NTFY_TOPIC': 'heki ops', 'NTFY_SERVER': 'https://ntfy.example.test/'},
            opener=fake_open,
        )

        self.assertTrue(result['sent'])
        request, timeout = calls[0]
        self.assertIsInstance(request, Request)
        self.assertEqual(request.full_url, 'https://ntfy.example.test/heki%20ops')
        self.assertEqual(request.headers['Title'], 'Ops Title')
        self.assertEqual(request.headers['Priority'], 'high')
        self.assertEqual(request.headers['Tags'], 'warning')

    def test_operations_report_flags_critical_and_warn_without_leaking_token(self):
        secret = 'read-token-should-not-appear'

        def fake_json(path):
            if path == '/health':
                return {
                    'status': 'ok',
                    'storage': 'local_json',
                    'matrix': {'ok': False},
                    'runtime': {'error_counts': {'5xx': 2}},
                }
            if path == '/api/admin/preflight':
                return {'checks': [{'name': 'matrix_shape', 'ok': False, 'detail': 'bad'}]}
            if path == '/api/admin/works_health':
                return {'maintenance': {'works_count': 10}}
            if path.startswith('/api/admin/recent_fetish_ranking'):
                return {'ranking': [{'fetish_name': '共依存', 'guessed': 80, 'total': 80}, {'fetish_name': '眼鏡', 'guessed': 20, 'total': 20}]}
            if path.startswith('/api/admin/question_events'):
                return {
                    'total': 20,
                    'metrics': {'relation_attachment_share': 70},
                    'questions': [{'question_id': 1, 'answered': 10, 'yes_rate': 95}],
                    'dropoff_ranking': [{'question_id': 2, 'shown': 10, 'dropoff_rate': 40}],
                }
            if path == '/api/admin/funnel_metrics':
                return {'completion': {'recent_7_days': {'completion_rate': 3}, 'completion_rate': 103}}
            if path.startswith('/api/admin/share_events'):
                return {'total': 5, 'metrics': {'result_page_views': 30, 'share_actions': 0}}
            raise AssertionError(path)

        report = operations_check.build_report(
            environ={'ADMIN_READ_TOKEN': secret, 'NTFY_WORKS_MIN_COUNT': '20'},
            json_getter=fake_json,
            bytes_getter=lambda path: b'not-png',
        )

        self.assertEqual(report['severity'], 'CRITICAL')
        self.assertIn('storage=local_json', report['message'])
        self.assertIn('heavy_result_ratio=80.0%', report['message'])
        self.assertNotIn(secret, report['message'])
        self.assertNotIn('ADMIN_READ_TOKEN', report['message'])

    def test_operations_report_warns_when_admin_token_missing(self):
        called = []

        def fake_json(path):
            called.append(path)
            if path.startswith('/api/admin/'):
                raise AssertionError('admin API should not be called without token')
            return {'status': 'ok', 'storage': 'postgres', 'matrix': {'ok': True}, 'runtime': {'error_counts': {'5xx': 0}}}

        report = operations_check.build_report(
            environ={},
            json_getter=fake_json,
            bytes_getter=lambda path: operations_check.PNG_SIGNATURE + b'abc',
        )

        self.assertEqual(report['severity'], 'WARN')
        self.assertEqual(called, ['/health'])
        self.assertIn('admin analytics checks skipped', report['message'])

    def test_operations_check_warn_exit_is_zero_even_when_ntfy_fails(self):
        with patch.object(operations_check, 'build_report', return_value={'severity': 'WARN', 'message': '[WARN] test'}), \
                patch.object(operations_check, 'notify', side_effect=RuntimeError('ntfy down')), \
                patch.dict(operations_check.os.environ, {'NTFY_TOPIC': 'topic'}, clear=True):
            self.assertEqual(operations_check.main([]), 0)

    def test_operations_check_critical_exit_is_nonzero_when_ntfy_fails(self):
        with patch.object(operations_check, 'build_report', return_value={'severity': 'CRITICAL', 'message': '[CRITICAL] test'}), \
                patch.object(operations_check, 'notify', side_effect=RuntimeError('ntfy down')), \
                patch.dict(operations_check.os.environ, {'NTFY_TOPIC': 'topic'}, clear=True):
            self.assertEqual(operations_check.main([]), 1)

    def test_daily_report_summarizes_safe_analytics(self):
        def fake_json(path):
            if path == '/api/admin/funnel_metrics':
                return {'stats_history': [{'date': '2026-05-26', 'start': 100, 'completion': 20, 'correct': 7, 'wrong': 3}]}
            if path.startswith('/api/admin/recent_fetish_ranking'):
                return {'ranking': [{'fetish_name': '共依存', 'guessed': 40, 'total': 40}, {'fetish_name': '眼鏡', 'guessed': 60, 'total': 60}]}
            if path.startswith('/api/admin/share_events'):
                return {'total': 12, 'metrics': {'result_page_views': 50, 'share_actions': 5}}
            if path.startswith('/api/admin/question_events'):
                return {
                    'total': 30,
                    'dropoff_ranking': [{'question_id': 3, 'question_text': '少人数の方が楽？', 'shown': 10, 'dropoff_rate': 20}],
                    'questions': [{'question_id': 4, 'question_text': '整った静かな雰囲気？', 'answered': 10, 'yes_rate': 92}],
                }
            raise AssertionError(path)

        report = daily_analytics_report.build_daily_report(
            environ={'ADMIN_READ_TOKEN': 'token', 'HEKI_REPORT_DATE': '2026-05-26'},
            json_getter=fake_json,
        )

        self.assertEqual(report['status'], 'ok')
        self.assertIn('plays: 100', report['message'])
        self.assertIn('completion_rate: 20.0%', report['message'])
        self.assertIn('共依存 40', report['message'])
        self.assertNotIn('unknown 40', report['message'])
        self.assertIn('heavy_result_ratio: 40.0%', report['message'])
        self.assertIn('share_rate: 10.0%', report['message'])
        self.assertNotIn('token', report['message'])

    def test_daily_report_uses_jst_yesterday_and_latest_active_stats(self):
        stats = daily_analytics_report._previous_day_stats({
            'stats_history': [
                {'date': '2026-05-25', 'start': 0, 'completion': 0},
                {'date': '2026-05-26', 'start': 50, 'completion': 25},
            ]
        }, '2026-05-24')

        self.assertEqual(stats['date'], '2026-05-26')
        self.assertEqual(stats['plays'], 50)
        self.assertEqual(stats['completion_rate'], 50.0)

    def test_operations_completion_rate_prefers_recent_bucket_and_clamps(self):
        self.assertEqual(
            operations_check._latest_completion_rate({'completion': {'recent_7_days': {'completion_rate': 42}, 'completion_rate': 101.8}}),
            42.0,
        )
        self.assertEqual(
            operations_check._latest_completion_rate({'completion': {'completion_rate': 101.8}}),
            100.0,
        )


if __name__ == '__main__':
    unittest.main()
