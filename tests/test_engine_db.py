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


    def test_default_recommended_works_cover_promoted_seed_gaps(self):
        works = engine_db.default_recommended_works_for_name('激重感情')
        self.assertEqual([work['title'] for work in works], ['ハッピーシュガーライフ', '未来日記', '君に愛されて痛かった'])
        uniform_works = engine_db.default_recommended_works_for_name('制服')
        self.assertEqual([work['title'] for work in uniform_works], ['明日ちゃんのセーラー服', 'その着せ替え人形は恋をする', '響け！ユーフォニアム'])
        self.assertEqual(engine_db.default_recommended_works_for_name('unknown'), [])

    def test_backfill_empty_recommended_works_updates_only_empty_rows(self):
        cursor = FakeCursor()
        cursor.rowcount = 1
        updated = engine_db.backfill_empty_recommended_works(cursor)
        self.assertGreaterEqual(updated, 1)
        sql, params = cursor.executed[0]
        self.assertIn('UPDATE fetishes SET works=%s', sql)
        self.assertIn("works='[]'", sql)
        self.assertEqual(params[1], '激重感情')
        self.assertIn('ハッピーシュガーライフ', params[0])


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



class TestEngineDbMutationAdapters(unittest.TestCase):
    def test_insert_fetish_with_matrix_keeps_id_query_and_matrix_insert_contract(self):
        cursor = FakeCursor(fetchone_values=[(10002,)])
        conn = FakeConn(cursor)
        execute_values_calls = []
        returned = []

        db_id = engine_db.insert_fetish_with_matrix(
            'Name',
            'Desc',
            [2.0, 3.0],
            [4.0, 5.0],
            get_conn=lambda: conn,
            put_conn=returned.append,
            execute_values=lambda cur, sql, rows: execute_values_calls.append((sql, list(rows))),
            player_base_id=10000,
        )

        self.assertEqual(db_id, 10002)
        self.assertIn('SELECT pg_advisory_xact_lock', cursor.executed[0][0])
        self.assertIn('SELECT COALESCE(MAX(id), %s - 1) + 1', cursor.executed[1][0])
        self.assertEqual(cursor.executed[2][1], (10002, 'Name', 'Desc', '[]'))
        self.assertIn('INSERT INTO matrix', execute_values_calls[0][0])
        self.assertEqual(execute_values_calls[0][1], [(10002, 0, 2.0, 4.0), (10002, 1, 3.0, 5.0)])
        self.assertEqual(returned, [conn])

    def test_update_fetish_fields_builds_only_provided_columns(self):
        cursor = FakeCursor()
        conn = FakeConn(cursor)

        engine_db.update_fetish_fields(
            7,
            name='Name',
            works=['作品'],
            get_conn=lambda: conn,
            put_conn=lambda _conn: None,
        )

        sql, params = cursor.executed[0]
        self.assertEqual(sql, 'UPDATE fetishes SET name=%s, works=%s WHERE id=%s')
        self.assertEqual(params, ['Name', '["作品"]', 7])

    def test_delete_fetish_rows_deletes_fetish_then_matrix(self):
        cursor = FakeCursor()
        conn = FakeConn(cursor)

        engine_db.delete_fetish_rows(7, get_conn=lambda: conn, put_conn=lambda _conn: None)

        self.assertEqual(
            [call[0] for call in cursor.executed],
            ['DELETE FROM fetishes WHERE id = %s', 'DELETE FROM matrix WHERE fetish_id = %s'],
        )
        self.assertEqual([call[1] for call in cursor.executed], [(7,), (7,)])

    def test_merge_fetish_rows_db_keeps_matrix_log_and_optional_name_update_contract(self):
        cursor = FakeCursor()
        conn = FakeConn(cursor)

        engine_db.merge_fetish_rows_db(
            1,
            2,
            new_name='Merged',
            keep_desc='Desc',
            get_conn=lambda: conn,
            put_conn=lambda _conn: None,
        )

        executed_sql = [sql for sql, _params in cursor.executed]
        self.assertIn('UPDATE matrix AS m', executed_sql[0])
        self.assertEqual(executed_sql[1], 'DELETE FROM fetishes WHERE id = %s')
        self.assertEqual(executed_sql[2], 'DELETE FROM matrix WHERE fetish_id = %s')
        self.assertIn('INSERT INTO fetish_log', executed_sql[3])
        self.assertEqual(executed_sql[4], 'DELETE FROM fetish_log WHERE fetish_id = %s')
        self.assertEqual(executed_sql[5], 'UPDATE fetishes SET name=%s, "desc"=%s WHERE id=%s')
        self.assertEqual(cursor.executed[5][1], ('Merged', 'Desc', 1))

    def test_promoted_stats_history_repair_reports_and_applies_old_keys(self):
        cursor = FakeCursor(fetchall_values=[
            [('f_guessed_10000', 2, 5), ('f_correct_10000', 1, 2)],
            [('f_guessed_10000', 2, 5), ('f_correct_10000', 1, 2)],
        ])
        conn = FakeConn(cursor)

        report = engine_db.promoted_stats_history_repair_report(
            [(10000, 3)], get_conn=lambda: conn, put_conn=lambda _conn: None,
        )
        self.assertEqual(report['mapping_count'], 1)
        self.assertEqual(report['total_value'], 7)
        self.assertEqual(report['rows'][0]['old_key'], 'f_guessed_10000')
        self.assertEqual(report['rows'][0]['new_key'], 'f_guessed_3')

        applied = engine_db.repair_promoted_stats_history(
            [(10000, 3)], get_conn=lambda: conn, put_conn=lambda _conn: None,
        )
        self.assertTrue(applied['applied'])
        executed_sql = [call[0] for call in cursor.executed]
        self.assertIn('SELECT key, COUNT(*), COALESCE(SUM(value), 0) FROM stats_history WHERE key = ANY(%s) GROUP BY key', executed_sql[0])
        self.assertIn('INSERT INTO stats_history', executed_sql[2])
        temp_key = cursor.executed[2][1][0]
        self.assertTrue(temp_key.startswith('__repair_'))
        self.assertTrue(temp_key.endswith('_f_guessed_10000'))
        self.assertEqual(cursor.executed[2][1][1], 'f_guessed_10000')
        self.assertEqual(cursor.executed[3][0], 'DELETE FROM stats_history WHERE key = %s')
        self.assertEqual(cursor.executed[3][1], ('f_guessed_10000',))
        self.assertIn('INSERT INTO stats_history', executed_sql[8])
        self.assertEqual(cursor.executed[8][1], ('f_guessed_3', temp_key))

    def test_promote_fetish_id_updates_all_id_references(self):
        cursor = FakeCursor()
        conn = FakeConn(cursor)

        engine_db.promote_fetish_id(10000, 3, get_conn=lambda: conn, put_conn=lambda _conn: None)

        executed_sql = [call[0] for call in cursor.executed]
        self.assertEqual(
            executed_sql[:3],
            [
                'UPDATE fetishes  SET id = %s WHERE id = %s',
                'UPDATE matrix    SET fetish_id = %s WHERE fetish_id = %s',
                'UPDATE fetish_log SET fetish_id = %s WHERE fetish_id = %s',
            ],
        )
        self.assertEqual([call[1] for call in cursor.executed[:3]], [(3, 10000), (3, 10000), (3, 10000)])
        self.assertEqual(len(cursor.executed), 9)
        for idx, prefix in enumerate(('f_guessed_', 'f_correct_', 'f_wrong_')):
            insert_sql, insert_params = cursor.executed[3 + idx * 2]
            delete_sql, delete_params = cursor.executed[4 + idx * 2]
            self.assertIn('INSERT INTO stats_history', insert_sql)
            self.assertIn('ON CONFLICT (date, key) DO UPDATE', insert_sql)
            self.assertEqual(insert_params, (f'{prefix}3', f'{prefix}10000'))
            self.assertEqual(delete_sql, 'DELETE FROM stats_history WHERE key = %s')
            self.assertEqual(delete_params, (f'{prefix}10000',))

    def test_promote_player_fetish_to_seed_chooses_id_inside_db_lock(self):
        cursor = FakeCursor(fetchone_values=[(10000,), (3,)])
        conn = FakeConn(cursor)
        returned = []

        new_id = engine_db.promote_player_fetish_to_seed(
            10000,
            player_base_id=100000,
            get_conn=lambda: conn,
            put_conn=returned.append,
        )

        self.assertEqual(new_id, 3)
        self.assertEqual(returned, [conn])
        executed_sql = [call[0] for call in cursor.executed]
        self.assertEqual(executed_sql[0], 'SELECT pg_advisory_xact_lock(%s)')
        self.assertEqual(cursor.executed[0][1], (100000,))
        self.assertEqual(executed_sql[1], 'SELECT id FROM fetishes WHERE id = %s AND id >= %s')
        self.assertIn('generate_series', executed_sql[2])
        self.assertEqual(
            executed_sql[3:6],
            [
                'UPDATE fetishes  SET id = %s WHERE id = %s',
                'UPDATE matrix    SET fetish_id = %s WHERE fetish_id = %s',
                'UPDATE fetish_log SET fetish_id = %s WHERE fetish_id = %s',
            ],
        )
        self.assertEqual([call[1] for call in cursor.executed[3:6]], [(3, 10000), (3, 10000), (3, 10000)])

    def test_promote_player_fetish_to_seed_returns_none_when_old_id_missing(self):
        cursor = FakeCursor(fetchone_values=[None])
        conn = FakeConn(cursor)

        new_id = engine_db.promote_player_fetish_to_seed(
            10000,
            player_base_id=100000,
            get_conn=lambda: conn,
            put_conn=lambda _conn: None,
        )

        self.assertIsNone(new_id)
        self.assertEqual(len(cursor.executed), 2)


class TestEngineDbStatsAdapters(unittest.TestCase):
    def test_increment_and_daily_stats_use_existing_upsert_sql(self):
        cursor = FakeCursor()
        conn = FakeConn(cursor)
        engine_db.increment_stat('play_count', get_conn=lambda: conn, put_conn=lambda _conn: None)
        engine_db.record_daily_stat('play', '2026-05-23', get_conn=lambda: conn, put_conn=lambda _conn: None)

        self.assertIn('ON CONFLICT (key) DO UPDATE SET value = stats.value + 1', cursor.executed[0][0])
        self.assertEqual(cursor.executed[0][1], ('play_count',))
        self.assertIn('ON CONFLICT (date, key) DO UPDATE SET value = stats_history.value + 1', cursor.executed[1][0])
        self.assertEqual(cursor.executed[1][1], ('2026-05-23', 'play'))

    def test_load_stats_and_history_keep_engine_shapes(self):
        cursor = FakeCursor(
            fetchall_values=[
                [('play_count', 2)],
                [('2026-05-23', 'start', 5), ('2026-05-23', 'completion', 3), ('2026-05-23', 'play', 3), ('2026-05-23', 'wrong', 1), ('2026-05-23', 'dropoff', 2)],
            ]
        )
        conn = FakeConn(cursor)

        self.assertEqual(
            engine_db.load_stats(('play_count', 'learn_count'), get_conn=lambda: conn, put_conn=lambda _conn: None),
            {'play_count': 2, 'learn_count': 0},
        )
        self.assertEqual(
            engine_db.load_stats_history(['2026-05-22', '2026-05-23'], get_conn=lambda: conn, put_conn=lambda _conn: None),
            [
                {'date': '2026-05-22', 'start': 0, 'play': 0, 'completion': 0, 'learn': 0, 'correct': 0, 'wrong': 0, 'dropoff': 0},
                {'date': '2026-05-23', 'start': 5, 'play': 3, 'completion': 3, 'learn': 0, 'correct': 0, 'wrong': 1, 'dropoff': 2},
            ],
        )


    def test_load_dropoff_totals_groups_answered_counts(self):
        cursor = FakeCursor(fetchall_values=[[('dropoff', 3), ('dropoff_q_0', 1), ('dropoff_q_3', 2)]])
        conn = FakeConn(cursor)

        self.assertEqual(
            engine_db.load_dropoff_totals('2026-05-20', get_conn=lambda: conn, put_conn=lambda _conn: None),
            {'total': 3, 'by_answered': {0: 1, 3: 2}},
        )
        self.assertIn("key = 'dropoff' OR key LIKE 'dropoff_q_%%'", cursor.executed[0][0])

    def test_feedback_quality_and_fetish_history_loaders_keep_raw_contracts(self):
        cursor = FakeCursor(
            fetchall_values=[
                [('f_guessed_10', 5), ('f_correct_10', 2), ('f_wrong_10', 1)],
                [('2026-05-23', 'f_correct_10', 2)],
                [('q_low_conf_guess', 4)],
            ]
        )
        conn = FakeConn(cursor)

        self.assertEqual(
            engine_db.load_feedback_totals('2026-05-20', get_conn=lambda: conn, put_conn=lambda _conn: None),
            {10: {'guessed': 5, 'correct': 2, 'wrong': 1}},
        )
        self.assertEqual(
            engine_db.load_fetish_history(
                ['2026-05-22', '2026-05-23'],
                'f_correct_10',
                'f_wrong_10',
                get_conn=lambda: conn,
                put_conn=lambda _conn: None,
            ),
            {'2026-05-23': {'f_correct_10': 2}},
        )
        self.assertEqual(
            engine_db.load_quality_event_totals(
                ['2026-05-22', '2026-05-23'],
                ('q_low_conf_guess', 'q_low_conf_wrong'),
                get_conn=lambda: conn,
                put_conn=lambda _conn: None,
            ),
            {'q_low_conf_guess': 4, 'q_low_conf_wrong': 0},
        )

    def test_disabled_questions_and_fetish_log_adapters_keep_contracts(self):
        cursor = FakeCursor(fetchall_values=[[('disabled_q_2',), ('disabled_q_5',)], [(10, 1, 2, 3)]])
        conn = FakeConn(cursor)

        self.assertEqual(engine_db.load_disabled_questions(get_conn=lambda: conn, put_conn=lambda _conn: None), {2, 5})
        engine_db.save_disabled_questions({5, 2}, get_conn=lambda: conn, put_conn=lambda _conn: None)
        engine_db.increment_fetish_log(10, 'correct', get_conn=lambda: conn, put_conn=lambda _conn: None)
        self.assertEqual(
            engine_db.load_fetish_log(get_conn=lambda: conn, put_conn=lambda _conn: None),
            {10: {'guessed': 1, 'correct': 2, 'wrong': 3}},
        )

        sqls = [sql for sql, _params in cursor.executed]
        self.assertIn("SELECT key FROM stats WHERE key LIKE 'disabled_q_%'", sqls)
        self.assertIn("DELETE FROM stats WHERE key LIKE 'disabled_q_%'", sqls)
        self.assertTrue(any('INSERT INTO fetish_log' in sql for sql in sqls))
        self.assertIn('SELECT fetish_id, guessed, correct, wrong FROM fetish_log', sqls)
        with self.assertRaises(ValueError):
            engine_db.increment_fetish_log(10, 'bad', get_conn=lambda: conn, put_conn=lambda _conn: None)


class TestEngineDbSeedAdapters(unittest.TestCase):
    def test_build_seed_matrix_rows_preserves_fetish_question_order(self):
        rows = engine_db.build_seed_matrix_rows(
            [{'id': 10}, {'id': 20}],
            2,
            build_initial_matrix=lambda nf, nq: ([[1.0, 2.0], [3.0, 4.0]], [[5.0, 6.0], [7.0, 8.0]]),
        )
        self.assertEqual(rows, [(10, 0, 1.0, 5.0), (10, 1, 2.0, 6.0), (20, 0, 3.0, 7.0), (20, 1, 4.0, 8.0)])

    def test_seed_matrix_uses_existing_insert_sql(self):
        calls = []
        engine_db.seed_matrix(
            object(),
            [{'id': 10}],
            1,
            execute_values=lambda cur, sql, rows: calls.append((cur, sql, rows)),
            build_initial_matrix=lambda nf, nq: ([[2.0]], [[4.0]]),
        )
        self.assertIn('INSERT INTO matrix (fetish_id, question_id, yes_count, total_count) VALUES %s', calls[0][1])
        self.assertEqual(calls[0][2], [(10, 0, 2.0, 4.0)])
