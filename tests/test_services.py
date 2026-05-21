import os
import tempfile
import unittest

from services import admin_security, app_meta, ids, inference, matrix_backups, name_matching, quality_stats, question_selection, rate_limit, response_hooks


class DummyRequest:
    def __init__(self, json_data=None, headers=None, method='GET', authorization=None):
        self._json_data = json_data
        self.headers = headers or {}
        self.method = method
        self.authorization = authorization

    def get_json(self, silent=True):
        return self._json_data


class DummyAuth:
    def __init__(self, username, password):
        self.username = username
        self.password = password


def dummy_jsonify(payload):
    return payload


class TestServices(unittest.TestCase):
    def test_name_matching_finds_close_names_without_exact_self_match(self):
        fetishes = [
            {'id': 1, 'name': 'ヤンデレ'},
            {'id': 2, 'name': 'ツンデレ'},
            {'id': 3, 'name': 'メガネ'},
        ]
        result = name_matching.find_similar('ヤンデレ系', fetishes)
        self.assertEqual(result[0]['id'], 1)
        exact_results = name_matching.find_similar('ヤンデレ', fetishes)
        self.assertNotIn(1, [item['id'] for item in exact_results])

    def test_app_version_changes_with_file_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'app.py')
            with open(path, 'w', encoding='utf-8') as f:
                f.write('a')
            first = app_meta.app_version(tmp, paths=('app.py',))
            with open(path, 'w', encoding='utf-8') as f:
                f.write('b')
            second = app_meta.app_version(tmp, paths=('app.py',))
        self.assertNotEqual(first, second)

    def test_confirm_text_accepts_body_or_header(self):
        self.assertEqual(
            admin_security.confirmation_text(DummyRequest(json_data={'confirm_text': 'OK'})),
            'OK',
        )
        self.assertEqual(
            admin_security.confirmation_text(DummyRequest(headers={'X-Confirm-Text': 'HDR'})),
            'HDR',
        )

    def test_csrf_token_reuses_unexpired_token(self):
        session = {'admin_csrf_token': 'token', 'admin_csrf_issued_at': 100}
        token = admin_security.csrf_token(
            session,
            {'ADMIN_CSRF_TTL_SECONDS': '7200'},
            now_fn=lambda: 200,
            token_fn=lambda size: 'new-token',
        )
        self.assertEqual(token, 'token')
        self.assertEqual(session['admin_csrf_token'], 'token')

    def test_csrf_token_refreshes_expired_token(self):
        session = {'admin_csrf_token': 'token', 'admin_csrf_issued_at': 0}
        token = admin_security.csrf_token(
            session,
            {'ADMIN_CSRF_TTL_SECONDS': '1'},
            now_fn=lambda: 100,
            token_fn=lambda size: 'new-token',
        )
        self.assertEqual(token, 'new-token')
        self.assertEqual(session['admin_csrf_issued_at'], 100)

    def test_rate_limit_uses_forwarded_for_only_for_trusted_proxy(self):
        req = DummyRequest(headers={'X-Forwarded-For': '203.0.113.9, 10.0.0.1'})
        req.remote_addr = '127.0.0.1'
        self.assertEqual(
            rate_limit.client_ip(req, {'TRUSTED_PROXY_IPS': '127.0.0.1'}),
            '203.0.113.9',
        )
        self.assertEqual(rate_limit.client_ip(req, {'TRUSTED_PROXY_IPS': ''}), '127.0.0.1')

    def test_rate_limit_returns_retry_after_response(self):
        req = DummyRequest()
        req.remote_addr = '127.0.0.1'
        buckets = {}
        guard = lambda name: True
        first = rate_limit.rate_limit(
            'api_start', 1, req, {}, buckets, dummy_jsonify, guard,
            window_seconds=60, time_fn=lambda: 100,
        )
        second = rate_limit.rate_limit(
            'api_start', 1, req, {}, buckets, dummy_jsonify, guard,
            window_seconds=60, time_fn=lambda: 101,
        )
        self.assertIsNone(first)
        self.assertEqual(second[1], 429)
        self.assertEqual(second[2]['Retry-After'], '59')


    def test_response_hooks_set_security_headers_and_count_errors(self):
        class Response:
            status_code = 404
            headers = {}

        counts = {'4xx': 0, '5xx': 0}
        response_hooks.record_status_counts(Response, counts)
        response_hooks.apply_security_headers(Response)
        self.assertEqual(counts['4xx'], 1)
        self.assertEqual(Response.headers['X-Content-Type-Options'], 'nosniff')
        self.assertIn("default-src 'self'", Response.headers['Content-Security-Policy'])

    def test_response_hooks_audit_admin_mutations_only(self):
        calls = []
        req = DummyRequest(method='POST')
        req.path = '/api/admin/cleanup_sessions'
        response = type('Response', (), {'status_code': 200})()
        response_hooks.write_admin_audit(
            response, req, lambda *args: calls.append(args),
        )
        self.assertEqual(calls[0][0], 'admin_api')
        self.assertEqual(calls[0][1], 'ok')

        calls.clear()
        req.path = '/api/admin/import_matrix'
        response_hooks.write_admin_audit(response, req, lambda *args: calls.append(args))
        self.assertEqual(calls, [])


    def test_matrix_backup_completeness_error_shape(self):
        result = matrix_backups.completeness_error(
            {'skipped_rows': 0, 'valid_rows': 1},
            2,
            dummy_jsonify,
        )
        self.assertEqual(result[1], 400)
        self.assertEqual(result[0]['expected_rows'], 2)

    def test_matrix_backup_prune_keeps_configured_count(self):
        removed = []

        class DummyPath:
            @staticmethod
            def join(*parts):
                return '/'.join(parts)

        class DummyOs:
            path = DummyPath

            @staticmethod
            def remove(path):
                removed.append(path)

        matrix_backups.prune_backups(
            environ={'MATRIX_IMPORT_BACKUP_KEEP': '2'},
            data_path=lambda name: name,
            os_module=DummyOs,
            list_fn=lambda limit=None: [{'name': f'b{i}.json'} for i in range(4)],
        )
        self.assertEqual(removed, ['matrix_import_backups/b2.json', 'matrix_import_backups/b3.json'])


    def test_quality_stats_records_guess_and_feedback_keys(self):
        calls = []

        class Engine:
            def _record_daily_stat(self, key):
                calls.append(key)

        session = {'low_confidence_extended': True}
        quality_stats.mark_guess_quality(Engine(), session, {str(i): 1 for i in range(22)}, 20)
        self.assertEqual(session['last_guess_quality'], {
            'low_confidence_extended': True,
            'additional_questions': 2,
        })
        self.assertIn('q_low_conf_guess', calls)
        self.assertIn('q_additional_guess', calls)
        self.assertEqual(calls.count('q_additional_question'), 2)

        quality_stats.record_guess_quality_feedback(Engine(), session, correct=False)
        self.assertNotIn('last_guess_quality', session)
        self.assertIn('q_low_conf_wrong', calls)
        self.assertIn('q_additional_wrong', calls)


    def test_question_selection_low_confidence_extension_bounds(self):
        self.assertFalse(question_selection.should_extend_low_confidence(19, 0.1, 0.09, 0.75, 20, 30))
        self.assertTrue(question_selection.should_extend_low_confidence(20, 0.7, 0.6, 0.75, 20, 30))
        self.assertTrue(question_selection.should_extend_low_confidence(20, 0.8, 0.7, 0.75, 20, 30))
        self.assertFalse(question_selection.should_extend_low_confidence(30, 0.7, 0.6, 0.75, 20, 30))


    def test_ids_parse_id_list_ignores_invalid_values(self):
        self.assertEqual(ids.parse_id_list(['1', 2, 'bad', None]), {1, 2})
        self.assertEqual(ids.parse_id_list('1,2'), set())


    def test_inference_make_guess_records_side_effects(self):
        calls = []

        class Engine:
            fetishes = [{'id': 7, 'name': 'A', 'desc': '', 'works': []}]
            questions = []
            config = {}

            def increment_play_count(self):
                calls.append('increment')

            def posteriors(self, answers):
                return [0.9]

            def get_related(self, source_db_id):
                return []

            def get_answer_contributions(self, answers, fetish_idx):
                return []

            def log_guessed(self, fetish_id):
                calls.append(('guessed', fetish_id))

        ctx = type('Ctx', (), {})()
        ctx.engine = Engine()
        ctx.session = {}
        ctx.soft_max_questions = 20
        ctx.mark_guess_quality = lambda engine, session, answers, soft: calls.append('quality')
        ctx.inference_context = lambda: type('InferenceCtx', (), {
            'engine': ctx.engine,
            'session': ctx.session,
            'work_title': lambda work: str(work),
            'get_compound_works': lambda a, b: [],
            'profile_min_ratio': 0.25,
            'profile_min_prob': 0.08,
            'compound_ratio': 0.55,
            'triple_ratio': 0.45,
        })()
        ctx.jsonify = lambda payload: payload

        result = inference.make_guess(ctx, {})
        self.assertEqual(result['fetish_id'], 7)
        self.assertEqual(calls, ['increment', 'quality', ('guessed', 7)])



if __name__ == '__main__':
    unittest.main()
