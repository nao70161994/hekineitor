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
