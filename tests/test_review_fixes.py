import base64
import copy
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from unittest.mock import Mock, patch

import app as app_module
from engine import db as engine_db
from engine import facade as engine_facade
from engine import persistence as engine_persistence
from scripts import daily_analytics_report, validate_matrix_backup
from services import app_meta, rate_limit, server_session, share_links
from storage import atomic_write_json


class Request:
    remote_addr = '127.0.0.1'
    headers = {}


class ReviewFixTests(unittest.TestCase):
    def test_api_rejects_non_object_json(self):
        app_module.app.config['TESTING'] = True
        client = app_module.app.test_client()
        for payload in ([], 'text', None):
            response = client.post('/api/answer', data=json.dumps(payload), content_type='application/json')
            self.assertEqual(response.status_code, 400)

    def test_empty_json_get_reaches_route_guards(self):
        client = app_module.app.test_client()
        response = client.get('/api/admin/preflight', headers={'Content-Type': 'application/json'})
        self.assertNotEqual(response.status_code, 400)

    def test_development_server_is_safe_by_default(self):
        self.assertEqual(
            app_meta.development_server_options({}),
            {
                'debug': False,
                'host': '127.0.0.1',
                'port': 5000,
            },
        )
        self.assertEqual(
            app_meta.development_server_options(
                {
                    'FLASK_DEBUG': 'true',
                    'FLASK_HOST': '0.0.0.0',
                    'FLASK_PORT': '8000',
                }
            )['port'],
            8000,
        )

    def test_production_rejects_short_secret(self):
        with self.assertRaises(RuntimeError):
            app_meta.secret_key({'APP_ENV': 'production', 'SECRET_KEY': 'short'})

    def test_nonpositive_rate_limit_configuration_falls_back_safely(self):
        self.assertIsNone(
            rate_limit.rate_limit(
                'scope',
                5,
                Request(),
                {},
                {},
                lambda value: value,
                lambda _name: True,
                environ={'RATE_LIMIT_SCOPE_LIMIT': '0', 'RATE_LIMIT_SCOPE_WINDOW': '-1'},
            )
        )

    def test_rate_limit_is_atomic_between_threads(self):
        buckets = {}
        barrier = threading.Barrier(8)
        results = []

        def invoke():
            barrier.wait()
            results.append(
                rate_limit.rate_limit(
                    'parallel',
                    1,
                    Request(),
                    {},
                    buckets,
                    lambda value: value,
                    lambda _name: True,
                    time_fn=lambda: 100,
                )
            )

        threads = [threading.Thread(target=invoke) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sum(result is None for result in results), 1)
        self.assertEqual(sum(result is not None and result[1] == 429 for result in results), 7)

    def test_sqlite_rate_limit_is_shared_across_bucket_dicts(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'rate.sqlite3')
            first = rate_limit.rate_limit(
                'shared',
                1,
                Request(),
                {},
                {},
                lambda value: value,
                lambda _name: True,
                shared_path=path,
                time_fn=lambda: 100,
            )
            second = rate_limit.rate_limit(
                'shared',
                1,
                Request(),
                {},
                {},
                lambda value: value,
                lambda _name: True,
                shared_path=path,
                time_fn=lambda: 100,
            )
            self.assertIsNone(first)
            self.assertEqual(second[1], 429)

    def test_shared_rate_limit_preserves_windows_longer_than_one_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'long-window.sqlite3')
            rate_limit.rate_limit(
                'long',
                1,
                Request(),
                {},
                {},
                lambda value: value,
                lambda _name: True,
                shared_path=path,
                window_seconds=172800,
                time_fn=lambda: 0,
            )
            other = type('OtherRequest', (), {'remote_addr': '127.0.0.2', 'headers': {}})()
            rate_limit.rate_limit(
                'long',
                1,
                other,
                {},
                {},
                lambda value: value,
                lambda _name: True,
                shared_path=path,
                window_seconds=172800,
                time_fn=lambda: 90000,
            )
            result = rate_limit.rate_limit(
                'long',
                1,
                Request(),
                {},
                {},
                lambda value: value,
                lambda _name: True,
                shared_path=path,
                window_seconds=172800,
                time_fn=lambda: 90000,
            )
            self.assertEqual(result[1], 429)

    def test_rate_limit_prunes_expired_keys(self):
        buckets = {('scope', 'old'): [1], ('other', 'kept'): [1]}
        rate_limit.rate_limit(
            'scope',
            5,
            Request(),
            {},
            buckets,
            lambda value: value,
            lambda _name: True,
            window_seconds=10,
            time_fn=lambda: 100,
        )
        self.assertNotIn(('scope', 'old'), buckets)
        self.assertIn(('other', 'kept'), buckets)

    def test_sqlite_sessions_share_state_outside_testing(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.dict(
                os.environ,
                {
                    'APP_ENV': 'development',
                    'SESSION_SQLITE_PATH': os.path.join(tmp, 'sessions.sqlite3'),
                    'SESSION_STORAGE': 'sqlite',
                },
            ),
        ):
            server_session.session_save('shared-sid', {'answers': {'1': 1}})
            server_session.LOCAL_SESSIONS.clear()
            self.assertEqual(server_session.session_load('shared-sid')['answers'], {'1': 1})

    def test_session_request_lock_serializes_same_sid(self):
        sid = '11111111-1111-1111-1111-111111111111'
        first_acquired = threading.Event()
        release_first = threading.Event()
        second_acquired = threading.Event()

        def first():
            handle = server_session._acquire_request_lock(sid)
            first_acquired.set()
            release_first.wait(2)
            server_session._release_request_lock(handle)

        def second():
            first_acquired.wait(2)
            handle = server_session._acquire_request_lock(sid)
            second_acquired.set()
            server_session._release_request_lock(handle)

        one = threading.Thread(target=first)
        two = threading.Thread(target=second)
        one.start()
        two.start()
        first_acquired.wait(2)
        self.assertFalse(second_acquired.wait(0.05))
        release_first.set()
        one.join()
        two.join()
        self.assertTrue(second_acquired.is_set())

    def test_json_settings_updates_merge_stale_workers(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(engine_facade, 'DATA_DIR', tmp),
            patch.object(engine_facade, '_use_db', return_value=False),
        ):
            engines = [engine_facade.Engine.__new__(engine_facade.Engine) for _ in range(2)]
            for engine in engines:
                engine._lock = threading.RLock()
                engine.disabled_questions = set()
                engine.config = dict(engine._CONFIG_DEFAULTS)
                engine._settings_last_loaded = 0
            engines[0].toggle_question_disabled(1)
            engines[1].toggle_question_disabled(2)
            self.assertEqual(engines[0]._load_disabled_questions(), {1, 2})
            engines[0].set_config('guess_threshold', 0.7)
            engines[1].set_config('compound_ratio', 0.6)
            stored = json.loads(Path(tmp, 'config.json').read_text(encoding='utf-8'))
            self.assertEqual(stored['guess_threshold'], 0.7)
            self.assertEqual(stored['compound_ratio'], 0.6)

    def test_session_three_way_merge_preserves_remote_nested_updates(self):
        original = {'answers': {'0': 1}, 'state': 'open'}
        current = {'answers': {'0': 1, '2': -1}, 'state': 'open', 'remote': True}
        updated = {'answers': {'0': 1, '1': 1}, 'state': 'open'}
        merged = server_session._merge_session_data(current, updated, original)
        self.assertEqual(merged['answers'], {'0': 1, '1': 1, '2': -1})
        self.assertTrue(merged['remote'])

    def test_session_original_is_deep_snapshot(self):
        session = server_session.ServerSession({'answers': {'0': 1}})
        session['answers']['1'] = 1
        self.assertNotIn('1', session.original['answers'])

    def test_concurrent_json_share_links_are_not_lost(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'links.json')
            barrier = threading.Barrier(2)
            errors = []

            def create(name, token):
                try:
                    barrier.wait()
                    share_links.create_link({'name': name}, path=path, token_fn=lambda _n: token)
                except Exception as exc:
                    errors.append(exc)

            threads = [
                threading.Thread(target=create, args=('a', 'Ab12Cd34')),
                threading.Thread(target=create, args=('b', 'Ef56Gh78')),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            self.assertEqual(errors, [])
            self.assertEqual(set(share_links.load_links(path=path)), {'Ab12Cd34', 'Ef56Gh78'})

    def test_db_question_toggle_is_atomic(self):
        calls = []

        class Cursor:
            def execute(self, sql, params=None):
                calls.append((sql, params))

            def fetchone(self):
                return None

        class Conn:
            def cursor(self):
                return Cursor()

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        returned = []
        self.assertTrue(engine_db.toggle_question_disabled(3, get_conn=Conn, put_conn=returned.append))
        self.assertTrue(any('pg_advisory_xact_lock' in sql for sql, _ in calls))
        self.assertTrue(any('RETURNING key' in sql for sql, _ in calls))
        self.assertEqual(len(returned), 1)

    def test_matrix_backup_schema_allows_new_current_questions_and_rejects_missing_source_rows(self):
        app_module.app.config['TESTING'] = True
        client = app_module.app.test_client()
        credentials = base64.b64encode(b'admin:testpass').decode()
        headers = {'Authorization': f'Basic {credentials}'}
        with patch.dict(os.environ, {'ADMIN_PASS': 'testpass'}):
            exported = client.get('/api/admin/export_matrix', headers=headers).get_json()
            self.assertEqual(exported['metadata']['backup_format_version'], 2)
            self.assertTrue(exported['questions'])
            legacy = json.loads(json.dumps(exported))
            legacy.pop('questions')
            legacy['metadata'].pop('backup_format_version')
            self.assertEqual(
                client.post('/api/admin/import_matrix/dry_run', json=legacy, headers=headers).status_code, 200
            )
            legacy_missing = json.loads(json.dumps(legacy))
            legacy_missing['matrix_rows'].pop()
            self.assertEqual(
                client.post('/api/admin/import_matrix/dry_run', json=legacy_missing, headers=headers).status_code, 400
            )
            legacy_conflict = json.loads(json.dumps(legacy))
            legacy_conflict['matrix_rows'][0]['question_text'] = 'conflicting text'
            self.assertEqual(
                client.post('/api/admin/import_matrix/dry_run', json=legacy_conflict, headers=headers).status_code, 400
            )
            removed = exported['questions'].pop()
            removed_index = removed['matrix_index']
            exported['matrix_rows'] = [row for row in exported['matrix_rows'] if row['question_id'] != removed_index]
            response = client.post('/api/admin/import_matrix/dry_run', json=exported, headers=headers)
            self.assertEqual(response.status_code, 200)
            report = response.get_json()
            self.assertTrue(report['complete'])
            self.assertEqual(report['valid_rows'], report['expected_rows'])
            broken = dict(exported)
            broken['matrix_rows'] = exported['matrix_rows'][:-1]
            response = client.post('/api/admin/import_matrix/dry_run', json=broken, headers=headers)
            self.assertEqual(response.status_code, 400)

    def test_json_body_size_limit_returns_json_413(self):
        client = app_module.app.test_client()
        previous = app_module.app.config['MAX_CONTENT_LENGTH']
        app_module.app.config['MAX_CONTENT_LENGTH'] = 64
        try:
            response = client.post(
                '/api/answer',
                data=json.dumps({'answer': 'x' * 200}),
                content_type='application/json',
            )
        finally:
            app_module.app.config['MAX_CONTENT_LENGTH'] = previous
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.get_json()['status'], 'error')

    def test_max_content_length_configuration_is_bounded(self):
        self.assertEqual(app_meta.max_content_length({'MAX_CONTENT_LENGTH': '1024'}), 1024)
        self.assertEqual(app_meta.max_content_length({'MAX_CONTENT_LENGTH': '0'}), app_meta.DEFAULT_MAX_CONTENT_LENGTH)
        self.assertEqual(
            app_meta.max_content_length({'MAX_CONTENT_LENGTH': 'bad'}), app_meta.DEFAULT_MAX_CONTENT_LENGTH
        )

    def test_memory_rate_limit_capacity_preserves_active_bucket(self):
        buckets = {}
        self.assertEqual(rate_limit._memory_bucket(buckets, ('admin', 'a'), 1, 60, 1, 60, 1)[0], False)
        self.assertEqual(rate_limit._memory_bucket(buckets, ('admin', 'a'), 2, 60, 1, 60, 1)[0], True)
        self.assertEqual(rate_limit._memory_bucket(buckets, ('admin', 'b'), 2, 60, 1, 60, 1)[0], True)
        self.assertIn(('admin', 'a'), buckets)
        self.assertNotIn(('admin', 'b'), buckets)
        self.assertEqual(rate_limit._memory_bucket(buckets, ('public', 'b'), 2, 60, 1, 60, 1)[0], False)

    def test_sqlite_rate_limit_capacity_preserves_active_bucket(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'limits.sqlite3')
            self.assertFalse(rate_limit._sqlite_shared_bucket(path, 'admin', 'a', 1, 60, 1, 1)[0])
            self.assertTrue(rate_limit._sqlite_shared_bucket(path, 'admin', 'b', 2, 60, 1, 1)[0])
            import sqlite3

            home = rate_limit._sqlite_shard_path(path, 'admin', 'a', rate_limit._SQLITE_SHARD_COUNT)
            conn = sqlite3.connect(home)
            try:
                rows = conn.execute('SELECT client_ip FROM rate_limits').fetchall()
            finally:
                conn.close()
            self.assertEqual(rows, [('a',)])

    def test_session_request_lock_is_reentrant_until_final_release(self):
        sid = '00000000-0000-0000-0000-000000000001'
        first = server_session._acquire_request_lock(sid)
        second = server_session._acquire_request_lock(sid)
        self.assertIs(first, second)
        server_session._release_request_lock(second)
        acquired = threading.Event()

        def wait_for_lock():
            handle = server_session._acquire_request_lock(sid)
            acquired.set()
            server_session._release_request_lock(handle)

        worker = threading.Thread(target=wait_for_lock)
        worker.start()
        time.sleep(0.05)
        self.assertFalse(acquired.is_set())
        server_session._release_request_lock(first)
        worker.join(2)
        self.assertTrue(acquired.is_set())
        self.assertNotIn(sid, server_session._SESSION_REQUEST_LOCKS)

    def test_sqlite_rate_limit_uses_multiple_shards(self):
        paths = {
            rate_limit._sqlite_shard_path('/tmp/limits.sqlite3', 'scope', f'192.0.2.{index}', 16)
            for index in range(1, 33)
        }
        self.assertGreater(len(paths), 1)
        self.assertTrue(all(path.startswith('/tmp/limits.sqlite3.shard-') for path in paths))

    def test_sqlite_rate_limit_storage_failure_returns_503_and_logs(self):
        logger = Mock()
        with patch.object(rate_limit, '_sqlite_bucket', side_effect=__import__('sqlite3').OperationalError('locked')):
            response = rate_limit.rate_limit(
                'admin',
                1,
                Request(),
                {},
                {},
                lambda value: value,
                lambda _name: True,
                shared_path='/tmp/rate-limit-test.sqlite3',
                logger=logger,
            )
        self.assertEqual(response[1], 503)
        self.assertEqual(response[2]['Retry-After'], '5')
        logger.exception.assert_called_once()

    def test_distributed_session_lock_uses_postgres_advisory_lifecycle(self):
        executed = []

        class Cursor:
            def execute(self, sql, params=None):
                executed.append((sql, params))

        class Conn:
            closed = False

            def cursor(self):
                return Cursor()

            def commit(self):
                pass

            def close(self):
                self.closed = True

        conn = Conn()
        returned = []
        sid = '00000000-0000-0000-0000-000000000099'
        with (
            patch.object(server_session, '_get_conn', return_value=conn),
            patch.object(server_session, '_put_conn', side_effect=returned.append),
        ):
            handle = server_session._acquire_request_lock(sid, distributed_db=True)
            server_session._release_request_lock(handle)
        self.assertIn('pg_advisory_lock', executed[0][0])
        self.assertIn('pg_advisory_unlock', executed[-1][0])
        self.assertEqual(returned, [conn])

    def test_db_matrix_snapshot_uses_one_transaction_and_rolls_back_together(self):
        state = {'exit_exc': None}

        class Cursor:
            pass

        class Conn:
            def cursor(self):
                return Cursor()

            def __enter__(self):
                return self

            def __exit__(self, exc_type, _exc, _tb):
                state['exit_exc'] = exc_type
                return False

        conn = Conn()
        calls = []

        def execute_values(_cursor, sql, rows):
            calls.append((sql, rows))
            if len(calls) == 2:
                raise RuntimeError('matrix write failed')

        returned = []
        with self.assertRaises(RuntimeError):
            engine_db.restore_matrix_snapshot(
                [{'id': 10000, 'name': 'x', 'desc': 'x', 'works': []}],
                [{'fetish_id': 10000, 'question_id': 0, 'yes': 1, 'total': 2}],
                get_conn=lambda: conn,
                put_conn=returned.append,
                execute_values=execute_values,
            )
        self.assertIs(state['exit_exc'], RuntimeError)
        self.assertEqual(returned, [conn])
        self.assertEqual(len(calls), 2)

    def test_backup_validator_rejects_missing_values_and_unknown_version(self):
        payload = {
            'exported_at': '2026-07-13T00:00:00Z',
            'metadata': {'backup_format_version': 2},
            'fetishes': [{'id': 1, 'name': 'one'}],
            'questions': [{'id': 10, 'matrix_index': 0, 'text': 'q'}],
            'matrix_rows': [{'fetish_id': 1, 'question_id': 0, 'yes': 1, 'total': 2}],
        }
        self.assertEqual(validate_matrix_backup.validate(payload)['rows'], 1)
        missing = json.loads(json.dumps(payload))
        missing['matrix_rows'][0].pop('yes')
        with self.assertRaises(ValueError):
            validate_matrix_backup.validate(missing)
        future = json.loads(json.dumps(payload))
        future['metadata']['backup_format_version'] = 999
        with self.assertRaises(ValueError):
            validate_matrix_backup.validate(future)

    def test_matrix_dry_run_rejects_missing_counts_and_unmapped_v2_schema(self):
        app_module.app.config['TESTING'] = True
        client = app_module.app.test_client()
        credentials = base64.b64encode(b'admin:testpass').decode()
        headers = {'Authorization': f'Basic {credentials}'}
        with patch.dict(os.environ, {'ADMIN_PASS': 'testpass'}):
            exported = client.get('/api/admin/export_matrix', headers=headers).get_json()
            missing = json.loads(json.dumps(exported))
            missing['matrix_rows'][0].pop('total')
            self.assertEqual(
                client.post('/api/admin/import_matrix/dry_run', json=missing, headers=headers).status_code, 400
            )
            unmapped = json.loads(json.dumps(exported))
            for index, question in enumerate(unmapped['questions']):
                question['id'] = 1000000 + index
            self.assertEqual(
                client.post('/api/admin/import_matrix/dry_run', json=unmapped, headers=headers).status_code, 400
            )
            unknown = json.loads(json.dumps(exported))
            unknown['metadata']['backup_format_version'] = 999
            self.assertEqual(
                client.post('/api/admin/import_matrix/dry_run', json=unknown, headers=headers).status_code, 400
            )

    def test_backup_schema_rejects_corrupt_questions_and_missing_fetish_name(self):
        payload = {
            'metadata': {'backup_format_version': 2},
            'fetishes': [{'id': 1, 'name': 'one'}],
            'questions': [{'id': 10, 'matrix_index': 0}],
            'matrix_rows': [{'fetish_id': 1, 'question_id': 0, 'yes': 1, 'total': 2}],
        }
        for corrupt in ({}, [], 'bad', 42, None):
            candidate = json.loads(json.dumps(payload))
            candidate.pop('metadata')
            candidate['questions'] = corrupt
            with self.subTest(corrupt=repr(corrupt)), self.assertRaises(ValueError):
                validate_matrix_backup.validate(candidate)
        missing_name = json.loads(json.dumps(payload))
        missing_name['fetishes'][0].pop('name')
        with self.assertRaises(ValueError):
            validate_matrix_backup.validate(missing_name)

    def test_partial_v2_question_mapping_is_not_complete_or_importable(self):
        app_module.app.config['TESTING'] = True
        client = app_module.app.test_client()
        credentials = base64.b64encode(b'admin:testpass').decode()
        headers = {'Authorization': f'Basic {credentials}'}
        with patch.dict(os.environ, {'ADMIN_PASS': 'testpass'}):
            payload = client.get('/api/admin/export_matrix', headers=headers).get_json()
            for index, question in enumerate(payload['questions'][1:], 1):
                question['id'] = 1000000 + index
            dry_run = client.post('/api/admin/import_matrix/dry_run', json=payload, headers=headers)
            self.assertEqual(dry_run.status_code, 200)
            self.assertFalse(dry_run.get_json()['complete'])
            self.assertGreater(dry_run.get_json()['ignored_source_rows'], 0)
            imported = client.post('/api/admin/import_matrix', json=payload, headers=headers)
            self.assertEqual(imported.status_code, 400)

    def test_session_lock_paths_are_bounded_and_nonreentrant_mode_rejects_reentry(self):
        paths = {server_session._session_lock_path(f'00000000-0000-0000-0000-{index:012d}') for index in range(10000)}
        self.assertLessEqual(len(paths), 65536)
        sid = '00000000-0000-0000-0000-000000000777'
        handle = server_session._acquire_request_lock(sid, reentrant=False)
        try:
            with self.assertRaises(RuntimeError):
                server_session._acquire_request_lock(sid, reentrant=False)
            self.assertFalse(handle['released'])
            self.assertEqual(handle['depth'], 1)
        finally:
            server_session._release_request_lock(handle)

    def test_matrix_restore_journal_rolls_forward_consistently(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal_path = os.path.join(tmp, 'journal.json')
            fetishes_path = os.path.join(tmp, 'fetishes.json')
            matrix_path = os.path.join(tmp, 'matrix.json')
            before = {
                'fetishes': [{'id': 1, 'name': 'before'}],
                'matrix': {'yes': [[1.0]], 'total': [[2.0]]},
            }
            after = {
                'fetishes': [{'id': 1, 'name': 'after'}, {'id': 10000, 'name': 'new'}],
                'matrix': {'yes': [[1.5], [2.0]], 'total': [[2.5], [4.0]]},
            }
            atomic_write_json(fetishes_path, after['fetishes'])
            atomic_write_json(matrix_path, before['matrix'])
            atomic_write_json(
                journal_path,
                {
                    'format_version': 1,
                    'before': before,
                    'after': after,
                },
            )
            self.assertTrue(
                engine_persistence.recover_matrix_restore(
                    journal_path,
                    fetishes_path,
                    matrix_path,
                    1,
                    atomic_write=atomic_write_json,
                )
            )
            self.assertFalse(os.path.exists(journal_path))
            with open(fetishes_path, encoding='utf-8') as source:
                self.assertEqual(json.load(source), after['fetishes'])
            with open(matrix_path, encoding='utf-8') as source:
                self.assertEqual(json.load(source), after['matrix'])

    def test_sqlite_hot_shard_can_use_the_full_global_capacity(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'limits.sqlite3')
            by_shard = {}
            index = 0
            while not any(len(values) >= 4 for values in by_shard.values()):
                ip = f'2001:db8::{index}'
                shard_path = rate_limit._sqlite_shard_path(
                    path,
                    'admin',
                    ip,
                    rate_limit._SQLITE_SHARD_COUNT,
                )
                by_shard.setdefault(shard_path, []).append(ip)
                index += 1
            ips = next(values for values in by_shard.values() if len(values) >= 4)
            for ip in ips[:3]:
                self.assertFalse(rate_limit._sqlite_shared_bucket(path, 'admin', ip, 1, 60, 1, 3)[0])
            self.assertTrue(rate_limit._sqlite_shared_bucket(path, 'admin', ips[3], 1, 60, 1, 3)[0])

    def test_db_restore_precomputes_memory_before_committing(self):
        engine = engine_facade.Engine()
        original_fetishes = copy.deepcopy(engine.fetishes)
        original_matrix = copy.deepcopy(engine.matrix)
        rows = [{'fetish_id': 10000, 'question_id': 0, 'yes': 1, 'total': 2}]
        with (
            patch.object(engine_facade, '_use_db', return_value=True),
            patch.object(engine_facade.engine_mutations, 'append_fetish', side_effect=RuntimeError('boom')),
            patch.object(engine_db, 'restore_matrix_snapshot') as restore_db,
        ):
            with self.assertRaises(RuntimeError):
                engine.restore_matrix_snapshot([{'id': 10000, 'name': 'new'}], rows)
        restore_db.assert_not_called()
        self.assertEqual(engine.fetishes, original_fetishes)
        self.assertEqual(engine.matrix, original_matrix)

    def test_settings_reload_preserves_temporary_in_process_override(self):
        engine = app_module.engine
        original_config = copy.deepcopy(engine.config)
        original_snapshot = copy.deepcopy(engine._settings_config_snapshot)
        original_disabled = set(engine.disabled_questions)
        original_loaded = engine._settings_last_loaded
        try:
            engine._settings_config_snapshot = copy.deepcopy(engine.config)
            engine.config['focus_threshold'] = 0.01
            engine._settings_last_loaded = 0
            persisted = copy.deepcopy(original_config)
            persisted['focus_threshold'] = 0.99
            with (
                patch.object(engine, '_load_config', return_value=persisted),
                patch.object(engine, '_load_disabled_questions', return_value=original_disabled),
            ):
                engine._reload_settings_if_stale()
            self.assertEqual(engine.config['focus_threshold'], 0.01)
        finally:
            engine.config = original_config
            engine._settings_config_snapshot = original_snapshot
            engine.disabled_questions = original_disabled
            engine._settings_last_loaded = original_loaded

    def test_daily_report_notification_failure_fails_job(self):
        with (
            patch.object(daily_analytics_report, 'build_daily_report', return_value={'message': 'ok'}),
            patch.object(daily_analytics_report, 'notify', side_effect=RuntimeError('offline')),
        ):
            self.assertEqual(daily_analytics_report.main([]), 1)

    def test_workflow_warning_title_is_stable_and_restore_matches_retention(self):
        backup = Path('.github/workflows/matrix_backup.yml').read_text(encoding='utf-8')
        restore = Path('.github/workflows/restore_matrix.yml').read_text(encoding='utf-8')
        self.assertIn("title = '⚠️ Render PostgreSQL 期限切れ警告'", backup)
        self.assertIn("f'{title} in:title'", backup)
        self.assertIn("'gh', 'issue', 'edit'", backup)
        self.assertIn('curl --fail-with-body', backup)
        self.assertIn('validate_matrix_backup.py data/matrix_backup.json --max-age-days 1', backup)
        self.assertLess(backup.index('Validate backup payload'), backup.index('Upload backup artifact'))
        self.assertIn('validate_matrix_backup.py', restore)
        self.assertIn('validate_matrix_backup.py data/matrix_backup.json --max-age-days 30', restore)
        self.assertNotIn("with open('data/questions.json'", restore)
        self.assertIn("expected = result.get('expected_rows')", restore)


if __name__ == '__main__':
    unittest.main()
