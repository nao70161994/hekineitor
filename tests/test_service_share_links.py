from datetime import datetime, timezone

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
        self.assertFalse(any(sql.startswith('SELECT share_id FROM share_links') for sql, _params in executed))
        self.assertTrue(
            any(
                'DELETE FROM share_links' in sql and params == (share_links.DEFAULT_JSON_MAX_ENTRIES,)
                for sql, params in executed
            )
        )

    def test_postgres_share_id_collision_retries_without_loading_all_ids(self):
        inserted_ids = []

        class UniqueViolation(Exception):
            pgcode = '23505'

        class Cursor:
            def execute(self, sql, params=None):
                if sql.startswith('SELECT share_id FROM share_links'):
                    raise AssertionError('create_link must not load all share IDs')
                if sql.startswith('INSERT INTO share_links'):
                    inserted_ids.append(params[0])
                    if len(inserted_ids) == 1:
                        raise UniqueViolation

        class Conn:
            def cursor(self):
                return Cursor()

            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc, _tb):
                return False

        candidates = iter(['Aa12Bb34', 'Cc56Dd78'])
        with (
            patch.object(share_links, 'use_db', return_value=True),
            patch.object(share_links, 'get_conn', return_value=Conn()),
            patch.object(share_links, 'put_conn'),
        ):
            share_id, payload = share_links.create_link(
                {'name': '眼鏡'},
                token_fn=lambda _length: next(candidates),
            )

        self.assertEqual(share_id, 'Cc56Dd78')
        self.assertEqual(payload['name'], '眼鏡')
        self.assertEqual(inserted_ids, ['Aa12Bb34', 'Cc56Dd78'])

    def test_json_share_links_prune_oldest_created_at_to_configured_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'share_links.json')
            with open(path, 'w', encoding='utf-8') as file_obj:
                json.dump(
                    {
                        'NoDate01': {'name': '日時なし'},
                        'Oldest1': {'name': '古い', 'created_at': '2024-01-01T00:00:00+00:00'},
                        'Recent01': {'name': '新しい', 'created_at': '2025-01-01T00:00:00+00:00'},
                    },
                    file_obj,
                )
            share_id, _payload = share_links.create_link(
                {'name': '最新'},
                path=path,
                environ={'SHARE_LINKS_MAX_ENTRIES': '2'},
                now_fn=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc),
                token_fn=lambda _length: 'Newest01',
            )

            links = share_links.load_links(path=path)

        self.assertEqual(share_id, 'Newest01')
        self.assertEqual(set(links), {'Recent01', 'Newest01'})

    def test_json_share_link_limit_uses_safe_default_for_invalid_values(self):
        self.assertEqual(share_links._json_max_entries({}), share_links.DEFAULT_JSON_MAX_ENTRIES)
        self.assertEqual(
            share_links._json_max_entries({'SHARE_LINKS_MAX_ENTRIES': 'invalid'}),
            share_links.DEFAULT_JSON_MAX_ENTRIES,
        )
        self.assertEqual(
            share_links._json_max_entries({'SHARE_LINKS_MAX_ENTRIES': '0'}),
            share_links.DEFAULT_JSON_MAX_ENTRIES,
        )

    def test_share_link_rejects_invalid_id_and_missing_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'share_links.json')
            self.assertIsNone(share_links.resolve_link('../bad', path=path))
            with self.assertRaises(ValueError):
                share_links.create_link({'probability': '88'}, path=path)
