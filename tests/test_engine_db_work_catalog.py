import json
import unittest
from pathlib import Path
from unittest.mock import patch

from engine import db_work_catalog, work_catalog


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
            'work_catalog_meta',
            'works_master',
            'work_editions',
            'work_edition_identifiers',
            'work_aliases',
            'fetish_work_links',
            'compound_work_links',
            'work_identity_reviews',
        ):
            self.assertIn(f'CREATE TABLE IF NOT EXISTS {table}', sql)
        self.assertIn('work_editions_asin_unique', sql)
        self.assertIn('ALTER TABLE work_catalog_meta', sql)
        self.assertIn('ADD COLUMN IF NOT EXISTS schema_version', sql)
        self.assertIn('UPDATE work_catalog_meta SET schema_version = 2', sql)
        self.assertIn('REFERENCES works_master(work_id)', sql)
        self.assertIn('REFERENCES work_editions(edition_id) ON DELETE CASCADE', sql)
        self.assertIn('UNIQUE (scheme, authority, value)', sql)
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

    def test_migrate_legacy_catalog_applies_seed_title_responsibilities(self):
        legacy_rows = [
            (
                7,
                'Example',
                'Desc',
                json.dumps(
                    [
                        {
                            'title': '作品名（人物）',
                            'url': 'https://www.amazon.co.jp/dp/B000000001',
                        }
                    ]
                ),
            )
        ]
        captured = []

        db_work_catalog.migrate_legacy_catalog(
            RoutingCursor(legacy_rows=legacy_rows),
            compound_data={},
            seed_overrides={
                'schema_version': 1,
                'title_normalizations': [
                    {
                        'display_title': '作品名（人物）',
                        'canonical_title': '作品名',
                        'context_label': '人物',
                    }
                ],
            },
            execute_values=lambda _cur, sql, rows: captured.append((sql, list(rows))),
        )

        masters = next(rows for sql, rows in captured if 'INSERT INTO works_master' in sql)
        aliases = next(rows for sql, rows in captured if 'INSERT INTO work_aliases' in sql)
        links = next(rows for sql, rows in captured if 'INSERT INTO fetish_work_links' in sql)
        self.assertEqual(masters[0][1], '作品名')
        self.assertEqual(aliases[0][2], '作品名（人物）')
        self.assertEqual(links[0][6], '人物')

    def test_migrate_legacy_catalog_applies_corrections_after_review(self):
        legacy_rows = [(7, 'Example', 'Desc', json.dumps(['作品']))]
        corrections = {'schema_version': 1, 'catalog_schema_version': 1, 'corrections': []}
        observed = []

        def apply(catalog, manifest):
            observed.append((catalog, manifest))
            return catalog

        with patch.object(db_work_catalog, 'apply_catalog_corrections', side_effect=apply):
            db_work_catalog.migrate_legacy_catalog(
                RoutingCursor(legacy_rows=legacy_rows),
                compound_data={},
                review_decisions={'schema_version': 1, 'reviewed_at': '2026-07-29', 'decisions': []},
                corrections=corrections,
                execute_values=lambda _cur, _sql, _rows: None,
            )

        self.assertEqual(len(observed), 1)
        self.assertIs(observed[0][1], corrections)
        self.assertEqual(observed[0][0]['works_master'][0]['canonical_title'], '作品')

    def test_fresh_migration_reverses_corrected_inline_to_the_stable_checked_catalog(self):
        data = Path(__file__).resolve().parents[1] / 'data'
        fetishes = json.loads((data / 'fetishes.json').read_text(encoding='utf-8'))
        compounds = json.loads((data / 'compound_works.json').read_text(encoding='utf-8'))
        seed = json.loads((data / 'work_catalog_seed_overrides.json').read_text(encoding='utf-8'))
        review = json.loads((data / 'work_catalog_review_decisions.json').read_text(encoding='utf-8'))
        corrections = json.loads((data / 'work_catalog_corrections.json').read_text(encoding='utf-8'))
        bibliography = json.loads((data / 'work_catalog_bibliography.json').read_text(encoding='utf-8'))
        checked_catalog = json.loads((data / 'work_catalog.json').read_text(encoding='utf-8'))
        projection = work_catalog.project_approved_inline_corrections(
            fetishes,
            compound_rows=compounds,
            corrections=corrections,
        )
        legacy_rows = [
            (
                row['id'],
                row['name'],
                row['desc'],
                json.dumps(row.get('works') or [], ensure_ascii=False),
            )
            for row in projection['fetishes']
        ]
        captured = []

        with patch.object(
            db_work_catalog,
            'replace_catalog',
            side_effect=lambda _cur, catalog, **_kwargs: captured.append(catalog) or {},
        ):
            db_work_catalog.migrate_legacy_catalog(
                RoutingCursor(legacy_rows=legacy_rows),
                compound_data=projection['compound_rows'],
                execute_values=lambda *_args: None,
                seed_overrides=seed,
                review_decisions=review,
                corrections=corrections,
                bibliography=bibliography,
            )

        self.assertEqual(len(captured), 1)
        self.assertEqual(
            work_catalog.catalog_digest(captured[0]),
            work_catalog.catalog_digest(work_catalog.upgrade_catalog_schema(checked_catalog)),
        )

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

    def test_load_catalog_reads_a_valid_repeatable_snapshot(self):
        identifier = work_catalog.build_edition_identifier(
            'wed_1', scheme='isbn', authority='isbn', value='9784063409116'
        )
        results = iter(
            [
                [('wrk_1', 'Work', 'work', '', 'active')],
                [('wed_1', 'wrk_1', 'B000000001', 'https://www.amazon.co.jp/dp/B000000001', '', '', '', 'active')],
                [
                    (
                        identifier['identifier_id'],
                        identifier['edition_id'],
                        identifier['scheme'],
                        identifier['authority'],
                        identifier['value'],
                    )
                ],
                [],
                [('fwl_1', 1, 'wrk_1', 'wed_1', None, 0, '', '')],
                [],
                [],
            ]
        )

        class Cursor:
            def __init__(self):
                self.executed = []
                self.rows = []

            def execute(self, sql, params=None):
                self.executed.append((sql, params))
                if not sql.startswith('SET TRANSACTION'):
                    self.rows = next(results)

            def fetchall(self):
                return self.rows

        cursor = Cursor()

        class Conn:
            def cursor(self):
                return cursor

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        conn = Conn()
        returned = []
        catalog = db_work_catalog.load_catalog(get_conn=lambda: conn, put_conn=returned.append)
        self.assertEqual(catalog['works_master'][0]['work_id'], 'wrk_1')
        self.assertEqual(catalog['fetish_work_links'][0]['edition_id'], 'wed_1')
        self.assertEqual(
            catalog['work_edition_identifiers'],
            [
                {
                    'identifier_id': identifier['identifier_id'],
                    'edition_id': 'wed_1',
                    'scheme': 'isbn',
                    'authority': 'isbn',
                    'value': '9784063409116',
                }
            ],
        )
        self.assertEqual(catalog['schema_version'], 2)
        self.assertIn('REPEATABLE READ READ ONLY', cursor.executed[0][0])
        self.assertEqual(returned, [conn])

    def test_replace_catalog_upgrades_v1_and_deletes_children_before_parents(self):
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
                'DELETE FROM work_edition_identifiers',
                'DELETE FROM work_editions',
                'DELETE FROM works_master',
                'UPDATE work_catalog_meta SET revision = revision + 1, schema_version = 2 WHERE singleton = TRUE',
            ],
        )
        self.assertEqual(counts['works_master'], 0)
        self.assertEqual(counts['work_edition_identifiers'], 0)

    def test_replace_catalog_inserts_identifiers_after_editions_and_reports_count(self):
        cursor = RoutingCursor()
        identifier = work_catalog.build_edition_identifier(
            'wed_1', scheme='isbn', authority='isbn', value='9784063409116'
        )
        catalog = {
            'schema_version': 2,
            'works_master': [
                {
                    'work_id': 'wrk_1',
                    'canonical_title': 'Work',
                    'normalized_title': 'work',
                    'media_type': '',
                    'status': 'active',
                }
            ],
            'work_editions': [
                {
                    'edition_id': 'wed_1',
                    'work_id': 'wrk_1',
                    'asin': '',
                    'canonical_url': '',
                    'edition_title': '',
                    'publisher': '',
                    'format': 'paperback',
                    'status': 'active',
                }
            ],
            'work_edition_identifiers': [identifier],
            'work_aliases': [],
            'fetish_work_links': [],
            'compound_work_links': [],
            'review_queue': [],
        }
        inserted = []

        counts = db_work_catalog.replace_catalog(
            cursor,
            catalog,
            execute_values=lambda _cur, sql, rows: inserted.append((sql, list(rows))),
        )

        edition_index = next(i for i, (sql, _rows) in enumerate(inserted) if 'INSERT INTO work_editions' in sql)
        identifier_index = next(
            i for i, (sql, _rows) in enumerate(inserted) if 'INSERT INTO work_edition_identifiers' in sql
        )
        self.assertLess(edition_index, identifier_index)
        identifier_rows = inserted[identifier_index][1]
        self.assertEqual(
            identifier_rows,
            [(identifier['identifier_id'], 'wed_1', 'isbn', 'isbn', '9784063409116')],
        )
        self.assertEqual(counts['work_edition_identifiers'], 1)


if __name__ == '__main__':
    unittest.main()
