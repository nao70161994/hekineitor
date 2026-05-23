import unittest

import engine_db


class TestEngineDbHelpers(unittest.TestCase):
    def test_build_save_matrix_rows_prefers_snapshot_and_falls_back_to_fetishes(self):
        fetishes = [{'id': 10}, {'id': 20}]
        self.assertEqual(
            engine_db.build_save_matrix_rows(
                {0: [(1, 2.0, 3.0)], 1: [(0, 4.0, 5.0)]},
                idx_to_db_id={0: 99},
                fetishes=fetishes,
            ),
            [(99, 1, 2.0, 3.0)],
        )
        self.assertEqual(
            engine_db.build_save_matrix_rows({1: [(0, 4.0, 5.0)]}, fetishes=fetishes),
            [(20, 0, 4.0, 5.0)],
        )

    def test_build_import_matrix_rows_uses_inverse_idx_map(self):
        self.assertEqual(
            engine_db.build_import_matrix_rows({1: [(0, 6.0, 7.0)], 9: [(0, 1.0, 1.0)]}, {10: 0, 20: 1}),
            [(20, 0, 6.0, 7.0)],
        )

    def test_save_and_import_skip_connection_when_no_rows(self):
        calls = []
        engine_db.save_matrix_updates({}, None, [], get_conn=lambda: calls.append('get'), put_conn=lambda conn: None)
        engine_db.import_matrix_rows({}, {}, get_conn=lambda: calls.append('get'), put_conn=lambda conn: None, execute_values=None)
        self.assertEqual(calls, [])

    def test_sql_contracts_keep_conflict_modes(self):
        self.assertIn('matrix.yes_count   + EXCLUDED.yes_count', engine_db.SAVE_MATRIX_SQL)
        self.assertIn('SET yes_count   = EXCLUDED.yes_count', engine_db.IMPORT_MATRIX_SQL)



class FakeCursor:
    def __init__(self, *, fetchone_values=None, fetchall_values=None):
        self.executed = []
        self.fetchone_values = list(fetchone_values or [])
        self.fetchall_values = list(fetchall_values or [])

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def executemany(self, sql, rows):
        self.executed.append((sql, list(rows)))

    def fetchone(self):
        return self.fetchone_values.pop(0)

    def fetchall(self):
        return self.fetchall_values.pop(0)


class FakeConn:
    def __init__(self, cursor):
        self.cursor_obj = cursor
        self.entered = False

    def cursor(self):
        return self.cursor_obj

    def __enter__(self):
        self.entered = True
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeEngine:
    questions = [{'text': 'q0'}, {'text': 'q1'}]

    def __init__(self):
        self.seed_calls = []

    def _load_json(self, name):
        assert name == 'fetishes.json'
        return [{'id': 0, 'name': 'Seed', 'desc': 'Desc', 'works': ['Work']}]

    def _seed_db(self, cur, fetishes):
        self.seed_calls.append((cur, fetishes))


class TestEngineDbLoadAndConfigHelpers(unittest.TestCase):
    def test_parse_fetish_rows_decodes_works_and_falls_back_to_empty_list(self):
        self.assertEqual(
            engine_db.parse_fetish_rows([
                (1, 'A', 'desc', '["W"]'),
                (2, 'B', 'desc', '{"bad": true}'),
                (3, 'C', 'desc', 'not-json'),
                (4, 'D', 'desc', None),
            ]),
            [
                {'id': 1, 'name': 'A', 'desc': 'desc', 'works': ['W']},
                {'id': 2, 'name': 'B', 'desc': 'desc', 'works': []},
                {'id': 3, 'name': 'C', 'desc': 'desc', 'works': []},
                {'id': 4, 'name': 'D', 'desc': 'desc', 'works': []},
            ],
        )

    def test_load_fetishes_keeps_select_contract_and_returns_connection(self):
        cursor = FakeCursor(fetchall_values=[[(1, 'A', 'desc', '["W"]')]])
        conn = FakeConn(cursor)
        returned = []

        rows = engine_db.load_fetishes(get_conn=lambda: conn, put_conn=returned.append)

        self.assertEqual(rows, [{'id': 1, 'name': 'A', 'desc': 'desc', 'works': ['W']}])
        self.assertEqual(cursor.executed[0][0], 'SELECT id, name, "desc", works FROM fetishes ORDER BY id')
        self.assertEqual(returned, [conn])

    def test_matrix_from_rows_skips_unknown_fetish_and_out_of_range_question(self):
        matrix = engine_db.matrix_from_rows(
            [{'id': 10}, {'id': 20}],
            [{'text': 'q0'}, {'text': 'q1'}],
            [
                (10, 0, 2.0, 3.0),
                (20, 1, 4.0, 5.0),
                (99, 0, 9.0, 9.0),
                (10, 9, 8.0, 8.0),
            ],
        )
        self.assertEqual(matrix, {'yes': [[2.0, 0.0], [0.0, 4.0]], 'total': [[3.0, 0.0], [0.0, 5.0]]})

    def test_load_matrix_keeps_select_contract_and_returns_connection(self):
        cursor = FakeCursor(fetchall_values=[[(10, 0, 2.0, 3.0)]])
        conn = FakeConn(cursor)
        returned = []

        matrix = engine_db.load_matrix(
            [{'id': 10}],
            [{'text': 'q0'}],
            get_conn=lambda: conn,
            put_conn=returned.append,
        )

        self.assertEqual(matrix, {'yes': [[2.0]], 'total': [[3.0]]})
        self.assertEqual(cursor.executed[0][0], 'SELECT fetish_id, question_id, yes_count, total_count FROM matrix')
        self.assertEqual(returned, [conn])

    def test_load_config_reads_db_and_ignores_unknown_keys(self):
        cursor = FakeCursor(fetchall_values=[[('guess_threshold', '0.8'), ('unknown', '9.9')]])
        conn = FakeConn(cursor)
        values = engine_db.load_config(
            {'guess_threshold': 0.75, 'focus_threshold': 0.4},
            use_db=lambda: True,
            get_conn=lambda: conn,
            put_conn=lambda _conn: None,
            config_path='unused.json',
            read_json=lambda path, default: {'guess_threshold': 0.1},
        )
        self.assertEqual(values, {'guess_threshold': 0.8, 'focus_threshold': 0.4})
        self.assertEqual(cursor.executed[0][0], 'SELECT key, value FROM config')

    def test_load_config_reads_local_json_and_ignores_unknown_keys(self):
        values = engine_db.load_config(
            {'guess_threshold': 0.75, 'focus_threshold': 0.4},
            use_db=lambda: False,
            get_conn=lambda: self.fail('DB connection should not be opened'),
            put_conn=lambda _conn: None,
            config_path='config.json',
            read_json=lambda path, default: {'guess_threshold': '0.81', 'unknown': '9.9'},
        )
        self.assertEqual(values, {'guess_threshold': 0.81, 'focus_threshold': 0.4})

    def test_save_config_value_writes_db_upsert(self):
        cursor = FakeCursor()
        conn = FakeConn(cursor)
        returned = []

        engine_db.save_config_value(
            'guess_threshold',
            0.82,
            use_db=lambda: True,
            get_conn=lambda: conn,
            put_conn=returned.append,
            config_path='unused.json',
            read_json=lambda path, default: {},
            atomic_write=lambda path, payload: self.fail('local writer should not run'),
        )

        sql, params = cursor.executed[0]
        self.assertIn('ON CONFLICT (key) DO UPDATE', sql)
        self.assertEqual(params, ('guess_threshold', '0.82'))
        self.assertEqual(returned, [conn])

    def test_save_config_value_updates_local_json(self):
        writes = []
        engine_db.save_config_value(
            'guess_threshold',
            0.83,
            use_db=lambda: False,
            get_conn=lambda: self.fail('DB connection should not be opened'),
            put_conn=lambda _conn: None,
            config_path='config.json',
            read_json=lambda path, default: {'focus_threshold': 0.4},
            atomic_write=lambda path, payload: writes.append((path, payload)),
        )
        self.assertEqual(writes, [('config.json', {'focus_threshold': 0.4, 'guess_threshold': 0.83})])

    def test_ensure_schema_preserves_table_creation_seed_and_question_migration_contract(self):
        cursor = FakeCursor(
            fetchone_values=[(0,), (0,), (0,)],
            fetchall_values=[[(0,)], [(0,), (1,)]],
        )
        conn = FakeConn(cursor)
        engine = FakeEngine()
        execute_values_calls = []
        returned = []

        engine_db.ensure_schema(
            engine,
            get_conn=lambda: conn,
            put_conn=returned.append,
            execute_values=lambda cur, sql, rows: execute_values_calls.append((sql, list(rows))),
            player_base_id=100000,
            build_initial_matrix=lambda nf, nq: ([[2.0] * nq for _ in range(nf)], [[4.0] * nq for _ in range(nf)]),
        )

        executed_sql = '\n'.join(sql for sql, _params in cursor.executed)
        self.assertIn('CREATE TABLE IF NOT EXISTS fetishes', executed_sql)
        self.assertIn('ALTER TABLE fetishes ADD COLUMN IF NOT EXISTS works', executed_sql)
        self.assertIn('CREATE TABLE IF NOT EXISTS matrix', executed_sql)
        self.assertIn('CREATE TABLE IF NOT EXISTS stats_history', executed_sql)
        self.assertIn('SELECT MAX(question_id) FROM matrix', executed_sql)
        self.assertEqual(len(engine.seed_calls), 1)
        self.assertIn('INSERT INTO fetishes', execute_values_calls[0][0])
        self.assertIn('INSERT INTO matrix', execute_values_calls[1][0])
        self.assertEqual(execute_values_calls[1][1], [(0, 1, 2.0, 4.0), (1, 1, 2.0, 4.0)])
        self.assertEqual(returned, [conn])
