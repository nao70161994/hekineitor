import os
import sys
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import engine as engine_module
from engine import Engine, work_catalog


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
        self.assertEqual(
            snapshot,
            {
                'yes': [[1.0, 2.0], [3.0, 4.0]],
                'total': [[5.0, 6.0], [7.0, 8.0]],
            },
        )

    def test_work_catalog_snapshot_uses_valid_deep_local_copy(self):
        e = minimal_engine()
        catalog = {
            'schema_version': 1,
            'works_master': [],
            'work_editions': [],
            'work_aliases': [],
            'fetish_work_links': [],
            'compound_work_links': [],
            'review_queue': [],
        }
        e._load_json = lambda name: catalog
        with patch.object(engine_module, '_use_db', return_value=False):
            snapshot = e._work_catalog_snapshot()
        snapshot['works_master'].append({'work_id': 'changed'})
        self.assertEqual(catalog['works_master'], [])

    def test_work_catalog_snapshot_uses_database_repository(self):
        e = minimal_engine()
        expected = {'schema_version': 1}
        with (
            patch.object(engine_module, '_use_db', return_value=True),
            patch.object(
                engine_module.engine_db.db_work_catalog, 'load_catalog', return_value=expected
            ) as load_catalog,
        ):
            self.assertIs(e._work_catalog_snapshot(), expected)
        load_catalog.assert_called_once()

    def test_recommended_works_are_catalog_first_without_legacy_mixing(self):
        e = minimal_engine()
        e.fetishes[0]['works'] = ['legacy A']
        e.fetishes[1]['works'] = ['legacy B']
        catalog = work_catalog.build_catalog_from_inline(
            [
                {
                    'id': 10,
                    'works': [
                        {
                            'title': 'Catalog A',
                            'url': 'https://www.amazon.co.jp/dp/B000000001',
                        }
                    ],
                },
                {'id': 20, 'works': []},
            ]
        )
        e._work_catalog_snapshot = lambda: catalog
        works = e.get_recommended_works(10)
        self.assertEqual(works[0]['title'], 'Catalog A')
        self.assertTrue(works[0]['work_id'].startswith('wrk_'))
        works[0]['title'] = 'mutated'
        self.assertEqual(e.get_recommended_works(10)[0]['title'], 'Catalog A')
        self.assertEqual(e.get_recommended_works(20), [])

    def test_recommended_works_fall_back_to_legacy_when_catalog_is_unavailable(self):
        e = minimal_engine()
        e.fetishes[0]['works'] = ['legacy A']
        e._work_catalog_snapshot = lambda: (_ for _ in ()).throw(ValueError('unavailable'))
        with self.assertLogs('engine.facade', level='ERROR'):
            self.assertEqual(e.get_recommended_works(10), ['legacy A'])

    def test_validate_matrix_rows_reports_valid_skipped_and_input_counts(self):
        e = minimal_engine()
        report = e.validate_matrix_rows(
            [
                {'fetish_id': 10, 'question_id': 0, 'yes': 2.0, 'total': 3.0},
                {'fetish_id': 999, 'question_id': 0, 'yes': 1.0, 'total': 1.0},
                {'fetish_id': 20, 'question_id': 999, 'yes': 1.0, 'total': 1.0},
            ]
        )
        self.assertEqual(report, {'valid_rows': 1, 'skipped_rows': 2, 'input_rows': 3})

    def test_import_matrix_local_updates_known_rows_and_saves_once(self):
        e = minimal_engine()
        rows = [
            {'fetish_id': 10, 'question_id': 1, 'yes': 3.5, 'total': 4.5},
            {'fetish_id': 999, 'question_id': 0, 'yes': 1.0, 'total': 1.0},
        ]
        with (
            patch.object(engine_module, '_use_db', return_value=False),
            patch.object(e, '_save_matrix_file', return_value=None) as save_matrix,
        ):
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
        with (
            patch.object(engine_module, '_use_db', return_value=True),
            patch.object(e, '_import_to_db', return_value=None) as import_to_db,
            patch.object(e, '_save_matrix_file', return_value=None) as save_matrix,
        ):
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

        with (
            patch.object(engine_module, '_get_conn', return_value=Conn()) as get_conn,
            patch.object(engine_module, '_put_conn', return_value=None) as put_conn,
        ):
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

        fake_psycopg2 = type(
            'Psycopg2',
            (),
            {
                'extras': type(
                    'Extras', (), {'execute_values': staticmethod(lambda cur, sql, rows: calls.append((sql, rows)))}
                )
            },
        )
        with (
            patch.object(engine_module, 'psycopg2', fake_psycopg2, create=True),
            patch.object(engine_module, '_get_conn', return_value=Conn()),
            patch.object(engine_module, '_put_conn', return_value=None),
        ):
            e._import_to_db({0: [(1, 2.0, 3.0)], 99: [(0, 9.0, 9.0)]}, {10: 0, 20: 1})

        self.assertEqual(calls[0][1], [(10, 1, 2.0, 3.0)])
        self.assertIn('ON CONFLICT', calls[0][0])
        self.assertIn('SET yes_count   = EXCLUDED.yes_count', calls[0][0])
