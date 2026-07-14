from tests._service_test_support import (
    json,
    os,
    patch,
    share_links,
    tempfile,
    unittest,
)


class TestServiceShareLinks(unittest.TestCase):
    def test_share_link_round_trip_uses_longer_base62_id_and_no_personal_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'share_links.json')
            seq = iter(['7f3kQ9Lm'])
            share_id, payload = share_links.create_link(
                {
                    'name': '感覚遮断落とし穴',
                    'probability': '93',
                    'desc': 'テスト',
                    'title': 'あなたの『癖』は……',
                    'rank': 'AI観測ログ',
                    'ip': '127.0.0.1',
                    'user_agent': 'secret',
                },
                path=path,
                token_fn=lambda length: next(seq),
            )
            self.assertEqual(share_id, '7f3kQ9Lm')
            self.assertEqual(payload['name'], '感覚遮断落とし穴')
            resolved = share_links.resolve_link('7f3kQ9Lm', path=path)
            self.assertEqual(resolved['probability'], '93')
            self.assertEqual(share_links.count_links(path=path), 1)
            self.assertNotIn('ip', resolved)
            self.assertNotIn('user_agent', resolved)

    def test_resolve_link_accepts_existing_four_character_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'share_links.json')
            with open(path, 'w', encoding='utf-8') as file_obj:
                json.dump({'7f3k': {'name': '旧共有', 'probability': '93'}}, file_obj, ensure_ascii=False)
            resolved = share_links.resolve_link('7f3k', path=path)
        self.assertEqual(resolved['name'], '旧共有')
        self.assertEqual(resolved['probability'], '93')

    def test_share_links_use_postgres_when_available(self):
        executed = []

        class Cursor:
            def __init__(self):
                self.rows = []
                self.payload = None

            def execute(self, sql, params=None):
                executed.append((sql, params))
                if sql.startswith('SELECT share_id FROM share_links'):
                    self.rows = []
                elif sql.startswith('SELECT payload FROM share_links'):
                    self.rows = [(self.payload,)] if self.payload else []
                elif sql.startswith('SELECT COUNT'):
                    self.rows = [(1,)]
                elif sql.startswith('INSERT INTO share_links'):
                    self.payload = params[1]

            def fetchall(self):
                return self.rows

            def fetchone(self):
                return self.rows[0] if self.rows else None

        class Conn:
            def __init__(self):
                self.cursor_obj = Cursor()

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def cursor(self):
                return self.cursor_obj

        conn = Conn()
        with (
            patch.object(share_links, 'use_db', return_value=True),
            patch.object(share_links, 'get_conn', return_value=conn),
            patch.object(share_links, 'put_conn'),
        ):
            share_id, payload = share_links.create_link(
                {'name': '眼鏡', 'probability': '88', 'desc': 'テスト'},
                token_fn=lambda length: 'Ab12Cd34',
            )
            resolved = share_links.resolve_link(share_id)
            count = share_links.count_links()

        self.assertEqual(share_id, 'Ab12Cd34')
        self.assertEqual(payload['name'], '眼鏡')
        self.assertEqual(resolved['probability'], '88')
        self.assertEqual(count, 1)
        self.assertTrue(any('CREATE TABLE IF NOT EXISTS share_links' in sql for sql, _params in executed))
        self.assertTrue(any(sql.startswith('INSERT INTO share_links') for sql, _params in executed))

    def test_share_link_rejects_invalid_id_and_missing_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'share_links.json')
            self.assertIsNone(share_links.resolve_link('../bad', path=path))
            with self.assertRaises(ValueError):
                share_links.create_link({'probability': '88'}, path=path)
