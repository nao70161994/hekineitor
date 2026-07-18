import json
import unittest

from engine import db_work_catalog


class RoutingCursor:
    def __init__(self, *, catalog_count=0, legacy_rows=()):
        self.catalog_count = catalog_count
        self.legacy_rows = list(legacy_rows)
        self.executed = []
        self._result = None

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        normalized = ' '.join(sql.split())
        if normalized == 'SELECT COUNT(*) FROM works_master':
            self._result = [(self.catalog_count,)]
        elif normalized == 'SELECT id, name, "desc", works FROM fetishes ORDER BY id':
            self._result = self.legacy_rows
        else:
            self._result = None

    def fetchone(self):
        return self._result[0]

    def fetchall(self):
        return list(self._result or [])


class TestDbWorkCatalog(unittest.TestCase):
    def test_schema_enforces_identity_references_order_and_pair_canonicalization(self):
        cursor = RoutingCursor()
        db_work_catalog.ensure_schema(cursor)
        sql = '\n'.join(statement for statement, _params in cursor.executed)
        for table in (
            'works_master',
            'work_editions',
            'work_aliases',
            'fetish_work_links',
            'compound_work_links',
            'work_identity_reviews',
        ):
            self.assertIn(f'CREATE TABLE IF NOT EXISTS {table}', sql)
        self.assertIn('work_editions_asin_unique', sql)
        self.assertIn('REFERENCES works_master(work_id)', sql)
        self.assertIn('UNIQUE (fetish_id, position)', sql)
        self.assertIn('CHECK (fetish_id_a < fetish_id_b)', sql)
        self.assertIn('UNIQUE (fetish_id_a, fetish_id_b, position)', sql)

    def test_migrate_legacy_catalog_is_deterministic_and_preserves_order(self):
        legacy_rows = [
            (9, 'Other', 'Desc', '[]'),
            (
                7,
                'Example',
                'Desc',
                json.dumps(
                    [
                        {'title': 'First', 'url': 'https://www.amazon.co.jp/dp/B000000001'},
                        {'title': 'Second', 'url': ''},
                    ]
                ),
            ),
        ]
        compound = {
            '9,7': [
                {'title': 'Pair', 'url': 'https://www.amazon.co.jp/dp/B000000002'},
            ]
        }
        captured = []
        cursor = RoutingCursor(legacy_rows=legacy_rows)

        result = db_work_catalog.migrate_legacy_catalog(
            cursor,
            compound_data=compound,
            execute_values=lambda _cur, sql, rows: captured.append((sql, list(rows))),
        )

        self.assertTrue(result['migrated'])
        self.assertTrue(
            any('pg_advisory_xact_lock' in sql for sql, _params in cursor.executed),
            'migration must serialize concurrent application startups',
        )
        self.assertEqual(result['works_master'], 3)
        fetish_links = next(rows for sql, rows in captured if 'INSERT INTO fetish_work_links' in sql)
        self.assertEqual([row[5] for row in fetish_links], [0, 1])
        compound_links = next(rows for sql, rows in captured if 'INSERT INTO compound_work_links' in sql)
        self.assertEqual([(row[1], row[2], row[6]) for row in compound_links], [(7, 9, 0)])

        repeated = []
        db_work_catalog.migrate_legacy_catalog(
            RoutingCursor(legacy_rows=legacy_rows),
            compound_data=compound,
            execute_values=lambda _cur, sql, rows: repeated.append((sql, list(rows))),
        )
        self.assertEqual(captured, repeated)

    def test_migration_does_not_replace_an_existing_catalog(self):
        cursor = RoutingCursor(catalog_count=1, legacy_rows=[(1, 'Ignored', '', '["Ignored"]')])
        inserts = []
        result = db_work_catalog.migrate_legacy_catalog(
            cursor,
            compound_data={},
            execute_values=lambda _cur, sql, rows: inserts.append((sql, list(rows))),
        )
        self.assertEqual(result, {'migrated': False})
        self.assertEqual(inserts, [])
        self.assertNotIn(
            'SELECT id, name, "desc", works FROM fetishes ORDER BY id',
            [' '.join(sql.split()) for sql, _params in cursor.executed],
        )

    def test_replace_catalog_deletes_children_before_parents(self):
        cursor = RoutingCursor()
        catalog = {
            'schema_version': 1,
            'works_master': [],
            'work_editions': [],
            'work_aliases': [],
            'fetish_work_links': [],
            'compound_work_links': [],
            'review_queue': [],
        }
        counts = db_work_catalog.replace_catalog(cursor, catalog, execute_values=lambda *_args: self.fail())
        deletes = [' '.join(sql.split()) for sql, _params in cursor.executed]
        self.assertEqual(
            deletes,
            [
                'DELETE FROM work_identity_reviews',
                'DELETE FROM compound_work_links',
                'DELETE FROM fetish_work_links',
                'DELETE FROM work_aliases',
                'DELETE FROM work_editions',
                'DELETE FROM works_master',
            ],
        )
        self.assertEqual(counts['works_master'], 0)


if __name__ == '__main__':
    unittest.main()
