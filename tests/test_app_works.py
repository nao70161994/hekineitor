# ruff: noqa: F403, F405

from tests._app_test_support import *


class TestCompoundWorks(FileSnapshotMixin, unittest.TestCase):
    """compound_works機能のテスト"""

    def setUp(self):
        import engine as em

        self._save_patch = patch.object(em, '_save_compound_works', return_value=None)
        self._save_patch.start()
        # テスト前にキャッシュをリセット
        em._compound_works_loaded = False
        em._COMPOUND_WORKS = {}
        app.config['TESTING'] = True
        self.client = app.test_client()

    def tearDown(self):
        import engine as em

        em._compound_works_loaded = False
        em._COMPOUND_WORKS = {}
        self._save_patch.stop()

    def _admin_read_headers(self):
        return {'Authorization': 'Bearer read-token'}

    def _admin_headers(self):
        import base64

        os.environ['ADMIN_PASS'] = 'testpass'
        creds = base64.b64encode(b'admin:testpass').decode()
        return {'Authorization': f'Basic {creds}'}

    def test_get_compound_works_returns_empty_for_unknown_pair(self):
        from engine import get_compound_works

        result = get_compound_works(9999, 9998)
        self.assertEqual(result, [])

    def test_set_and_get_compound_works(self):
        from engine import get_compound_works, set_compound_works

        set_compound_works(100, 200, ['作品A', '作品B'])
        result = get_compound_works(100, 200)
        self.assertEqual(result, ['作品A', '作品B'])
        # 逆順のIDでも同じ結果
        result2 = get_compound_works(200, 100)
        self.assertEqual(result2, ['作品A', '作品B'])

    def test_delete_compound_works(self):
        from engine import delete_compound_works, get_compound_works, set_compound_works

        set_compound_works(100, 200, ['作品A'])
        ok = delete_compound_works(100, 200)
        self.assertTrue(ok)
        self.assertEqual(get_compound_works(100, 200), [])

    def test_delete_nonexistent_returns_false(self):
        from engine import delete_compound_works

        self.assertFalse(delete_compound_works(9999, 9998))

    def test_list_compound_works(self):
        from engine import list_compound_works, set_compound_works

        set_compound_works(1, 2, ['作品X'])
        set_compound_works(3, 4, ['作品Y', '作品Z'])
        items = list_compound_works()
        keys = [i['key'] for i in items]
        self.assertIn('1,2', keys)
        self.assertIn('3,4', keys)

    def test_api_set_compound_works(self):
        headers = self._admin_headers()
        res = self.client.post(
            '/api/admin/compound_works',
            json={'id_a': 0, 'id_b': 1, 'works': ['テスト作品A', 'テスト作品B']},
            headers=headers,
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['status'], 'ok')
        self.assertEqual(data['key'], '0,1')
        self.assertIn('テスト作品A', data['works'])

    def test_api_set_requires_works(self):
        headers = self._admin_headers()
        res = self.client.post('/api/admin/compound_works', json={'id_a': 0, 'id_b': 1, 'works': []}, headers=headers)
        self.assertEqual(res.status_code, 400)

    def test_api_set_same_id_rejected(self):
        headers = self._admin_headers()
        res = self.client.post(
            '/api/admin/compound_works', json={'id_a': 5, 'id_b': 5, 'works': ['作品']}, headers=headers
        )
        self.assertEqual(res.status_code, 400)

    def test_api_list_compound_works(self):
        from app import engine as app_engine

        app_engine.set_compound_work_rows(0, 1, ['テスト作品'])
        headers = self._admin_headers()
        res = self.client.get('/api/admin/compound_works', headers=headers)
        self.assertEqual(res.status_code, 200)
        items = res.get_json()
        self.assertIsInstance(items, list)
        keys = [i['key'] for i in items]
        self.assertIn('0,1', keys)
        # name_a / name_b フィールドが付与されている
        item = next(i for i in items if i['key'] == '0,1')
        self.assertIn('name_a', item)
        self.assertIn('name_b', item)

    def test_api_delete_compound_works(self):
        from app import engine as app_engine

        app_engine.set_compound_work_rows(0, 1, ['作品'])
        headers = self._admin_headers()
        res = self.client.delete('/api/admin/compound_works/0,1', headers=headers)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()['status'], 'deleted')

    def test_api_delete_nonexistent(self):
        headers = self._admin_headers()
        res = self.client.delete('/api/admin/compound_works/9999,9998', headers=headers)
        self.assertEqual(res.status_code, 404)

    def test_cross_works_in_guess_response(self):
        """複合診断時にcross_worksフィールドが返る"""
        from engine import set_compound_works

        set_compound_works(0, 1, ['複合専用テスト作品'])
        client = app.test_client()
        res = client.post('/api/start')
        q_id = res.get_json()['question_id']
        # 上限まで答えて強制終了させる
        for _ in range(35):
            r = client.post('/api/answer', json={'question_id': q_id, 'answer': 1})
            d = r.get_json()
            if d.get('action') == 'guess':
                break
            q_id = d.get('question_id', q_id)
        # cross_worksフィールドが存在する（空でも可）
        self.assertIn('cross_works', d)
        self.assertIsInstance(d['cross_works'], list)

    def test_edit_fetish_with_works(self):
        """edit_fetish()がworksパラメータを受け付ける"""
        import engine as em

        eng = em.Engine()
        fid = eng.fetishes[0]['id']
        ok = eng.edit_fetish(fid, works=['テスト作品1', 'テスト作品2'])
        self.assertTrue(ok)
        idx = eng.index_of(fid)
        self.assertEqual(eng.fetishes[idx]['works'], ['テスト作品1', 'テスト作品2'])

    def test_admin_api_edit_fetish_works(self):
        """APIからworks編集ができる（テスト後に元に戻す）"""
        from app import engine as app_engine

        headers = self._admin_headers()
        fid = app_engine.fetishes[0]['id']
        idx = app_engine.index_of(fid)
        original_works = list(app_engine.fetishes[idx].get('works', []))
        try:
            res = self.client.post(
                f'/api/admin/edit_fetish/{fid}', json={'works': ['API作品A', 'API作品B']}, headers=headers
            )
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertIn('API作品A', data['works'])
        finally:
            app_engine.edit_fetish(fid, works=original_works)

    def test_admin_api_edit_fetish_rejects_invalid_works_payload_types(self):
        from app import engine as app_engine

        headers = self._admin_headers()
        fid = app_engine.fetishes[0]['id']
        for works in (None, {'title': 'bad'}, 123):
            with self.subTest(works=works):
                res = self.client.post(f'/api/admin/edit_fetish/{fid}', json={'works': works}, headers=headers)
                self.assertEqual(res.status_code, 400)

    def test_work_url_rejects_javascript_scheme(self):
        from engine import parse_work_item

        self.assertEqual(parse_work_item('危険|javascript:alert(1)'), '危険')
        self.assertEqual(parse_work_item({'title': '危険', 'url': 'javascript:alert(1)'}), '危険')
        self.assertEqual(
            parse_work_item('安全|https://example.com/a'),
            {'title': '安全', 'url': 'https://example.com/a'},
        )
