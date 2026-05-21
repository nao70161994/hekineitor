import os
import tempfile
import unittest

from services import admin_security, app_meta, name_matching, rate_limit, response_hooks


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



if __name__ == '__main__':
    unittest.main()
