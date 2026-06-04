import unittest
from unittest.mock import patch
from urllib.error import HTTPError
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

    def test_ntfy_blocks_local_topic_by_default(self):
        result = ntfy_notifier.notify(
            'title',
            'message',
            environ={'NTFY_TOPIC': 'shared-ops-topic'},
            opener=lambda request, timeout=10: self.fail('local opener should not be called'),
        )

        self.assertFalse(result['sent'])
        self.assertTrue(result['skipped'])
        self.assertIn('local ntfy send blocked', result['reason'])

    def test_ntfy_builds_topic_url_and_headers_when_actions_enabled(self):
        calls = []

        def fake_open(request, timeout=10):
            calls.append((request, timeout))
            return FakeResponse()

        result = ntfy_notifier.notify(
            'Ops\nTitle',
            'hello',
            priority='high',
            tags='warning',
            environ={'NTFY_TOPIC': 'heki ops', 'NTFY_SERVER': 'https://ntfy.example.test/', 'GITHUB_ACTIONS': 'true'},
            opener=fake_open,
        )

        self.assertTrue(result['sent'])
        request, timeout = calls[0]
        self.assertIsInstance(request, Request)
        self.assertEqual(request.full_url, 'https://ntfy.example.test/heki%20ops')
        self.assertEqual(request.headers['Title'], 'Ops Title')
        self.assertEqual(request.headers['Priority'], 'high')
        self.assertEqual(request.headers['Tags'], 'warning')

    def test_operations_admin_getter_retries_admin_reads(self):
        calls = []

        def fake_fetch(path, *, environ=None, timeout=15):
            calls.append((path, timeout))
            if len(calls) == 1:
                raise TimeoutError('temporary')
            return {'status': 'ok'}

        with patch.object(operations_check, 'fetch_json', fake_fetch):
            getter = operations_check.report_json_getter({
                'ADMIN_READ_TOKEN': 'token',
                'NTFY_ADMIN_RETRIES': '2',
                'NTFY_ADMIN_TIMEOUT_SECONDS': '7',
            })
            self.assertEqual(getter('/api/admin/preflight'), {'status': 'ok'})

        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0], ('/api/admin/preflight', 7))

    def test_daily_report_admin_getter_retries_admin_reads(self):
        calls = []

        def fake_fetch(path, *, environ=None, timeout=15):
            calls.append((path, timeout))
            if len(calls) == 1:
                raise TimeoutError('temporary')
            return {'status': 'ok'}

        with patch.object(daily_analytics_report, 'fetch_json', fake_fetch):
            getter = daily_analytics_report.report_json_getter({
                'ADMIN_READ_TOKEN': 'token',
                'NTFY_ADMIN_RETRIES': '2',
                'NTFY_ADMIN_TIMEOUT_SECONDS': '8',
            })
            self.assertEqual(getter('/api/admin/funnel_metrics'), {'status': 'ok'})

        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0], ('/api/admin/funnel_metrics', 8))

    def test_operations_report_flags_critical_and_warn_without_leaking_token(self):
        secret = 'read-token-should-not-appear'

        def fake_json(path):
            if path == '/health':
                return {
                    'status': 'ok',
                    'storage': 'local_json',
                    'matrix': {'ok': False},
                    'runtime': {'error_counts': {'5xx': 3}},
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
                    'questions': [{'question_id': 1, 'answered': 10, 'shown': 12, 'yes_rate': 95, 'category': 'tone'}],
                    'dropoff_ranking': [{'question_id': 2, 'shown': 10, 'dropoff_rate': 40}],
                }
            if path == '/api/admin/funnel_metrics':
                return {'completion': {'recent_7_days': {'starts': 30, 'completions': 1, 'completion_rate': 3}, 'completion_rate': 103}}
            if path.startswith('/api/admin/share_events'):
                return {'total': 5, 'metrics': {'result_page_views': 30, 'share_actions': 0}}
            raise AssertionError(path)

        report = operations_check.build_report(
            environ={'ADMIN_READ_TOKEN': secret, 'NTFY_WORKS_MIN_COUNT': '20', 'NTFY_QUESTION_MIN_ANSWERS': '5'},
            json_getter=fake_json,
            bytes_getter=lambda path: b'not-png',
        )

        self.assertEqual(report['severity'], 'CRITICAL')
        self.assertIn('storage=local_json', report['message'])
        self.assertIn('heavy_result_ratio=unavailable (stats_history_fallback)', report['message'])
        self.assertIn('Q1 95.0% (10/12, tone)', report['message'])
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
                patch.dict(operations_check.os.environ, {'NTFY_TOPIC': 'topic', 'GITHUB_ACTIONS': 'true'}, clear=True):
            self.assertEqual(operations_check.main([]), 0)

    def test_operations_check_critical_exit_is_nonzero_when_ntfy_fails(self):
        with patch.object(operations_check, 'build_report', return_value={'severity': 'CRITICAL', 'message': '[CRITICAL] test'}), \
                patch.object(operations_check, 'notify', side_effect=RuntimeError('ntfy down')), \
                patch.dict(operations_check.os.environ, {'NTFY_TOPIC': 'topic', 'GITHUB_ACTIONS': 'true'}, clear=True):
            self.assertEqual(operations_check.main([]), 1)



    def test_works_count_accepts_actual_works_health_shape(self):
        works_health = {
            'status': 'ok',
            'maintenance': {
                'total_works': 42,
                'missing_work_fetish_count': 0,
                'missing_url_work_count': 0,
                'unsafe_url_work_count': 0,
            },
            'link_queue': {'count': 0, 'samples': []},
            'seed_backfill': {'candidate_count': 0, 'candidates': []},
        }

        self.assertEqual(operations_check._works_count(works_health), 42)

    def test_works_count_keeps_legacy_fallbacks(self):
        self.assertEqual(operations_check._works_count({'maintenance': {'works_count': 7}}), 7)
        self.assertEqual(operations_check._works_count({'seed_backfill': {'works_count': 8}}), 8)

    def test_operations_report_demotes_public_timeout_critical_when_metrics_exist(self):
        critical = ['/health failed: TimeoutError', 'OGP PNG failure: TimeoutError', 'matrix shape mismatch']
        warn = []
        remaining = operations_check._demote_public_timeout_criticals(
            critical,
            warn,
            admin_signal_available=False,
            daily=['heavy_result_ratio=77.8%', 'question_events=39'],
        )

        self.assertEqual(remaining, ['matrix shape mismatch'])
        self.assertIn('/health failed: TimeoutError (admin metrics reachable; downgraded from CRITICAL)', warn)
        self.assertIn('OGP PNG failure: TimeoutError (admin metrics reachable; downgraded from CRITICAL)', warn)


    def test_heavy_ratio_warning_is_suppressed_when_samples_are_small(self):
        def fake_json(path):
            if path == '/health':
                return {'status': 'ok', 'storage': 'postgres', 'matrix': {'ok': True}, 'runtime': {'error_counts': {'5xx': 0}}}
            if path == '/api/admin/preflight':
                return {'checks': []}
            if path == '/api/admin/works_health':
                return {'maintenance': {'works_count': 100}}
            if path.startswith('/api/admin/result_exposures'):
                return {
                    'source': 'result_exposures',
                    'ranking': [
                        {'fetish_name': '共依存', 'guessed': 3, 'total': 3},
                        {'fetish_name': '激重感情', 'guessed': 2, 'total': 2},
                    ],
                }
            if path.startswith('/api/admin/question_events'):
                return {'total': 1, 'metrics': {}, 'questions': [], 'dropoff_ranking': []}
            if path == '/api/admin/funnel_metrics':
                return {'completion': {'recent_7_days': {'starts': 30, 'completions': 15, 'completion_rate': 50}}}
            if path.startswith('/api/admin/share_events'):
                return {'total': 0, 'metrics': {'result_page_views': 0, 'share_actions': 0}}
            raise AssertionError(path)

        report = operations_check.build_report(
            environ={'ADMIN_READ_TOKEN': 'token', 'NTFY_HEAVY_RESULT_MIN_SAMPLES': '10'},
            json_getter=fake_json,
            bytes_getter=lambda path: operations_check.PNG_SIGNATURE + b'abc',
        )

        self.assertNotIn('heavy_result_ratio=100.0% TOP:', report['message'])
        self.assertIn('heavy_result_ratio=100.0%', report['message'])
        # sample不足時は警告にしない（metrics は残す）


    def test_completion_reference_warning_is_suppressed_with_small_starts(self):
        def fake_json(path):
            if path == '/health':
                return {'status': 'ok', 'storage': 'postgres', 'matrix': {'ok': True}, 'runtime': {'error_counts': {'5xx': 0}}}
            if path == '/api/admin/preflight':
                return {'checks': []}
            if path == '/api/admin/works_health':
                return {'maintenance': {'works_count': 100}}
            if path.startswith('/api/admin/recent_fetish_ranking'):
                return {'ranking': []}
            if path.startswith('/api/admin/question_events'):
                return {'total': 1, 'metrics': {}, 'questions': [], 'dropoff_ranking': []}
            if path == '/api/admin/funnel_metrics':
                return {'completion': {'recent_7_days': {'starts': 4, 'completions': 2, 'completion_rate': 50}}}
            if path.startswith('/api/admin/share_events'):
                return {'total': 0, 'metrics': {'result_page_views': 0, 'share_actions': 0}}
            raise AssertionError(path)

        report = operations_check.build_report(
            environ={'ADMIN_READ_TOKEN': 'token', 'NTFY_COMPLETION_WARN_MIN_STARTS': '10'},
            json_getter=fake_json,
            bytes_getter=lambda path: operations_check.PNG_SIGNATURE + b'abc',
        )

        self.assertIn('completion_rate=50.0% (参考値) (2/4)', report['message'])
        self.assertEqual(report['message'].count('completion_rate=50.0% (参考値) (2/4)'), 1)


    def test_operations_report_rechecks_public_endpoints_after_admin_warmup(self):
        attempts = {'health': 0, 'png': 0}

        def fake_json(path):
            if path == '/health':
                attempts['health'] += 1
                if attempts['health'] <= 2:
                    raise TimeoutError()
                return {'status': 'ok', 'storage': 'postgres', 'matrix': {'ok': True}, 'runtime': {'error_counts': {'5xx': 0}}}
            if path == '/api/admin/preflight':
                return {'checks': []}
            if path == '/api/admin/works_health':
                return {'maintenance': {'works_count': 100}}
            if path.startswith('/api/admin/recent_fetish_ranking'):
                return {'ranking': [{'fetish_name': '眼鏡', 'guessed': 10, 'total': 10}]}
            if path.startswith('/api/admin/question_events'):
                return {'total': 10, 'metrics': {}, 'questions': [], 'dropoff_ranking': []}
            if path == '/api/admin/funnel_metrics':
                return {'completion': {'recent_7_days': {'starts': 30, 'completions': 15, 'completion_rate': 50}}}
            if path.startswith('/api/admin/share_events'):
                return {'total': 2, 'metrics': {'result_page_views': 10, 'share_actions': 1}}
            raise AssertionError(path)

        def fake_bytes(path):
            attempts['png'] += 1
            if attempts['png'] <= 2:
                raise TimeoutError()
            return operations_check.PNG_SIGNATURE + b'abc'

        report = operations_check.build_report(
            environ={'ADMIN_READ_TOKEN': 'token'},
            json_getter=fake_json,
            bytes_getter=fake_bytes,
        )

        self.assertNotIn('/health failed', report['message'])
        self.assertNotIn('OGP PNG failure', report['message'])
        self.assertEqual(attempts, {'health': 3, 'png': 3})

    def test_operations_report_treats_public_timeout_as_warn_when_admin_is_reachable(self):
        class TimeoutErrorForTest(TimeoutError):
            pass

        calls = []

        def fake_json(path):
            calls.append(path)
            if path == '/health':
                raise TimeoutErrorForTest()
            if path == '/api/admin/preflight':
                return {'checks': []}
            if path == '/api/admin/works_health':
                return {'maintenance': {'works_count': 100}}
            if path.startswith('/api/admin/recent_fetish_ranking'):
                return {'ranking': [{'fetish_name': '眼鏡', 'guessed': 10, 'total': 10}]}
            if path.startswith('/api/admin/question_events'):
                return {'total': 10, 'metrics': {}, 'questions': [], 'dropoff_ranking': []}
            if path == '/api/admin/funnel_metrics':
                return {'completion': {'recent_7_days': {'starts': 30, 'completions': 15, 'completion_rate': 50}}}
            if path.startswith('/api/admin/share_events'):
                return {'total': 2, 'metrics': {'result_page_views': 10, 'share_actions': 1}}
            raise AssertionError(path)

        report = operations_check.build_report(
            environ={'ADMIN_READ_TOKEN': 'token'},
            json_getter=fake_json,
            bytes_getter=lambda path: (_ for _ in ()).throw(TimeoutErrorForTest()),
        )

        self.assertEqual(report['severity'], 'WARN')
        self.assertIn('/health failed: TimeoutErrorForTest', report['message'])
        self.assertIn('OGP PNG failure: TimeoutErrorForTest', report['message'])
        self.assertIn('treated as transient', report['message'])

    def test_operations_report_retries_public_checks(self):
        attempts = {'health': 0, 'png': 0}

        def fake_json(path):
            if path == '/health':
                attempts['health'] += 1
                if attempts['health'] == 1:
                    raise TimeoutError()
                return {'status': 'ok', 'storage': 'postgres', 'matrix': {'ok': True}, 'runtime': {'error_counts': {'5xx': 0}}}
            if path == '/api/admin/preflight':
                return {'checks': []}
            if path == '/api/admin/works_health':
                return {'maintenance': {'works_count': 100}}
            if path.startswith('/api/admin/recent_fetish_ranking'):
                return {'ranking': []}
            if path.startswith('/api/admin/question_events'):
                return {'total': 1, 'metrics': {}, 'questions': [], 'dropoff_ranking': []}
            if path == '/api/admin/funnel_metrics':
                return {'completion': {'recent_7_days': {'starts': 30, 'completions': 15, 'completion_rate': 50}}}
            if path.startswith('/api/admin/share_events'):
                return {'total': 1, 'metrics': {'result_page_views': 10, 'share_actions': 1}}
            raise AssertionError(path)

        def fake_bytes(path):
            attempts['png'] += 1
            if attempts['png'] == 1:
                raise TimeoutError()
            return operations_check.PNG_SIGNATURE + b'abc'

        report = operations_check.build_report(
            environ={'ADMIN_READ_TOKEN': 'token'},
            json_getter=fake_json,
            bytes_getter=fake_bytes,
        )

        self.assertNotIn('/health failed', report['message'])
        self.assertNotIn('OGP PNG failure', report['message'])
        self.assertEqual(attempts, {'health': 2, 'png': 2})

    def test_operations_report_falls_back_when_share_days_query_fails(self):
        calls = []

        def fake_json(path):
            calls.append(path)
            if path == '/health':
                return {'status': 'ok', 'storage': 'postgres', 'matrix': {'ok': True}, 'runtime': {'error_counts': {'5xx': 0}}}
            if path == '/api/admin/preflight':
                return {'checks': []}
            if path == '/api/admin/works_health':
                return {'maintenance': {'works_count': 100}}
            if path.startswith('/api/admin/recent_fetish_ranking'):
                return {'ranking': [{'fetish_name': '眼鏡', 'guessed': 10, 'total': 10}]}
            if path.startswith('/api/admin/question_events'):
                return {'total': 0, 'metrics': {}, 'questions': [], 'dropoff_ranking': []}
            if path == '/api/admin/funnel_metrics':
                return {'completion': {'recent_7_days': {'starts': 30, 'completions': 15, 'completion_rate': 50}}}
            if path == '/api/admin/share_events?days=7&limit=5000':
                raise HTTPError(path, 500, 'server error', hdrs=None, fp=None)
            if path == '/api/admin/share_events?limit=5000':
                return {'total': 0, 'metrics': {'result_page_views': 0, 'share_actions': 0}}
            raise AssertionError(path)

        report = operations_check.build_report(
            environ={'ADMIN_READ_TOKEN': 'token'},
            json_getter=fake_json,
            bytes_getter=lambda path: operations_check.PNG_SIGNATURE + b'abc',
        )

        self.assertEqual(report['severity'], 'WARN')
        self.assertIn('/api/admin/share_events?limit=5000', calls)
        self.assertIn('question_events=0', report['message'])
        self.assertIn('share_events=0', report['message'])
        self.assertNotIn('share analytics unavailable', report['message'])

    def test_operations_report_includes_http_status_when_share_fallback_fails(self):
        def fake_json(path):
            if path == '/health':
                return {'status': 'ok', 'storage': 'postgres', 'matrix': {'ok': True}, 'runtime': {'error_counts': {'5xx': 0}}}
            if path == '/api/admin/preflight':
                return {'checks': []}
            if path == '/api/admin/works_health':
                return {'maintenance': {'works_count': 100}}
            if path.startswith('/api/admin/recent_fetish_ranking'):
                return {'ranking': []}
            if path.startswith('/api/admin/question_events'):
                return {'total': 1, 'metrics': {}, 'questions': [], 'dropoff_ranking': []}
            if path == '/api/admin/funnel_metrics':
                return {'completion': {'recent_7_days': {'starts': 30, 'completions': 15, 'completion_rate': 50}}}
            if path.startswith('/api/admin/share_events'):
                raise HTTPError(path, 403, 'forbidden', hdrs=None, fp=None)
            raise AssertionError(path)

        report = operations_check.build_report(
            environ={'ADMIN_READ_TOKEN': 'token'},
            json_getter=fake_json,
            bytes_getter=lambda path: operations_check.PNG_SIGNATURE + b'abc',
        )

        self.assertIn('share analytics unavailable: HTTP 403', report['message'])


    def test_operations_report_does_not_warn_heavy_ratio_from_stats_history_fallback(self):
        def fake_json(path):
            if path == '/health':
                return {'status': 'ok', 'storage': 'postgres', 'matrix': {'ok': True}, 'runtime': {'error_counts': {'5xx': 0}}}
            if path == '/api/admin/preflight':
                return {'checks': []}
            if path == '/api/admin/works_health':
                return {'maintenance': {'works_count': 100}}
            if path.startswith('/api/admin/result_exposures'):
                return {'source': 'result_exposures', 'ranking': []}
            if path.startswith('/api/admin/recent_fetish_ranking'):
                return {'ranking': [{'fetish_name': '共依存', 'guessed': 90, 'total': 90}, {'fetish_name': '白衣', 'guessed': 10, 'total': 10}]}
            if path.startswith('/api/admin/question_events'):
                return {'total': 1, 'metrics': {}, 'questions': [], 'dropoff_ranking': []}
            if path == '/api/admin/funnel_metrics':
                return {'completion': {'recent_7_days': {'starts': 30, 'completions': 15, 'completion_rate': 50}}}
            if path.startswith('/api/admin/share_events'):
                return {'total': 1, 'metrics': {'result_page_views': 1, 'share_actions': 0}}
            raise AssertionError(path)

        report = operations_check.build_report(
            environ={'ADMIN_READ_TOKEN': 'token'},
            json_getter=fake_json,
            bytes_getter=lambda path: operations_check.PNG_SIGNATURE + b'abc',
        )

        self.assertIn('heavy_result_ratio=unavailable (stats_history_fallback)', report['message'])
        self.assertIn('result_source=stats_history_fallback', report['message'])
        self.assertNotIn('heavy_result_ratio=90.0% TOP:', report['message'])


    def test_operations_report_uses_result_exposure_ranking_before_stats_history(self):
        calls = []

        def fake_json(path):
            calls.append(path)
            if path == '/health':
                return {'status': 'ok', 'storage': 'postgres', 'matrix': {'ok': True}, 'runtime': {'error_counts': {'5xx': 0}}}
            if path == '/api/admin/preflight':
                return {'checks': []}
            if path == '/api/admin/works_health':
                return {'maintenance': {'works_count': 100}}
            if path.startswith('/api/admin/result_exposures'):
                return {'source': 'result_exposures', 'ranking': [{'fetish_name': '白衣', 'count': 9, 'total': 9}]}
            if path.startswith('/api/admin/recent_fetish_ranking'):
                raise AssertionError('stats ranking should not be used when exposures exist')
            if path.startswith('/api/admin/question_events'):
                return {'total': 1, 'metrics': {}, 'questions': [], 'dropoff_ranking': []}
            if path == '/api/admin/funnel_metrics':
                return {'completion': {'recent_7_days': {'starts': 30, 'completions': 15, 'completion_rate': 50}}}
            if path.startswith('/api/admin/share_events'):
                return {'total': 1, 'metrics': {'result_page_views': 1, 'share_actions': 0}}
            raise AssertionError(path)

        report = operations_check.build_report(
            environ={'ADMIN_READ_TOKEN': 'token'},
            json_getter=fake_json,
            bytes_getter=lambda path: operations_check.PNG_SIGNATURE + b'abc',
        )

        self.assertIn('/api/admin/result_exposures?days=7&top_n=20', calls)
        self.assertIn('result_source=result_exposures', report['message'])
        self.assertIn('heavy_result_ratio=0.0%', report['message'])

    def test_daily_report_uses_result_exposure_ranking_before_stats_history(self):
        calls = []

        def fake_json(path):
            calls.append(path)
            if path == '/api/admin/funnel_metrics':
                return {'stats_history': [{'date': '2026-05-26', 'start': 100, 'completion': 80}]}
            if path.startswith('/api/admin/result_exposures'):
                self.assertIn('date=2026-05-26', path)
                return {'source': 'result_exposures', 'ranking': [{'fetish_name': '白衣', 'count': 8, 'total': 8}]}
            if path.startswith('/api/admin/recent_fetish_ranking'):
                raise AssertionError('stats ranking should not be used when exposures exist')
            if path.startswith('/api/admin/share_events'):
                return {'total': 2, 'metrics': {'result_page_views': 10, 'share_actions': 1}}
            if path.startswith('/api/admin/question_events'):
                return {'total': 3, 'dropoff_ranking': [], 'questions': []}
            raise AssertionError(path)

        report = daily_analytics_report.build_daily_report(
            environ={'ADMIN_READ_TOKEN': 'token', 'HEKI_REPORT_DATE': '2026-05-26'},
            json_getter=fake_json,
        )

        self.assertIn('result_source: result_exposures', report['message'])
        self.assertIn('heavy_result_ratio: 0.0% (参考値) (0/8)', report['message'])
        self.assertIn('白衣 8', report['message'])
        self.assertIn('/api/admin/result_exposures?days=1&date=2026-05-26&top_n=10', calls)

    def test_daily_report_summarizes_safe_analytics(self):
        def fake_json(path):
            if path == '/api/admin/funnel_metrics':
                return {'stats_history': [{'date': '2026-05-26', 'start': 100, 'completion': 20, 'correct': 7, 'wrong': 3}]}
            if path.startswith('/api/admin/recent_fetish_ranking'):
                self.assertIn('date=2026-05-26', path)
                return {'ranking': [{'fetish_name': '共依存', 'guessed': 40, 'total': 40}, {'fetish_name': '眼鏡', 'guessed': 60, 'total': 60}]}
            if path.startswith('/api/admin/share_events'):
                return {'total': 12, 'metrics': {'result_page_views': 50, 'share_actions': 5}}
            if path.startswith('/api/admin/question_events'):
                return {
                    'total': 30,
                    'dropoff_ranking': [{'question_id': 3, 'question_text': '少人数の方が楽？', 'shown': 10, 'dropoff': 2, 'dropoff_rate': 20}],
                    'questions': [{'question_id': 4, 'question_text': '整った静かな雰囲気？', 'answered': 20, 'shown': 21, 'yes_rate': 92, 'category': 'aesthetic'}],
                }
            raise AssertionError(path)

        report = daily_analytics_report.build_daily_report(
            environ={'ADMIN_READ_TOKEN': 'token', 'HEKI_REPORT_DATE': '2026-05-26'},
            json_getter=fake_json,
        )

        self.assertEqual(report['status'], 'ok')
        self.assertIn('plays: 100', report['message'])
        self.assertIn('completion_rate: 20.0% (20/100)', report['message'])
        self.assertIn('共依存 40', report['message'])
        self.assertNotIn('unknown 40', report['message'])
        self.assertIn('heavy_result_ratio: unavailable (stats_history_fallback)', report['message'])
        self.assertIn('note: result stats are legacy fallback', report['message'])
        self.assertIn('share_rate: 10.0%', report['message'])
        self.assertIn('Q3 20.0% (2/10) 少人数の方が楽？', report['message'])
        self.assertIn('Q4 92.0% (20/21, aesthetic)', report['message'])
        self.assertNotIn('note: question_events未蓄積', report['message'])
        self.assertNotIn('token', report['message'])


    def test_daily_report_marks_heavy_ratio_as_reference_when_sample_is_small(self):
        line = daily_analytics_report._heavy_line([{'fetish_name': '激重感情', 'count': 4}, {'fetish_name': '白衣', 'count': 1}])

        self.assertEqual(line, 'heavy_result_ratio: 80.0% (参考値) (4/5)')

    def test_daily_report_marks_empty_analytics_logs(self):
        def fake_json(path):
            if path == '/api/admin/funnel_metrics':
                return {'stats_history': [{'date': '2026-05-26', 'start': 10, 'completion': 5}]}
            if path.startswith('/api/admin/recent_fetish_ranking'):
                return {'ranking': []}
            if path.startswith('/api/admin/share_events'):
                return {'total': 0, 'metrics': {'result_page_views': 0, 'share_actions': 0}}
            if path.startswith('/api/admin/question_events'):
                return {'total': 0, 'dropoff_ranking': [], 'questions': []}
            raise AssertionError(path)

        report = daily_analytics_report.build_daily_report(
            environ={'ADMIN_READ_TOKEN': 'token', 'HEKI_REPORT_DATE': '2026-05-26'},
            json_getter=fake_json,
        )

        self.assertIn('note: question_events未蓄積', report['message'])
        self.assertIn('note: share_events未蓄積', report['message'])



    def test_daily_report_survives_partial_api_timeouts(self):
        def fake_json(path):
            if path == '/api/admin/funnel_metrics':
                raise TimeoutError()
            if path.startswith('/api/admin/result_exposures'):
                raise TimeoutError()
            if path.startswith('/api/admin/recent_fetish_ranking'):
                raise TimeoutError()
            if path.startswith('/api/admin/share_events'):
                raise TimeoutError()
            if path.startswith('/api/admin/question_events'):
                return {'total': 4, 'dropoff_ranking': [], 'questions': []}
            raise AssertionError(path)

        report = daily_analytics_report.build_daily_report(
            environ={'ADMIN_READ_TOKEN': 'token', 'HEKI_REPORT_DATE': '2026-05-26'},
            json_getter=fake_json,
        )

        self.assertEqual(report['status'], 'ok')
        self.assertIn('plays: unavailable', report['message'])
        self.assertIn('completion_rate: unavailable', report['message'])
        self.assertIn('/api/admin/funnel_metrics: TimeoutError', report['message'])
        self.assertIn('result_source: unavailable', report['message'])
        self.assertIn('partial_failures:', report['message'])
        self.assertIn('/api/admin/share_events?days=1&limit=5000: TimeoutError', report['message'])
        self.assertIn('note: share_events未蓄積', report['message'])

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
        self.assertTrue(stats['completion_reliable'])

    def test_daily_report_marks_completion_rate_as_reference_when_unstable(self):
        stats = daily_analytics_report._previous_day_stats({
            'stats_history': [{'date': '2026-05-26', 'start': 8, 'completion': 8}],
        }, '2026-05-26')

        self.assertIn('completion_rate: 100.0% (参考値) (8/8)', daily_analytics_report._completion_line(stats))

    def test_operations_completion_rate_prefers_recent_bucket_and_marks_reference(self):
        metric = operations_check._completion_metric({'completion': {'recent_7_days': {'starts': 30, 'completions': 12, 'completion_rate': 42}, 'completion_rate': 101.8}})
        self.assertEqual(metric['rate'], 42.0)
        self.assertTrue(metric['reliable'])

        unstable = operations_check._completion_metric({'completion': {'recent_7_days': {'starts': 8, 'completions': 8, 'completion_rate': 100}}})
        self.assertEqual(unstable['rate'], 100.0)
        self.assertFalse(unstable['reliable'])
        self.assertIn('参考値', operations_check._completion_label(unstable))

    def test_operations_completion_rate_unavailable_when_completions_exceed_starts(self):
        metric = operations_check._completion_metric({
            'completion': {'recent_7_days': {'starts': 10, 'completions': 12, 'completion_rate': 120}},
        })
        self.assertIsNone(metric['rate'])
        self.assertFalse(metric['reliable'])
        self.assertIn('unavailable', operations_check._completion_label(metric))

        stats = daily_analytics_report._previous_day_stats({
            'stats_history': [{'date': '2026-05-26', 'start': 10, 'completion': 12}],
        }, '2026-05-26')
        self.assertIsNone(stats['completion_rate'])
        self.assertIn('unavailable', daily_analytics_report._completion_line(stats))

    def test_operations_single_5xx_is_warn_not_critical(self):
        def fake_json(path):
            if path == '/health':
                return {'status': 'ok', 'storage': 'postgres', 'matrix': {'ok': True}, 'runtime': {'error_counts': {'5xx': 1}}}
            if path == '/api/admin/preflight':
                return {'checks': []}
            if path == '/api/admin/works_health':
                return {'maintenance': {'works_count': 100}}
            if path.startswith('/api/admin/recent_fetish_ranking'):
                return {'ranking': []}
            if path.startswith('/api/admin/question_events'):
                return {'total': 1, 'metrics': {}, 'questions': [], 'dropoff_ranking': []}
            if path == '/api/admin/funnel_metrics':
                return {'completion': {'recent_7_days': {'starts': 30, 'completions': 15, 'completion_rate': 50}}}
            if path.startswith('/api/admin/share_events'):
                return {'total': 1, 'metrics': {'result_page_views': 1, 'share_actions': 0}}
            raise AssertionError(path)

        report = operations_check.build_report(
            environ={'ADMIN_READ_TOKEN': 'token'},
            json_getter=fake_json,
            bytes_getter=lambda path: operations_check.PNG_SIGNATURE + b'abc',
        )

        self.assertEqual(report['severity'], 'WARN')
        self.assertIn('5xx errors=1 (単発は様子見)', report['message'])


if __name__ == '__main__':
    unittest.main()
