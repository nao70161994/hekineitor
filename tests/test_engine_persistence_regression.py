import os
import sys
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import engine as engine_module
from engine import Engine


def minimal_engine():
    e = Engine.__new__(Engine)
    e._lock = threading.RLock()
    e.fetishes = [
        {'id': 10, 'name': 'A', 'desc': 'a'},
        {'id': 20, 'name': 'B', 'desc': 'b'},
    ]
    e.questions = [
        {'text': 'q0'},
        {'text': 'q1'},
    ]
    e.matrix = {
        'yes': [[1.0, 2.0], [3.0, 4.0]],
        'total': [[5.0, 6.0], [7.0, 8.0]],
    }
    return e


class TestEnginePersistenceRegression(unittest.TestCase):
    def test_matrix_snapshot_returns_deep_copy(self):
        e = minimal_engine()
        snapshot = e._matrix_snapshot()
        e.matrix['yes'][0][0] = 99.0
        e.matrix['total'][1][1] = 100.0
        self.assertEqual(snapshot, {
            'yes': [[1.0, 2.0], [3.0, 4.0]],
            'total': [[5.0, 6.0], [7.0, 8.0]],
        })

    def test_validate_matrix_rows_reports_valid_skipped_and_input_counts(self):
        e = minimal_engine()
        report = e.validate_matrix_rows([
            {'fetish_id': 10, 'question_id': 0, 'yes': 2.0, 'total': 3.0},
            {'fetish_id': 999, 'question_id': 0, 'yes': 1.0, 'total': 1.0},
            {'fetish_id': 20, 'question_id': 999, 'yes': 1.0, 'total': 1.0},
        ])
        self.assertEqual(report, {'valid_rows': 1, 'skipped_rows': 2, 'input_rows': 3})

    def test_import_matrix_local_updates_known_rows_and_saves_once(self):
        e = minimal_engine()
        rows = [
            {'fetish_id': 10, 'question_id': 1, 'yes': 3.5, 'total': 4.5},
            {'fetish_id': 999, 'question_id': 0, 'yes': 1.0, 'total': 1.0},
        ]
        with patch.object(engine_module, '_use_db', return_value=False), \
                patch.object(e, '_save_matrix_file', return_value=None) as save_matrix:
            imported = e.import_matrix(rows)
        self.assertEqual(imported, 1)
        self.assertEqual(e.matrix['yes'][0][1], 3.5)
        self.assertEqual(e.matrix['total'][0][1], 4.5)
        self.assertEqual(e.matrix['yes'][1], [3.0, 4.0])
        save_matrix.assert_called_once_with()

    def test_import_matrix_db_mode_uses_overwrite_import_without_local_save(self):
        e = minimal_engine()
        rows = [
            {'fetish_id': 20, 'question_id': 0, 'yes': 6.0, 'total': 7.0},
        ]
        with patch.object(engine_module, '_use_db', return_value=True), \
                patch.object(e, '_import_to_db', return_value=None) as import_to_db, \
                patch.object(e, '_save_matrix_file', return_value=None) as save_matrix:
            imported = e.import_matrix(rows)
        self.assertEqual(imported, 1)
        self.assertEqual(e.matrix['yes'][1][0], 6.0)
        self.assertEqual(e.matrix['total'][1][0], 7.0)
        import_to_db.assert_called_once_with({1: [(0, 6.0, 7.0)]}, {10: 0, 20: 1})
        save_matrix.assert_not_called()

    def test_collect_matrix_updates_rejects_duplicate_pairs(self):
        e = minimal_engine()
        rows = [
            {'fetish_id': 10, 'question_id': 0, 'yes': 1.0, 'total': 1.0},
            {'fetish_id': 10, 'question_id': 0, 'yes': 1.0, 'total': 1.0},
        ]
        with self.assertRaisesRegex(ValueError, '重複'):
            e.validate_matrix_rows(rows)


class TestEngineDbPersistenceRegression(unittest.TestCase):
    def test_save_to_db_uses_idx_snapshot_and_skips_missing_ids(self):
        e = minimal_engine()
        calls = []

        class Cursor:
            def executemany(self, sql, rows):
                calls.append((sql, rows))

        class Conn:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def cursor(self):
                return Cursor()

        with patch.object(engine_module, '_get_conn', return_value=Conn()) as get_conn, \
                patch.object(engine_module, '_put_conn', return_value=None) as put_conn:
            e._save_to_db(
                {0: [(0, 1.0, 2.0)], 1: [(1, 3.0, 4.0)], 99: [(0, 9.0, 9.0)]},
                {0: 10},
            )

        get_conn.assert_called_once_with()
        put_conn.assert_called_once()
        self.assertEqual(calls[0][1], [(10, 0, 1.0, 2.0)])
        self.assertIn('ON CONFLICT', calls[0][0])

    def test_import_to_db_builds_overwrite_rows_from_idx_map(self):
        e = minimal_engine()
        calls = []

        class Cursor:
            pass

        class Conn:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def cursor(self):
                return Cursor()

        fake_psycopg2 = type('Psycopg2', (), {
            'extras': type('Extras', (), {
                'execute_values': staticmethod(lambda cur, sql, rows: calls.append((sql, rows)))
            })
        })
        with patch.object(engine_module, 'psycopg2', fake_psycopg2, create=True), \
                patch.object(engine_module, '_get_conn', return_value=Conn()), \
                patch.object(engine_module, '_put_conn', return_value=None):
            e._import_to_db({0: [(1, 2.0, 3.0)], 99: [(0, 9.0, 9.0)]}, {10: 0, 20: 1})

        self.assertEqual(calls[0][1], [(10, 1, 2.0, 3.0)])
        self.assertIn('ON CONFLICT', calls[0][0])
        self.assertIn('SET yes_count   = EXCLUDED.yes_count', calls[0][0])
