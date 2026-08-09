"""Real PostgreSQL lifecycle coverage for the normalized work catalog."""

import importlib
import json
import os
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from engine import db as engine_db
from engine import db_stats, db_work_catalog, work_catalog
from services import event_store, gameplay_events

TEST_POSTGRES_URL = os.environ.get('TEST_POSTGRES_URL')
DATA_DIR = Path(__file__).resolve().parents[1] / 'data'


class _FixtureEngine:
    questions = json.loads((DATA_DIR / 'questions.json').read_text(encoding='utf-8'))

    @staticmethod
    def _load_json(name):
        return json.loads((DATA_DIR / name).read_text(encoding='utf-8'))


if TEST_POSTGRES_URL:
    psycopg2 = importlib.import_module('psycopg2')
    extras = importlib.import_module('psycopg2.extras')
else:
    psycopg2 = None
    extras = None


@unittest.skipUnless(TEST_POSTGRES_URL, 'TEST_POSTGRES_URL is not configured')
class PostgresWorkCatalogIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url = TEST_POSTGRES_URL
        cls.schema = f'hekineitor_test_{uuid.uuid4().hex}'
        admin = psycopg2.connect(cls.url)
        admin.autocommit = True
        try:
            with admin.cursor() as cur:
                cur.execute(f'CREATE SCHEMA {cls.schema}')
        finally:
            admin.close()

    @classmethod
    def tearDownClass(cls):
        admin = psycopg2.connect(cls.url)
        admin.autocommit = True
        try:
            with admin.cursor() as cur:
                cur.execute(f'DROP SCHEMA IF EXISTS {cls.schema} CASCADE')
        finally:
            admin.close()

    def get_conn(self):
        return psycopg2.connect(self.url, options=f'-c search_path={self.schema}')

    @staticmethod
    def put_conn(conn):
        conn.close()

    def setUp(self):
        conn = self.get_conn()
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute('CREATE TABLE IF NOT EXISTS fetishes (id INTEGER PRIMARY KEY)')
                    cur.execute('TRUNCATE fetishes CASCADE')
                    cur.executemany('INSERT INTO fetishes (id) VALUES (%s)', [(1,), (2,)])
                    db_work_catalog.ensure_schema(cur)
                    base = work_catalog.build_catalog_from_inline(
                        [
                            {
                                'id': 1,
                                'works': [
                                    {
                                        'title': 'Base Work',
                                        'url': 'https://www.amazon.co.jp/dp/B000000001',
                                    }
                                ],
                            },
                            {'id': 2, 'works': []},
                        ],
                        compound_rows=[{'id_a': 1, 'id_b': 2, 'works': ['Pair Work']}],
                    )
                    db_work_catalog.replace_catalog(cur, base, execute_values=extras.execute_values)
        finally:
            self.put_conn(conn)
        self.base = base

    def snapshot(self):
        return db_work_catalog.load_catalog(get_conn=self.get_conn, put_conn=self.put_conn)

    def replace(self, catalog):
        conn = self.get_conn()
        try:
            with conn:
                with conn.cursor() as cur:
                    db_work_catalog.lock_catalog(cur)
                    return db_work_catalog.replace_catalog(cur, catalog, execute_values=extras.execute_values)
        finally:
            self.put_conn(conn)

    def test_crud_projection_restore_and_transaction_rollback_match_pure_catalog(self):
        self.assertEqual(self.snapshot(), self.base)
        updated, work_id = work_catalog.admin_create_master(
            self.base,
            {'canonical_title': 'Managed Work', 'media_type': 'manga'},
        )
        updated, edition_id = work_catalog.admin_upsert_edition(
            updated,
            {
                'work_id': work_id,
                'canonical_url': 'https://example.com/managed/1',
                'edition_title': 'Managed Work 1',
                'publisher': 'Publisher',
                'format': 'digital',
            },
        )
        updated, identifier_id = work_catalog.admin_upsert_edition_identifier(
            updated,
            {'edition_id': edition_id, 'scheme': 'isbn', 'authority': 'isbn', 'value': '9780306406157'},
        )
        updated, alias_id = work_catalog.admin_upsert_alias(
            updated,
            {'work_id': work_id, 'alias': 'Managed Alias'},
        )
        self.replace(updated)
        self.assertEqual(self.snapshot(), updated)

        before_failed_write = self.snapshot()
        conn = self.get_conn()
        try:
            with self.assertRaises(RuntimeError):
                with conn:
                    with conn.cursor() as cur:
                        db_work_catalog.lock_catalog(cur)
                        db_work_catalog.replace_catalog(cur, self.base, execute_values=extras.execute_values)
                        raise RuntimeError('force rollback')
        finally:
            self.put_conn(conn)
        self.assertEqual(self.snapshot(), before_failed_write)

        deleted = work_catalog.admin_delete_edition_identifier(updated, identifier_id)
        deleted = work_catalog.admin_delete_alias(deleted, alias_id)
        deleted = work_catalog.admin_delete_edition(deleted, edition_id)
        deleted = work_catalog.admin_delete_master(deleted, work_id)
        self.replace(deleted)
        self.assertEqual(self.snapshot(), self.base)

    def test_optimistic_mutation_rejects_stale_digest_without_partial_write(self):
        before = self.snapshot()
        digest = work_catalog.catalog_digest(before)

        def mutate(catalog):
            return work_catalog.admin_create_master(catalog, {'canonical_title': 'Atomic Work'})

        updated, result = engine_db.mutate_work_catalog(
            mutate,
            expected_digest=digest,
            get_conn=self.get_conn,
            put_conn=self.put_conn,
            execute_values=extras.execute_values,
        )
        self.assertEqual(
            result, next(row['work_id'] for row in updated['works_master'] if row['canonical_title'] == 'Atomic Work')
        )
        self.assertEqual(self.snapshot(), updated)

        with self.assertRaisesRegex(ValueError, 'version conflict'):
            engine_db.mutate_work_catalog(
                mutate,
                expected_digest=digest,
                get_conn=self.get_conn,
                put_conn=self.put_conn,
                execute_values=extras.execute_values,
            )
        self.assertEqual(self.snapshot(), updated)

    def test_fetish_log_migration_and_dual_counters_run_on_real_postgres(self):
        conn = self.get_conn()
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute("ALTER TABLE fetishes ADD COLUMN IF NOT EXISTS name TEXT NOT NULL DEFAULT ''")
                    cur.execute('ALTER TABLE fetishes ADD COLUMN IF NOT EXISTS "desc" TEXT NOT NULL DEFAULT \'\'')
                    cur.execute("ALTER TABLE fetishes ADD COLUMN IF NOT EXISTS works TEXT NOT NULL DEFAULT '[]'")
                    cur.execute(
                        'CREATE TABLE IF NOT EXISTS matrix (fetish_id INTEGER, question_id INTEGER, yes_count REAL NOT NULL, total_count REAL NOT NULL, PRIMARY KEY (fetish_id, question_id))'
                    )
                    cur.execute('INSERT INTO matrix VALUES (1, 0, 2, 4) ON CONFLICT DO NOTHING')
                    cur.execute('DROP TABLE IF EXISTS fetish_log')
                    cur.execute(
                        'CREATE TABLE fetish_log (fetish_id INTEGER PRIMARY KEY, guessed INTEGER NOT NULL DEFAULT 0, correct INTEGER NOT NULL DEFAULT 0, wrong INTEGER NOT NULL DEFAULT 0)'
                    )
                    cur.execute('INSERT INTO fetish_log VALUES (1, 5, 7, 2)')
        finally:
            self.put_conn(conn)

        engine_db.ensure_schema(
            _FixtureEngine(),
            get_conn=self.get_conn,
            put_conn=self.put_conn,
            execute_values=extras.execute_values,
            player_base_id=100000,
            build_initial_matrix=lambda nf, nq: ([[2.0] * nq for _ in range(nf)], [[4.0] * nq for _ in range(nf)]),
        )
        migrated = db_stats.load_fetish_log(get_conn=self.get_conn, put_conn=self.put_conn)
        self.assertEqual(
            migrated[1],
            {
                'guessed': 5,
                'correct': 7,
                'wrong': 2,
                'correction_selected': 0,
                'exposure_guessed': 0,
                'exposure_correct': 0,
            },
        )

        db_stats.increment_fetish_log_counters(
            1,
            {'guessed': 1, 'correct': 1, 'exposure_guessed': 1, 'exposure_correct': 1},
            get_conn=self.get_conn,
            put_conn=self.put_conn,
        )
        db_stats.increment_fetish_log_counters(
            2,
            {'guessed': 2, 'exposure_guessed': 2, 'exposure_correct': 1},
            get_conn=self.get_conn,
            put_conn=self.put_conn,
        )
        engine_db.merge_fetish_rows_db(1, 2, get_conn=self.get_conn, put_conn=self.put_conn)
        merged = db_stats.load_fetish_log(get_conn=self.get_conn, put_conn=self.put_conn)
        self.assertEqual(merged[1]['guessed'], 8)
        self.assertEqual(merged[1]['exposure_guessed'], 3)
        self.assertEqual(merged[1]['exposure_correct'], 2)
        self.assertNotIn(2, merged)

        conn = self.get_conn()
        try:
            with self.assertRaises(RuntimeError):
                with conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            'UPDATE fetish_log SET exposure_guessed = exposure_guessed + 10 WHERE fetish_id = 1'
                        )
                        raise RuntimeError('force rollback')
        finally:
            self.put_conn(conn)
        rolled_back = db_stats.load_fetish_log(get_conn=self.get_conn, put_conn=self.put_conn)
        self.assertEqual(rolled_back[1]['exposure_guessed'], 3)

    def test_gameplay_event_payload_and_retention_match_jsonl_on_real_postgres(self):
        event_type = f'gameplay_integration_{uuid.uuid4().hex}'
        now = datetime(2026, 8, 9, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            json_event = gameplay_events.record_event(
                'diagnosis_summary',
                path=os.path.join(tmp, 'gameplay.jsonl'),
                now_fn=lambda: now,
                release='2026.08.09',
                summary_status='completed',
                retry_kind='new',
                result_reached=True,
                answered_count=12,
                feedback_outcome='maybe',
                correction_count=1,
            )
        old_event = {**json_event, 'timestamp': (now - timedelta(days=91)).isoformat(timespec='seconds')}
        event_store.record_event(
            event_type,
            old_event,
            get_conn_fn=self.get_conn,
            put_conn_fn=self.put_conn,
        )
        event_store._LAST_RETENTION_PRUNE.pop(event_type, None)
        event_store.record_event(
            event_type,
            json_event,
            retention_days=90,
            now_fn=lambda: now,
            get_conn_fn=self.get_conn,
            put_conn_fn=self.put_conn,
        )

        stored = event_store.read_events(
            event_type,
            get_conn_fn=self.get_conn,
            put_conn_fn=self.put_conn,
        )

        self.assertEqual(stored, [json_event])
        self.assertEqual(stored[0]['schema_version'], gameplay_events.SCHEMA_VERSION)
        self.assertEqual(stored[0]['release'], '2026.08.09')


if __name__ == '__main__':
    unittest.main()
