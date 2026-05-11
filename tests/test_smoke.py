import base64
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ.setdefault('SECRET_KEY', 'test_secret_key_for_testing')

from app import app


class TestSmoke(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        self.client = app.test_client()

    def _admin_headers(self):
        os.environ['ADMIN_PASS'] = 'testpass'
        creds = base64.b64encode(b'admin:testpass').decode()
        return {'Authorization': f'Basic {creds}'}

    def test_index_loads_static_app_js(self):
        res = self.client.get('/')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'/static/app.css', res.data)
        self.assertIn(b'/static/app.js', res.data)
        self.assertIn(b'window.APP_CONFIG', res.data)
        self.assertNotIn(b'onclick=', res.data)
        self.assertNotIn(b'oninput=', res.data)
        self.assertNotIn(b'onchange=', res.data)
        with open(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static', 'app.js'), 'rb') as f:
            self.assertIn(b'function startGame', f.read())
        with open(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static', 'app.css'), 'rb') as f:
            self.assertIn(b'.btn-start', f.read())

    def test_admin_loads_static_admin_js_without_inline_handlers(self):
        res = self.client.get('/admin', headers=self._admin_headers())
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'/static/admin.css', res.data)
        self.assertIn(b'/static/admin_ops.js', res.data)
        self.assertIn(b'/static/admin.js', res.data)
        self.assertIn(b'class="skip-link"', res.data)
        self.assertIn(b'id="log-page-info"', res.data)
        self.assertNotIn(b'onclick=', res.data)
        self.assertNotIn(b'oninput=', res.data)
        self.assertNotIn(b'onchange=', res.data)
        with open(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static', 'admin.js'), 'rb') as f:
            self.assertIn(b'function saveParams', f.read())
        with open(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static', 'admin_ops.js'), 'rb') as f:
            self.assertIn(b'function loadPreflight', f.read())
        with open(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static', 'admin.css'), 'rb') as f:
            self.assertIn(b'.btn-save', f.read())

    def test_start_api_smoke(self):
        res = self.client.post('/api/start')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn('question_id', data)
        self.assertIn('question', data)


if __name__ == '__main__':
    unittest.main()
