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
        with open(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static', 'game_flow.js'), 'rb') as f:
            self.assertIn(b'window.startGame', f.read())
        with open(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static', 'game_state.js'), 'rb') as f:
            self.assertIn(b'window.setLastFetishName', f.read())
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

    def test_client_module_scripts_are_loaded_in_dependency_order(self):
        res = self.client.get('/')
        self.assertEqual(res.status_code, 200)
        body = res.data.decode('utf-8')
        expected = [
            '/static/game_state.js',
            '/static/api_client.js',
            '/static/utils.js',
            '/static/renderers.js',
            '/static/app.js',
            '/static/network.js',
            '/static/ui.js',
            '/static/game_flow.js',
            '/static/draft.js',
            '/static/teach.js',
            '/static/history.js',
            '/static/feedback.js',
            '/static/share.js',
            '/static/pwa.js',
            '/static/events.js',
        ]
        positions = []
        for script in expected:
            self.assertIn(script, body)
            positions.append(body.index(script))
        self.assertEqual(positions, sorted(positions))

    def test_index_uses_png_og_image(self):
        res = self.client.get('/')
        self.assertEqual(res.status_code, 200)
        body = res.data.decode('utf-8')
        self.assertIn('property="og:image"', body)
        self.assertIn('/ogp.png?f=%E3%81%B8%E3%81%8D%E3%83%8D%E3%82%A4%E3%82%BF%E3%83%BC', body)
        self.assertIn('name="twitter:card" content="summary_large_image"', body)

    def test_result_share_uses_png_og_image(self):
        res = self.client.get('/r?f=Test&p=88&d=desc')
        self.assertEqual(res.status_code, 200)
        body = res.data.decode('utf-8')
        self.assertIn('/ogp.png?f=Test&amp;p=88', body)
        self.assertNotIn('/ogp?f=Test&amp;p=88', body)

    def test_legacy_svg_ogp_endpoint_still_works(self):
        res = self.client.get('/ogp?f=SvgTest&p=77')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.mimetype, 'image/svg+xml')
        self.assertIn(b'SvgTest', res.data)

    def test_share_page_keeps_social_metadata(self):
        res = self.client.get('/r?f=ShareTest&p=91&d=hello')
        self.assertEqual(res.status_code, 200)
        body = res.data.decode('utf-8')
        self.assertIn('property="og:image"', body)
        self.assertIn('name="twitter:card" content="summary_large_image"', body)
        self.assertIn('ShareTest', body)

    def test_service_worker_keeps_static_and_offline_cache_paths(self):
        res = self.client.get('/sw.js')
        self.assertEqual(res.status_code, 200)
        body = res.data.decode('utf-8')
        self.assertIn("'/manifest.json'", body)
        self.assertIn("'/offline'", body)
        self.assertIn("url.pathname.startsWith('/static/')", body)
        self.assertIn("url.pathname.includes('/api/')", body)

    def test_url_map_keeps_public_game_and_admin_routes(self):
        rules = {rule.rule for rule in app.url_map.iter_rules()}
        expected = {
            '/',
            '/fetishes',
            '/r',
            '/ogp.png',
            '/ogp',
            '/fetish/<int:fetish_id>',
            '/stats',
            '/robots.txt',
            '/sitemap.xml',
            '/manifest.json',
            '/sw.js',
            '/offline',
            '/health',
            '/api/start',
            '/api/answer',
            '/api/back',
            '/api/continue',
            '/api/confirm',
            '/api/teach',
            '/api/add_fetish',
            '/api/finalize_added',
            '/api/fetish/<int:fetish_id>',
            '/admin',
            '/api/admin/works_link_queue',
            '/api/admin/quality_report',
            '/api/admin/maintenance_checklist',
        }
        self.assertTrue(expected.issubset(rules))

    def test_start_api_smoke(self):
        res = self.client.post('/api/start')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn('question_id', data)
        self.assertIn('question', data)

    def test_client_compat_exports_live_with_owning_modules(self):
        root = os.path.dirname(os.path.dirname(__file__))
        expectations = {
            'static/game_flow.js': [b'window.startGame', b'window.sendAnswer', b'window.continueGame'],
            'static/feedback.js': [b'window.quickFeedback', b'window.submitConfirm'],
            'static/teach.js': [b'window.submitTeach', b'window.addFetishStep1'],
            'static/history.js': [b'window.toggleHistory', b'window.retryExcluding'],
            'static/draft.js': [b'window.resumeGame', b'window._checkDraft'],
            'static/share.js': [b'window.shareResult', b'window.setDiagnosedName'],
            'static/pwa.js': [b'window.dismissInstall'],
        }
        for relpath, markers in expectations.items():
            with open(os.path.join(root, relpath), 'rb') as f:
                body = f.read()
            for marker in markers:
                self.assertIn(marker, body, relpath)

        body = self.client.get('/').data.decode('utf-8')
        self.assertNotIn('/static/compat.js', body)

        self.assertFalse(os.path.exists(os.path.join(root, 'static', 'compat.js')))

        with open(os.path.join(root, 'static', 'game_state.js'), 'rb') as f:
            state = f.read()
        self.assertIn(b'window.setLastFetishName', state)

    def test_resume_feedback_draft_static_contracts(self):
        root = os.path.dirname(os.path.dirname(__file__))
        with open(os.path.join(root, 'static', 'draft.js'), 'rb') as f:
            draft = f.read()
        self.assertIn(b"const DRAFT_KEY = 'heki_draft'", draft)
        self.assertIn(b"apiFetch('/api/resume'", draft)
        self.assertIn(b'localStorage.setItem(DRAFT_KEY', draft)

        with open(os.path.join(root, 'static', 'feedback.js'), 'rb') as f:
            feedback = f.read()
        self.assertIn(b"apiFetch('/api/confirm'", feedback)
        self.assertIn(b"apiFetch('/api/finalize_added'", feedback)
        self.assertIn('ありがとうございます。'.encode('utf-8'), feedback)
        self.assertIn('保存せず確認しました'.encode('utf-8'), feedback)
        with open(os.path.join(root, 'static', 'teach.js'), 'rb') as f:
            teach = f.read()
        self.assertIn('保存せず確認しました'.encode('utf-8'), teach)

    def test_share_ogp_and_pwa_static_contracts(self):
        root = os.path.dirname(os.path.dirname(__file__))
        with open(os.path.join(root, 'static', 'share.js'), 'rb') as f:
            share = f.read()
        self.assertIn(b'/r?f=', share)
        self.assertIn(b'navigator.share', share)
        self.assertIn(b'twitter.com/intent/tweet', share)

        with open(os.path.join(root, 'templates', 'sw.js'), 'rb') as f:
            sw = f.read()
        self.assertIn(b"const STATIC = ['/', '/manifest.json'", sw)
        self.assertIn(b"url.pathname.includes('/admin')", sw)
        self.assertIn(b"caches.match('/offline')", sw)


if __name__ == '__main__':
    unittest.main()
