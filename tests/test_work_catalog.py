import copy
import json
import unittest
from pathlib import Path

from engine import work_catalog
from work_utils import work_title

ROOT = Path(__file__).resolve().parents[1]


class WorkCatalogMigrationTests(unittest.TestCase):
    def test_same_asin_shares_stable_work_and_edition_but_preserves_alias(self):
        fetishes = [
            {
                'id': 1,
                'works': [
                    {'title': 'Future Diary', 'url': 'https://www.amazon.co.jp/dp/B00K6THSBE?tag=x'},
                ],
            },
            {
                'id': 2,
                'works': [
                    {'title': '未来日記', 'url': 'https://www.amazon.co.jp/dp/B00K6THSBE?tag=x'},
                ],
            },
        ]

        first = work_catalog.build_catalog_from_inline(fetishes)
        second = work_catalog.build_catalog_from_inline(copy.deepcopy(fetishes))

        self.assertEqual(first, second)
        self.assertEqual(len(first['works_master']), 1)
        self.assertEqual(len(first['work_editions']), 1)
        self.assertEqual(len(first['work_aliases']), 1)
        links = first['fetish_work_links']
        self.assertEqual(links[0]['work_id'], links[1]['work_id'])
        self.assertEqual(links[0]['edition_id'], links[1]['edition_id'])
        materialized = work_catalog.materialize_fetish_works(first)
        self.assertEqual(materialized[1][0]['title'], 'Future Diary')
        self.assertEqual(materialized[2][0]['title'], '未来日記')
        self.assertTrue(materialized[1][0]['work_id'].startswith('wrk_'))
        self.assertTrue(materialized[1][0]['edition_id'].startswith('wed_'))

    def test_different_asins_are_not_merged_and_enter_conflict_review(self):
        fetishes = [
            {
                'id': 1,
                'works': [
                    {'title': '作品（漫画）', 'url': 'https://www.amazon.co.jp/dp/B000000001'},
                    {'title': '作品', 'url': 'https://www.amazon.co.jp/dp/B000000002'},
                ],
            }
        ]

        catalog = work_catalog.build_catalog_from_inline(fetishes)

        self.assertEqual(len(catalog['works_master']), 2)
        self.assertEqual(len(catalog['work_editions']), 2)
        self.assertEqual(len(catalog['review_queue']), 1)
        review = catalog['review_queue'][0]
        self.assertEqual(review['review_type'], 'normalization_conflict')
        self.assertEqual(review['asins'], ['B000000001', 'B000000002'])
        self.assertEqual(review['status'], 'pending')

    def test_catalog_materialization_preserves_seed_titles_urls_and_order(self):
        fetishes = json.loads((ROOT / 'data' / 'fetishes.json').read_text())
        compounds = json.loads((ROOT / 'data' / 'compound_works.json').read_text())
        compound_rows = []
        for key, works in compounds.items():
            id_a, id_b = key.split(',', 1)
            compound_rows.append({'key': key, 'id_a': int(id_a), 'id_b': int(id_b), 'works': works})
        catalog = work_catalog.build_catalog_from_inline(fetishes, compound_rows=compound_rows)

        fetish_works = work_catalog.materialize_fetish_works(catalog)
        compound_works = work_catalog.materialize_compound_works(catalog)
        for fetish in fetishes:
            legacy = [
                (work_title(work), work.get('url', '') if isinstance(work, dict) else '')
                for work in fetish.get('works', [])
            ]
            migrated = [(work['title'], work['url']) for work in fetish_works.get(fetish['id'], [])]
            self.assertEqual(migrated, legacy, fetish['id'])
        for key, works in compounds.items():
            legacy = [(work_title(work), work.get('url', '') if isinstance(work, dict) else '') for work in works]
            migrated = [(work['title'], work['url']) for work in compound_works.get(key, [])]
            self.assertEqual(migrated, legacy, key)

    def test_checked_in_catalog_matches_deterministic_migration(self):
        from scripts.build_work_catalog import build_catalog

        checked_in = json.loads((ROOT / 'data' / 'work_catalog.json').read_text())
        self.assertEqual(checked_in, build_catalog())

    def test_builder_rejects_unknown_or_same_compound_fetish(self):
        fetishes = [{'id': 1, 'name': 'A', 'desc': '', 'works': []}]
        with self.assertRaisesRegex(ValueError, 'unknown fetish ids'):
            work_catalog.build_catalog_from_inline(
                fetishes,
                compound_rows=[{'id_a': 1, 'id_b': 2, 'works': ['Work']}],
            )
        with self.assertRaisesRegex(ValueError, 'two different fetishes'):
            work_catalog.build_catalog_from_inline(
                fetishes,
                compound_rows=[{'id_a': 1, 'id_b': 1, 'works': ['Work']}],
            )

    def test_validation_rejects_broken_references_and_duplicate_positions(self):
        catalog = work_catalog.build_catalog_from_inline(
            [{'id': 1, 'works': [{'title': 'A', 'url': 'https://www.amazon.co.jp/dp/B000000001'}]}]
        )
        broken = copy.deepcopy(catalog)
        broken['fetish_work_links'][0]['work_id'] = 'wrk_missing'
        with self.assertRaisesRegex(ValueError, 'unknown work_id'):
            work_catalog.validate_catalog(broken)

        duplicate_position = copy.deepcopy(catalog)
        duplicate = copy.deepcopy(duplicate_position['fetish_work_links'][0])
        duplicate['link_id'] = 'fwl_duplicate'
        duplicate_position['fetish_work_links'].append(duplicate)
        with self.assertRaisesRegex(ValueError, 'duplicate owner position'):
            work_catalog.validate_catalog(duplicate_position)

        broken_review = copy.deepcopy(catalog)
        broken_review['review_queue'] = [
            {
                'review_id': 'wrv_broken',
                'work_ids': ['wrk_missing'],
            }
        ]
        with self.assertRaisesRegex(ValueError, 'review queue references unknown work_id'):
            work_catalog.validate_catalog(broken_review)

        negative_position = copy.deepcopy(catalog)
        negative_position['fetish_work_links'][0]['position'] = -1
        with self.assertRaisesRegex(ValueError, 'negative position'):
            work_catalog.validate_catalog(negative_position)

        with self.assertRaisesRegex(ValueError, 'unknown fetish ids'):
            work_catalog.validate_catalog_fetish_references(catalog, {999})

    def test_unsafe_url_is_not_materialized(self):
        catalog = work_catalog.build_catalog_from_inline(
            [{'id': 1, 'works': [{'title': 'A', 'url': 'javascript:alert(1)'}]}]
        )
        materialized = work_catalog.materialize_fetish_works(catalog)
        self.assertEqual(materialized[1][0]['url'], '')
        self.assertIsNone(materialized[1][0]['edition_id'])

    def test_replace_fetish_works_only_replaces_target_owner(self):
        original = work_catalog.build_catalog_from_inline(
            [
                {'id': 1, 'works': [{'title': 'A', 'url': 'https://www.amazon.co.jp/dp/B000000001'}]},
                {'id': 2, 'works': [{'title': 'B', 'url': 'https://www.amazon.co.jp/dp/B000000002'}]},
            ],
            compound_rows=[{'id_a': 1, 'id_b': 2, 'works': ['Compound']}],
        )
        before = copy.deepcopy(original)
        original['fetish_work_links'][1]['context_label'] = 'keep'

        updated = work_catalog.replace_fetish_works(
            original,
            1,
            [
                {'title': 'B alias', 'url': 'https://www.amazon.co.jp/dp/B000000002'},
                {'title': 'C', 'url': 'https://www.amazon.co.jp/dp/B000000003'},
            ],
        )

        self.assertEqual(before['fetish_work_links'][0]['work_id'], original['fetish_work_links'][0]['work_id'])
        self.assertEqual(original['fetish_work_links'][1]['context_label'], 'keep')
        self.assertEqual(
            [work['title'] for work in work_catalog.materialize_fetish_works(updated)[1]],
            ['B alias', 'C'],
        )
        owner_two = [row for row in updated['fetish_work_links'] if row['fetish_id'] == 2]
        self.assertEqual(owner_two[0]['context_label'], 'keep')
        self.assertEqual(
            work_catalog.materialize_compound_works(updated),
            work_catalog.materialize_compound_works(original),
        )

    def test_replace_work_reuses_edition_and_preserves_catalog_metadata(self):
        catalog = work_catalog.build_catalog_from_inline(
            [
                {'id': 1, 'works': []},
                {'id': 2, 'works': [{'title': 'Original', 'url': 'https://www.amazon.co.jp/dp/B000000001'}]},
            ]
        )
        catalog['works_master'][0]['media_type'] = 'manga'
        catalog['work_editions'][0]['format'] = 'kindle'
        original_work_id = catalog['works_master'][0]['work_id']
        original_edition_id = catalog['work_editions'][0]['edition_id']

        updated = work_catalog.replace_fetish_works(
            catalog,
            1,
            [{'title': 'Localized', 'url': 'https://www.amazon.co.jp/dp/B000000001'}],
        )
        materialized = work_catalog.materialize_fetish_works(updated)[1][0]

        self.assertEqual(materialized['title'], 'Localized')
        self.assertEqual(materialized['work_id'], original_work_id)
        self.assertEqual(materialized['edition_id'], original_edition_id)
        self.assertEqual(updated['works_master'][0]['media_type'], 'manga')
        self.assertEqual(updated['work_editions'][0]['format'], 'kindle')

    def test_replace_compound_works_is_canonical_and_empty_deletes_links(self):
        catalog = work_catalog.build_catalog_from_inline(
            [{'id': 1, 'works': []}, {'id': 2, 'works': []}],
            compound_rows=[{'id_a': 1, 'id_b': 2, 'works': ['Old']}],
        )
        updated = work_catalog.replace_compound_works(catalog, 2, 1, ['New'])
        self.assertEqual(
            [work['title'] for work in work_catalog.materialize_compound_works(updated)['1,2']],
            ['New'],
        )
        deleted = work_catalog.replace_compound_works(updated, 1, 2, [])
        self.assertNotIn('1,2', work_catalog.materialize_compound_works(deleted))

    def test_new_conflict_resets_stale_review_decision(self):
        catalog = work_catalog.build_catalog_from_inline(
            [
                {
                    'id': 1,
                    'works': [
                        {'title': 'Same (manga)', 'url': 'https://www.amazon.co.jp/dp/B000000001'},
                        {'title': 'Same', 'url': 'https://www.amazon.co.jp/dp/B000000002'},
                    ],
                },
                {'id': 2, 'works': []},
            ]
        )
        review = catalog['review_queue'][0]
        review.update({'status': 'resolved', 'decision': 'keep_separate', 'version': 4})

        updated = work_catalog.replace_fetish_works(
            catalog,
            2,
            [{'title': 'Same (novel)', 'url': 'https://www.amazon.co.jp/dp/B000000003'}],
        )
        updated_review = updated['review_queue'][0]

        self.assertEqual(updated_review['status'], 'pending')
        self.assertEqual(updated_review['decision'], '')
        self.assertEqual(updated_review['version'], 5)
        self.assertEqual(len(updated_review['work_ids']), 3)
        self.assertEqual(updated_review['asins'], ['B000000001', 'B000000002', 'B000000003'])

    def test_replacement_rejects_duplicate_work_identity(self):
        catalog = work_catalog.build_catalog_from_inline([{'id': 1, 'works': []}])
        with self.assertRaisesRegex(ValueError, 'duplicate work identity'):
            work_catalog.replace_fetish_works(catalog, 1, ['Same', 'Same'])


if __name__ == '__main__':
    unittest.main()
