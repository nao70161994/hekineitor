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
        correction_manifests = tuple(
            json.loads((ROOT / 'data' / name).read_text(encoding='utf-8'))
            for name in (
                'work_catalog_corrections.json',
                'work_catalog_corrections_batch2.json',
                'work_catalog_link_bindings_batch2.json',
            )
        )
        source = work_catalog.project_approved_inline_correction_manifests(
            fetishes,
            compound_rows=compounds,
            correction_manifests=correction_manifests,
            direction='reverse',
        )
        fetishes, compounds = source['fetishes'], source['compound_rows']

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

    def test_checked_phase2_bibliography_is_idempotent_validated_and_preserves_raw_parity(self):
        catalog = json.loads((ROOT / 'data' / 'work_catalog.json').read_text(encoding='utf-8'))
        manifests = [
            json.loads((ROOT / 'data' / 'work_catalog_bibliography.json').read_text(encoding='utf-8')),
            json.loads((ROOT / 'data' / 'work_catalog_bibliography_batch2.json').read_text(encoding='utf-8')),
        ]
        manifest = manifests[1]
        reapplied, counts = work_catalog.apply_bibliography_manifest(catalog, manifest)

        self.assertEqual(reapplied, catalog)
        self.assertEqual(counts['entry_count'], len(manifest['entries']))
        self.assertEqual(counts['work_update_count'], 0)
        expected_identifier_values = {'9784063409116', '9784799211441'}
        for bibliography in manifests:
            for entry in bibliography['entries']:
                edition = entry.get('edition') or {}
                if edition.get('isbn'):
                    expected_identifier_values.add(work_catalog.normalize_isbn(edition['isbn']))
                elif edition.get('identifier'):
                    expected_identifier_values.add(
                        work_catalog.normalize_edition_identifier(**edition['identifier'])[2]
                    )
        self.assertEqual(len(catalog['work_edition_identifiers']), 25)
        self.assertEqual(
            {row['value'] for row in catalog['work_edition_identifiers']},
            expected_identifier_values,
        )
        self.assertNotIn('4199007804', {row['value'] for row in catalog['work_edition_identifiers']})
        self.assertEqual(sum(bool(row['media_type']) for row in catalog['works_master']), 31)
        identified_editions = {row['edition_id'] for row in catalog['work_edition_identifiers']}
        self.assertTrue(
            all(
                row.get('edition_title') and row.get('publisher')
                for row in catalog['work_editions']
                if row['edition_id'] in identified_editions
            )
        )

        fetishes = json.loads((ROOT / 'data' / 'fetishes.json').read_text(encoding='utf-8'))
        compounds = json.loads((ROOT / 'data' / 'compound_works.json').read_text(encoding='utf-8'))
        parity = work_catalog.catalog_parity_report(catalog, fetishes, compound_rows=compounds)
        self.assertTrue(parity['automated_parity_ok'])
        self.assertEqual(parity['mismatch_count'], 0)

        seed = json.loads((ROOT / 'data' / 'work_catalog_seed_overrides.json').read_text(encoding='utf-8'))
        normalized = work_catalog.apply_seed_overrides(catalog, seed)
        normalized_reapplied, normalized_counts = work_catalog.apply_bibliography_manifest(normalized, manifest)
        self.assertEqual(normalized_reapplied, normalized)
        self.assertEqual(normalized_counts['work_update_count'], 0)
        self.assertEqual(normalized_counts['edition_count'], 0)
        self.assertEqual(normalized_counts['identifier_count'], 0)

    @staticmethod
    def _bibliography_case(title='Work'):
        catalog = work_catalog.build_catalog_from_inline([{'id': 1, 'works': [title]}])
        expected = copy.deepcopy(catalog['works_master'][0])
        target = {**expected, 'media_type': 'book'}
        return catalog, expected, target

    @staticmethod
    def _bibliography_manifest(expected, target, edition, entry_id='bibliography-entry'):
        return {
            'schema_version': 1,
            'catalog_schema_version': 2,
            'entries': [
                {
                    'entry_id': entry_id,
                    'expected_work': expected,
                    'target_work': target,
                    'edition': edition,
                }
            ],
        }

    def test_bibliography_legacy_isbn_remains_canonical_and_idempotent(self):
        catalog, expected, target = self._bibliography_case()
        manifest = self._bibliography_manifest(
            expected,
            target,
            {
                'canonical_url': 'https://example.com/isbn-edition',
                'edition_title': 'Work paperback',
                'publisher': 'Example Press',
                'format': 'paperback',
                'isbn': '4-08-873665-6',
            },
        )

        updated, counts = work_catalog.apply_bibliography_manifest(catalog, manifest)

        self.assertEqual(counts['edition_count'], 1)
        self.assertEqual(counts['identifier_count'], 1)
        self.assertEqual(
            updated['work_edition_identifiers'],
            [
                work_catalog.build_edition_identifier(
                    updated['work_editions'][0]['edition_id'],
                    scheme='isbn',
                    authority='isbn',
                    value='9784088736655',
                )
            ],
        )
        reapplied, reapplied_counts = work_catalog.apply_bibliography_manifest(updated, manifest)
        self.assertEqual(reapplied, updated)
        self.assertEqual(reapplied_counts['work_update_count'], 0)
        self.assertEqual(reapplied_counts['edition_count'], 0)
        self.assertEqual(reapplied_counts['identifier_count'], 0)

    def test_bibliography_generic_identifier_is_canonical_and_idempotent(self):
        catalog, expected, target = self._bibliography_case()
        manifest = self._bibliography_manifest(
            expected,
            target,
            {
                'canonical_url': 'https://doi.org/10.1234/example',
                'edition_title': 'Work online edition',
                'publisher': 'Example Press',
                'format': 'digital',
                'identifier': {
                    'scheme': ' DOI ',
                    'authority': ' CrossRef ',
                    'value': ' 10.1234/Example ',
                },
            },
        )

        updated, counts = work_catalog.apply_bibliography_manifest(catalog, manifest)

        self.assertEqual(counts['edition_count'], 1)
        self.assertEqual(counts['identifier_count'], 1)
        identifier = updated['work_edition_identifiers'][0]
        self.assertEqual(identifier['scheme'], 'doi')
        self.assertEqual(identifier['authority'], 'crossref')
        self.assertEqual(identifier['value'], '10.1234/Example')
        reapplied, reapplied_counts = work_catalog.apply_bibliography_manifest(updated, manifest)
        self.assertEqual(reapplied, updated)
        self.assertEqual(reapplied_counts['work_update_count'], 0)
        self.assertEqual(reapplied_counts['edition_count'], 0)
        self.assertEqual(reapplied_counts['identifier_count'], 0)

    def test_bibliography_extends_an_applied_evidence_entry_with_missing_edition_parts(self):
        catalog, expected, _ = self._bibliography_case('Old Work Title')
        target = {
            **expected,
            'canonical_title': 'Canonical Work Title',
            'normalized_title': work_catalog.normalized_work_title('Canonical Work Title'),
            'media_type': 'book',
        }
        evidence_manifest = {
            'schema_version': 1,
            'catalog_schema_version': 2,
            'entries': [
                {
                    'entry_id': 'progressive-entry',
                    'expected_work': expected,
                    'target_work': target,
                    'evidence_url': 'https://example.com/work-evidence',
                }
            ],
        }
        evidence_applied, evidence_counts = work_catalog.apply_bibliography_manifest(catalog, evidence_manifest)
        expected_aliases = copy.deepcopy(evidence_applied['work_aliases'])
        self.assertEqual(evidence_counts['work_update_count'], 1)
        self.assertEqual(evidence_counts['edition_count'], 0)
        self.assertEqual(len(expected_aliases), 1)

        edition = {
            'canonical_url': 'https://example.com/progressive-edition',
            'edition_title': 'Canonical Work edition',
            'publisher': 'Example Press',
            'format': 'paperback',
        }
        edition_manifest = self._bibliography_manifest(
            expected,
            target,
            edition,
            entry_id='progressive-entry',
        )
        edition_applied, edition_counts = work_catalog.apply_bibliography_manifest(
            evidence_applied,
            edition_manifest,
        )
        self.assertEqual(edition_counts['work_update_count'], 0)
        self.assertEqual(edition_counts['edition_count'], 1)
        self.assertEqual(edition_counts['identifier_count'], 0)
        self.assertEqual(edition_applied['work_aliases'], expected_aliases)

        identified_manifest = self._bibliography_manifest(
            expected,
            target,
            {
                **edition,
                'identifier': {
                    'scheme': 'doi',
                    'authority': 'crossref',
                    'value': '10.1234/progressive',
                },
            },
            entry_id='progressive-entry',
        )
        identified, identifier_counts = work_catalog.apply_bibliography_manifest(
            edition_applied,
            identified_manifest,
        )
        self.assertEqual(identifier_counts['work_update_count'], 0)
        self.assertEqual(identifier_counts['edition_count'], 0)
        self.assertEqual(identifier_counts['identifier_count'], 1)
        self.assertEqual(identified['work_aliases'], expected_aliases)

        reapplied, reapplied_counts = work_catalog.apply_bibliography_manifest(identified, identified_manifest)
        self.assertEqual(reapplied, identified)
        self.assertEqual(reapplied_counts['work_update_count'], 0)
        self.assertEqual(reapplied_counts['edition_count'], 0)
        self.assertEqual(reapplied_counts['identifier_count'], 0)

    def test_bibliography_allows_an_edition_without_an_identifier(self):
        catalog, expected, target = self._bibliography_case()
        manifest = self._bibliography_manifest(
            expected,
            target,
            {
                'canonical_url': 'https://example.com/unidentified-edition',
                'edition_title': 'Work archival edition',
                'publisher': 'Example Press',
                'format': 'archive',
            },
        )

        updated, counts = work_catalog.apply_bibliography_manifest(catalog, manifest)

        self.assertEqual(len(updated['work_editions']), 1)
        self.assertEqual(updated['work_edition_identifiers'], [])
        self.assertEqual(counts['edition_count'], 1)
        self.assertEqual(counts['identifier_count'], 0)
        reapplied, reapplied_counts = work_catalog.apply_bibliography_manifest(updated, manifest)
        self.assertEqual(reapplied, updated)
        self.assertEqual(reapplied_counts['work_update_count'], 0)
        self.assertEqual(reapplied_counts['edition_count'], 0)
        self.assertEqual(reapplied_counts['identifier_count'], 0)

    def test_bibliography_rejects_ambiguous_or_invalid_identifiers(self):
        cases = {
            'both': (
                {
                    'isbn': '9784088736655',
                    'identifier': {'scheme': 'doi', 'authority': 'crossref', 'value': '10.1234/example'},
                },
                'identifier is ambiguous',
            ),
            'not-object': ({'identifier': '10.1234/example'}, 'identifier is invalid'),
            'missing-key': (
                {'identifier': {'scheme': 'doi', 'value': '10.1234/example'}},
                'identifier is invalid',
            ),
            'asin': (
                {'identifier': {'scheme': 'asin', 'authority': 'amazon', 'value': 'B000000001'}},
                'identifier is invalid',
            ),
            'blank-authority': (
                {'identifier': {'scheme': 'doi', 'authority': '', 'value': '10.1234/example'}},
                'identifier is invalid',
            ),
        }
        for name, (identifier_fields, message) in cases.items():
            with self.subTest(name=name):
                catalog, expected, target = self._bibliography_case()
                edition = {
                    'canonical_url': 'https://example.com/invalid-identifier',
                    'edition_title': 'Work edition',
                    'publisher': 'Example Press',
                    'format': 'paperback',
                    **identifier_fields,
                }
                manifest = self._bibliography_manifest(expected, target, edition)
                with self.assertRaisesRegex(ValueError, message):
                    work_catalog.apply_bibliography_manifest(catalog, manifest)

    def test_bibliography_rejects_a_generic_identifier_used_by_another_edition(self):
        catalog = work_catalog.build_catalog_from_inline([{'id': 1, 'works': ['First', 'Second']}])
        entries = []
        for index, expected in enumerate(catalog['works_master'], start=1):
            entries.append(
                {
                    'entry_id': f'entry-{index}',
                    'expected_work': copy.deepcopy(expected),
                    'target_work': {**expected, 'media_type': 'book'},
                    'edition': {
                        'canonical_url': f'https://example.com/edition-{index}',
                        'edition_title': f'Edition {index}',
                        'publisher': 'Example Press',
                        'format': 'paperback',
                        'identifier': {
                            'scheme': 'doi',
                            'authority': 'crossref',
                            'value': '10.1234/shared',
                        },
                    },
                }
            )
        manifest = {'schema_version': 1, 'catalog_schema_version': 2, 'entries': entries}

        with self.assertRaisesRegex(ValueError, 'identifier source drift'):
            work_catalog.apply_bibliography_manifest(catalog, manifest)

    def test_bibliography_rejects_unsafe_or_missing_evidence(self):
        catalog = work_catalog.build_catalog_from_inline([{'id': 1, 'works': ['Work']}])
        expected = catalog['works_master'][0]
        target = {**expected, 'media_type': 'manga'}
        manifest = {
            'schema_version': 1,
            'catalog_schema_version': 2,
            'entries': [
                {
                    'entry_id': 'bad-evidence',
                    'expected_work': expected,
                    'target_work': target,
                    'evidence_url': 'javascript:x',
                }
            ],
        }
        with self.assertRaisesRegex(ValueError, 'evidence URL'):
            work_catalog.apply_bibliography_manifest(catalog, manifest)

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

    def test_delete_fetish_references_removes_owned_and_compound_links(self):
        catalog = work_catalog.build_catalog_from_inline(
            [
                {'id': 1, 'works': ['Keep']},
                {'id': 2, 'works': ['Remove']},
                {'id': 3, 'works': []},
            ],
            compound_rows=[
                {'id_a': 1, 'id_b': 2, 'works': ['Pair A']},
                {'id_a': 2, 'id_b': 3, 'works': ['Pair B']},
            ],
        )
        updated = work_catalog.delete_fetish_references(catalog, 2)

        self.assertNotIn(2, work_catalog.materialize_fetish_works(updated))
        self.assertEqual(work_catalog.materialize_compound_works(updated), {})
        self.assertIn(2, work_catalog.materialize_fetish_works(catalog))

    def test_merge_fetish_references_combines_compound_pairs_without_duplicates(self):
        catalog = work_catalog.build_catalog_from_inline(
            [{'id': 1, 'works': ['Keep']}, {'id': 2, 'works': ['Remove']}, {'id': 3, 'works': []}],
            compound_rows=[
                {'id_a': 1, 'id_b': 3, 'works': ['Shared', 'Keep pair']},
                {'id_a': 2, 'id_b': 3, 'works': ['Shared', 'Remove pair']},
                {'id_a': 1, 'id_b': 2, 'works': ['Self pair']},
            ],
        )
        updated = work_catalog.delete_fetish_references(catalog, 2, replacement_id=1)
        compounds = work_catalog.materialize_compound_works(updated)

        self.assertEqual([work['title'] for work in compounds['1,3']], ['Shared', 'Keep pair', 'Remove pair'])
        self.assertEqual(list(compounds), ['1,3'])
        self.assertNotIn(2, work_catalog.materialize_fetish_works(updated))

    def test_promote_fetish_references_rekeys_all_owners_and_legacy_projection(self):
        catalog = work_catalog.build_catalog_from_inline(
            [{'id': 1, 'works': []}, {'id': 3, 'works': []}, {'id': 10000, 'works': ['Player']}],
            compound_rows=[{'id_a': 3, 'id_b': 10000, 'works': ['Pair']}],
        )
        updated = work_catalog.promote_fetish_references(catalog, 10000, 2)

        self.assertEqual([work['title'] for work in work_catalog.materialize_fetish_works(updated)[2]], ['Player'])
        self.assertEqual(work_catalog.legacy_compound_projection(updated), {'2,3': ['Pair']})
        work_catalog.validate_catalog_fetish_references(updated, {1, 2, 3})

    def test_replacement_rejects_duplicate_work_identity(self):
        catalog = work_catalog.build_catalog_from_inline([{'id': 1, 'works': []}])
        with self.assertRaisesRegex(ValueError, 'duplicate work identity'):
            work_catalog.replace_fetish_works(catalog, 1, ['Same', 'Same'])

    def test_admin_master_create_and_update_reject_duplicate_identity(self):
        catalog = work_catalog.build_catalog_from_inline(
            [
                {
                    'id': 1,
                    'works': [
                        {'title': 'Existing', 'url': 'https://www.amazon.co.jp/dp/B000000001'},
                        {'title': 'Other', 'url': 'https://www.amazon.co.jp/dp/B000000002'},
                    ],
                }
            ]
        )
        existing, other = catalog['works_master']
        existing['media_type'] = 'manga'
        other['media_type'] = 'novel'

        with self.assertRaisesRegex(ValueError, 'identity already exists'):
            work_catalog.admin_create_master(
                catalog,
                {'canonical_title': 'Ｅｘｉｓｔｉｎｇ', 'media_type': 'manga'},
            )

        with self.assertRaisesRegex(ValueError, 'identity already exists'):
            work_catalog.admin_update_master(
                catalog,
                other['work_id'],
                {'canonical_title': 'Existing', 'media_type': 'manga'},
            )

    def test_admin_crud_requires_unreferenced_children_and_preserves_metadata(self):
        catalog = work_catalog.build_catalog_from_inline([{'id': 1, 'works': []}])
        catalog, work_id = work_catalog.admin_create_master(
            catalog, {'canonical_title': 'Managed', 'media_type': 'manga'}
        )
        catalog, edition_id = work_catalog.admin_upsert_edition(
            catalog, {'work_id': work_id, 'canonical_url': 'https://www.amazon.co.jp/dp/B000000001', 'format': 'kindle'}
        )
        catalog, alias_id = work_catalog.admin_upsert_alias(catalog, {'work_id': work_id, 'alias': 'Managed Alias'})
        catalog = work_catalog.replace_fetish_works(
            catalog, 1, [{'title': 'Managed Alias', 'url': 'https://www.amazon.co.jp/dp/B000000001'}]
        )
        link_id = catalog['fetish_work_links'][0]['link_id']
        catalog = work_catalog.admin_update_link(
            catalog, link_id, {'context_label': '入門', 'recommendation_reason': '理由'}
        )
        self.assertEqual(catalog['fetish_work_links'][0]['context_label'], '入門')
        self.assertEqual(catalog['fetish_work_links'][0]['recommendation_reason'], '理由')
        self.assertEqual(catalog['fetish_work_links'][0]['edition_id'], edition_id)
        self.assertEqual(catalog['fetish_work_links'][0]['alias_id'], alias_id)
        with self.assertRaisesRegex(ValueError, 'still referenced'):
            work_catalog.admin_delete_master(catalog, work_id)
        with self.assertRaisesRegex(ValueError, 'still referenced'):
            work_catalog.admin_delete_edition(catalog, edition_id)
        with self.assertRaisesRegex(ValueError, 'still referenced'):
            work_catalog.admin_delete_alias(catalog, alias_id)

    def test_isbn_normalization_validates_checksums_and_converts_isbn10(self):
        self.assertEqual(work_catalog.normalize_isbn('0-306-40615-2'), '9780306406157')
        self.assertEqual(work_catalog.normalize_isbn('978-0-306-40615-7'), '9780306406157')

        with self.assertRaisesRegex(ValueError, 'ISBN-10 checksum'):
            work_catalog.normalize_isbn('0-306-40615-3')
        with self.assertRaisesRegex(ValueError, 'ISBN-13 checksum'):
            work_catalog.normalize_isbn('978-0-306-40615-8')

    def test_edition_identifier_rejects_asin_child_and_canonicalizes_isbn(self):
        with self.assertRaisesRegex(ValueError, 'ASIN must remain'):
            work_catalog.build_edition_identifier(
                'wed_example',
                scheme='ASIN',
                authority='amazon',
                value='B000000001',
            )

        identifier = work_catalog.build_edition_identifier(
            'wed_example',
            scheme='ISBN',
            authority='ignored',
            value='0-306-40615-2',
        )
        self.assertEqual(identifier['scheme'], 'isbn')
        self.assertEqual(identifier['authority'], 'isbn')
        self.assertEqual(identifier['value'], '9780306406157')

    def test_v1_upgrade_adds_empty_identifiers_without_inferred_backfill(self):
        catalog = work_catalog.build_catalog_from_inline(
            [{'id': 1, 'works': [{'title': 'ASIN edition', 'url': 'https://www.amazon.co.jp/dp/B000000001'}]}]
        )
        legacy = copy.deepcopy(catalog)
        legacy['schema_version'] = 1
        legacy.pop('work_edition_identifiers')
        before = copy.deepcopy(legacy)

        upgraded = work_catalog.upgrade_catalog_schema(legacy)

        self.assertEqual(legacy, before)
        self.assertEqual(upgraded['schema_version'], 2)
        self.assertEqual(upgraded['work_edition_identifiers'], [])
        self.assertEqual(upgraded['work_editions'][0]['asin'], 'B000000001')

    def test_edition_identifier_is_globally_unique_across_editions(self):
        catalog = work_catalog.build_catalog_from_inline([{'id': 1, 'works': []}])
        catalog, first_work_id = work_catalog.admin_create_master(catalog, {'canonical_title': 'First'})
        catalog, second_work_id = work_catalog.admin_create_master(catalog, {'canonical_title': 'Second'})
        catalog, first_edition_id = work_catalog.admin_upsert_edition(
            catalog,
            {'work_id': first_work_id, 'canonical_url': 'https://example.com/first'},
        )
        catalog, second_edition_id = work_catalog.admin_upsert_edition(
            catalog,
            {'work_id': second_work_id, 'canonical_url': 'https://example.com/second'},
        )
        catalog, _identifier_id = work_catalog.admin_upsert_edition_identifier(
            catalog,
            {
                'edition_id': first_edition_id,
                'scheme': 'isbn',
                'authority': 'isbn',
                'value': '9780306406157',
            },
        )

        with self.assertRaisesRegex(ValueError, 'edition identifier already exists'):
            work_catalog.admin_upsert_edition_identifier(
                catalog,
                {
                    'edition_id': second_edition_id,
                    'scheme': 'isbn',
                    'authority': 'isbn',
                    'value': '0-306-40615-2',
                },
            )

    def test_edition_identifier_crud_and_parent_deletion_cascade(self):
        catalog = work_catalog.build_catalog_from_inline([{'id': 1, 'works': []}])
        catalog, work_id = work_catalog.admin_create_master(catalog, {'canonical_title': 'Managed identifiers'})
        catalog, edition_id = work_catalog.admin_upsert_edition(
            catalog,
            {'work_id': work_id, 'canonical_url': 'https://example.com/edition'},
        )
        catalog, identifier_id = work_catalog.admin_upsert_edition_identifier(
            catalog,
            {
                'edition_id': edition_id,
                'scheme': 'isbn',
                'authority': 'isbn',
                'value': '0-306-40615-2',
            },
        )
        self.assertEqual(catalog['work_edition_identifiers'][0]['identifier_id'], identifier_id)

        catalog, updated_identifier_id = work_catalog.admin_upsert_edition_identifier(
            catalog,
            {
                'edition_id': edition_id,
                'scheme': 'isbn',
                'authority': 'isbn',
                'value': '9783161484100',
            },
            identifier_id=identifier_id,
        )
        self.assertNotEqual(updated_identifier_id, identifier_id)
        self.assertEqual(
            [row['value'] for row in catalog['work_edition_identifiers']],
            ['9783161484100'],
        )
        catalog = work_catalog.admin_delete_edition_identifier(catalog, updated_identifier_id)
        self.assertEqual(catalog['work_edition_identifiers'], [])

        catalog, identifier_id = work_catalog.admin_upsert_edition_identifier(
            catalog,
            {
                'edition_id': edition_id,
                'scheme': 'isbn',
                'authority': 'isbn',
                'value': '9780306406157',
            },
        )
        catalog = work_catalog.admin_delete_edition(catalog, edition_id)
        self.assertNotIn(identifier_id, {row['identifier_id'] for row in catalog['work_edition_identifiers']})

        catalog, edition_id = work_catalog.admin_upsert_edition(
            catalog,
            {'work_id': work_id, 'canonical_url': 'https://example.com/recreated-edition'},
        )
        catalog, identifier_id = work_catalog.admin_upsert_edition_identifier(
            catalog,
            {
                'edition_id': edition_id,
                'scheme': 'isbn',
                'authority': 'isbn',
                'value': '9780306406157',
            },
        )
        catalog = work_catalog.admin_delete_master(catalog, work_id)
        self.assertNotIn(identifier_id, {row['identifier_id'] for row in catalog['work_edition_identifiers']})

    def test_restored_legacy_owner_reuses_curated_ids_and_keeps_review_rows(self):
        catalog = work_catalog.build_catalog_from_inline(
            [{'id': 1, 'works': [{'title': 'Original', 'url': 'https://www.amazon.co.jp/dp/B000000001'}]}]
        )
        catalog['works_master'][0]['media_type'] = 'manga'
        catalog['work_editions'][0]['format'] = 'kindle'
        catalog['review_queue'] = [
            {
                'review_id': 'wrv_manual',
                'review_type': 'normalization_candidate',
                'candidate_key': 'manual',
                'work_ids': [catalog['works_master'][0]['work_id']],
                'titles': ['Original'],
                'asins': [],
                'status': 'resolved',
                'decision': 'keep_separate',
                'target_work_id': None,
                'version': 4,
                'updated_at': '2026-01-01T00:00:00+00:00',
            }
        ]
        before = copy.deepcopy(catalog)
        updated = work_catalog.merge_restored_fetish_works(
            catalog,
            [{'id': 10000, 'works': [{'title': 'Alias', 'url': 'https://www.amazon.co.jp/dp/B000000001'}, 'New Work']}],
        )
        self.assertEqual(catalog, before)
        self.assertEqual(updated['review_queue'][0], before['review_queue'][0])
        restored = work_catalog.materialize_fetish_works(updated)[10000]
        self.assertEqual(restored[0]['work_id'], before['works_master'][0]['work_id'])
        self.assertEqual(restored[0]['edition_id'], before['work_editions'][0]['edition_id'])
        self.assertEqual(updated['works_master'][0]['media_type'], 'manga')
        self.assertEqual(updated['work_editions'][0]['format'], 'kindle')

    def test_catalog_parity_report_checks_effective_order_and_pending_reviews(self):
        fetishes = [{'id': 1, 'works': ['First', 'Second']}]
        catalog = work_catalog.build_catalog_from_inline(fetishes)
        report = work_catalog.catalog_parity_report(catalog, fetishes)
        self.assertTrue(report['automated_parity_ok'])
        changed = copy.deepcopy(fetishes)
        changed[0]['works'].reverse()
        report = work_catalog.catalog_parity_report(catalog, changed)
        self.assertFalse(report['automated_parity_ok'])
        self.assertEqual(report['fetish_mismatch_count'], 1)

    def _production_correction_projection_fixture(self):
        data = ROOT / 'data'
        catalog = json.loads((data / 'work_catalog.json').read_text(encoding='utf-8'))
        fetishes = json.loads((data / 'fetishes.json').read_text(encoding='utf-8'))
        compounds = json.loads((data / 'compound_works.json').read_text(encoding='utf-8'))
        correction_manifests = tuple(
            json.loads((data / name).read_text(encoding='utf-8'))
            for name in (
                'work_catalog_corrections.json',
                'work_catalog_corrections_batch2.json',
                'work_catalog_link_bindings_batch2.json',
            )
        )
        source = work_catalog.project_approved_inline_correction_manifests(
            fetishes,
            compound_rows=compounds,
            correction_manifests=correction_manifests,
            direction='reverse',
        )
        fetishes, compounds = source['fetishes'], source['compound_rows']
        player_works = [
            {
                'title': '誰かこの状況を説明してください！',
                'url': 'https://www.amazon.co.jp/dp/B07DL6G318?tag=hekinator-22',
            },
            {
                'title': 'わたしの幸せな結婚',
                'url': 'https://www.amazon.co.jp/dp/B07X25T546?tag=hekinator-22',
            },
        ]
        next_fetishes = copy.deepcopy(fetishes)
        next(row for row in next_fetishes if row['id'] == 104)['works'] = player_works
        next_catalog = work_catalog.replace_fetish_works(catalog, 104, player_works)
        return next_catalog, next_fetishes, compounds, correction_manifests

    def test_strict_inline_projection_round_trips_checked_sources(self):
        data = ROOT / 'data'
        fetishes = json.loads((data / 'fetishes.json').read_text(encoding='utf-8'))
        compounds = json.loads((data / 'compound_works.json').read_text(encoding='utf-8'))
        correction_manifests = tuple(
            json.loads((data / name).read_text(encoding='utf-8'))
            for name in (
                'work_catalog_corrections.json',
                'work_catalog_corrections_batch2.json',
                'work_catalog_link_bindings_batch2.json',
            )
        )

        reverse = work_catalog.project_approved_inline_correction_manifests(
            fetishes,
            compound_rows=compounds,
            correction_manifests=correction_manifests,
            direction='reverse',
        )
        forward = work_catalog.project_approved_inline_correction_manifests(
            reverse['fetishes'],
            compound_rows=reverse['compound_rows'],
            correction_manifests=correction_manifests,
        )

        self.assertEqual(reverse['applied_link_count'], 92)
        self.assertEqual(reverse['fetish_owner_count'], 10)
        self.assertEqual(reverse['compound_owner_count'], 50)
        self.assertEqual(forward['fetishes'], fetishes)
        self.assertEqual(forward['compound_rows'], compounds)

    def test_strict_inline_projection_rejects_source_drift(self):
        _catalog, fetishes, compounds, correction_manifests = self._production_correction_projection_fixture()
        next(row for row in fetishes if row['id'] == 23)['works'][1]['title'] += ' drift'

        with self.assertRaisesRegex(ValueError, 'source_signature_drift'):
            work_catalog.project_approved_inline_correction_manifests(
                fetishes,
                compound_rows=compounds,
                correction_manifests=correction_manifests,
            )

    def test_checked_inline_fallback_has_raw_parity_with_the_checked_catalog(self):
        data = ROOT / 'data'
        catalog = json.loads((data / 'work_catalog.json').read_text(encoding='utf-8'))
        fetishes = json.loads((data / 'fetishes.json').read_text(encoding='utf-8'))
        compounds = json.loads((data / 'compound_works.json').read_text(encoding='utf-8'))

        parity = work_catalog.catalog_parity_report(
            catalog,
            fetishes,
            compound_rows=compounds,
        )

        self.assertTrue(parity['automated_parity_ok'])
        correction_manifests = tuple(
            json.loads((data / name).read_text(encoding='utf-8'))
            for name in (
                'work_catalog_corrections.json',
                'work_catalog_corrections_batch2.json',
                'work_catalog_link_bindings_batch2.json',
            )
        )
        approved = work_catalog.approved_projection_parity_report_many(
            catalog, fetishes, compound_rows=compounds, correction_manifests=correction_manifests
        )
        self.assertTrue(approved['approved_projection_ok'])
        self.assertEqual(approved['approved_projection_applied_count'], 0)
        self.assertEqual(parity['mismatch_count'], 0)

    def test_approved_projection_explains_all_production_correction_deltas(self):
        catalog, fetishes, compounds, correction_manifests = self._production_correction_projection_fixture()

        raw = work_catalog.catalog_parity_report(catalog, fetishes, compound_rows=compounds)
        approved = work_catalog.approved_projection_parity_report_many(
            catalog,
            fetishes,
            compound_rows=compounds,
            correction_manifests=correction_manifests,
        )

        self.assertEqual(raw['mismatch_count'], 59)
        self.assertFalse(raw['automated_parity_ok'])
        self.assertTrue(approved['approved_projection_ok'])
        self.assertEqual(approved['approved_mismatch_count'], 0)
        self.assertEqual(approved['approved_projection_applied_count'], 91)
        self.assertEqual(approved['approved_projection_missing_count'], 2)

    def test_approved_projection_rejects_unapproved_signature_and_shape_drift(self):
        catalog, fetishes, compounds, correction_manifests = self._production_correction_projection_fixture()
        cases = {}

        title_drift = copy.deepcopy(fetishes)
        next(row for row in title_drift if row['id'] == 23)['works'][1]['title'] += ' drift'
        cases['title'] = (title_drift, compounds)

        url_drift = copy.deepcopy(fetishes)
        next(row for row in url_drift if row['id'] == 23)['works'][1]['url'] = 'https://example.com/drift'
        cases['url'] = (url_drift, compounds)

        order_drift = copy.deepcopy(fetishes)
        next(row for row in order_drift if row['id'] == 13)['works'].reverse()
        cases['order'] = (order_drift, compounds)

        count_drift = copy.deepcopy(compounds)
        count_drift['68,97'].pop()
        cases['count'] = (fetishes, count_drift)

        owner_drift = copy.deepcopy(fetishes)
        next(row for row in owner_drift if row['id'] == 23)['id'] = 999
        cases['owner'] = (owner_drift, compounds)

        for name, (candidate_fetishes, candidate_compounds) in cases.items():
            with self.subTest(name=name):
                report = work_catalog.approved_projection_parity_report_many(
                    catalog,
                    candidate_fetishes,
                    compound_rows=candidate_compounds,
                    correction_manifests=correction_manifests,
                )
                self.assertFalse(report['approved_projection_ok'])
                self.assertGreater(report['approved_mismatch_count'], 0)

    def test_approved_projection_rejects_source_moved_behind_an_applied_target(self):
        catalog, fetishes, compounds, correction_manifests = self._production_correction_projection_fixture()
        owner = next(row for row in fetishes if row['id'] == 13)
        source = copy.deepcopy(owner['works'][2])
        owner['works'][2]['title'] = '学園物の乙女ゲームの世界に転生したけど、チート持ちの背景男子生徒だったようです。'
        owner['works'].append(source)

        report = work_catalog.approved_projection_parity_report_many(
            catalog,
            fetishes,
            compound_rows=compounds,
            correction_manifests=correction_manifests,
        )

        self.assertFalse(report['approved_projection_ok'])
        self.assertIn(
            'source_position_drift',
            [row['reason'] for row in report['approved_projection_errors']],
        )

    def test_approved_projection_rejects_allow_missing_source_moved_to_another_owner(self):
        catalog, fetishes, compounds, correction_manifests = self._production_correction_projection_fixture()
        moved_source = {
            'title': 'アンジェリーク',
            'url': 'https://www.amazon.co.jp/dp/B011KZQVH4?tag=hekinator-22',
        }
        next(row for row in fetishes if row['id'] == 105)['works'] = [moved_source]
        catalog = work_catalog.replace_fetish_works(catalog, 105, [moved_source])

        report = work_catalog.approved_projection_parity_report_many(
            catalog,
            fetishes,
            compound_rows=compounds,
            correction_manifests=correction_manifests,
        )

        self.assertFalse(report['approved_projection_ok'])
        self.assertIn(
            'source_owner_drift',
            [row['reason'] for row in report['approved_projection_errors']],
        )

    def test_approved_projection_rejects_non_boolean_allow_missing(self):
        catalog, fetishes, compounds, correction_manifests = self._production_correction_projection_fixture()
        correction_manifests = copy.deepcopy(correction_manifests)
        corrections = correction_manifests[0]
        optional = next(
            update
            for correction in corrections['corrections']
            for update in correction['link_updates']
            if update.get('allow_missing')
        )
        optional['allow_missing'] = 'false'

        report = work_catalog.approved_projection_parity_report_many(
            catalog,
            fetishes,
            compound_rows=compounds,
            correction_manifests=correction_manifests,
        )

        self.assertFalse(report['approved_projection_ok'])
        self.assertIn(
            'invalid_allow_missing',
            [row['reason'] for row in report['approved_projection_errors']],
        )

    def test_review_merge_preserves_each_source_display_title_as_alias(self):
        catalog = work_catalog.build_catalog_from_inline(
            [
                {
                    'id': 1,
                    'works': [
                        {'title': '作品（漫画）', 'url': 'https://www.amazon.co.jp/dp/B000000001'},
                        {'title': '作品', 'url': 'https://www.amazon.co.jp/dp/B000000002'},
                    ],
                }
            ]
        )
        before_titles = [row['title'] for row in work_catalog.materialize_fetish_works(catalog)[1]]
        review = catalog['review_queue'][0]
        target_id = review['work_ids'][0]
        updated = work_catalog.admin_decide_review(
            catalog,
            review['review_id'],
            {
                'expected_version': 0,
                'decision': 'merge',
                'target_work_id': target_id,
                'updated_at': '2026-01-01T00:00:00+00:00',
            },
        )
        self.assertEqual(len(updated['works_master']), 1)
        self.assertEqual([row['title'] for row in work_catalog.materialize_fetish_works(updated)[1]], before_titles)
        work_catalog.validate_catalog(updated)

    def test_old_backup_work_sanitization_skips_invalid_and_duplicate_rows(self):
        rows = work_catalog.sanitize_restored_works(
            [
                '',
                {'title': ''},
                'Same',
                'Same',
                {'title': 'Alias A', 'url': 'https://www.amazon.co.jp/dp/B000000001'},
                {'title': 'Alias B', 'url': 'https://www.amazon.co.jp/dp/B000000001'},
            ]
        )
        self.assertEqual(rows, ['Same', {'title': 'Alias A', 'url': 'https://www.amazon.co.jp/dp/B000000001'}])

    def test_review_decision_manifest_resolves_complete_queue_and_preserves_projection(self):
        catalog = work_catalog.build_catalog_from_inline(
            [
                {
                    'id': 1,
                    'works': [
                        {'title': 'Same（人物A）', 'url': 'https://www.amazon.co.jp/dp/B000000001'},
                        {'title': 'Same（人物B）'},
                    ],
                }
            ]
        )
        review = catalog['review_queue'][0]
        before = work_catalog.materialize_fetish_works(catalog)
        target = next(row['work_id'] for row in catalog['work_editions'] if row.get('asin') == 'B000000001')
        manifest = {
            'schema_version': 1,
            'reviewed_at': '2026-07-28',
            'decisions': [
                {
                    'review_id': review['review_id'],
                    'candidate_key': review['candidate_key'],
                    'work_ids': review['work_ids'],
                    'decision': 'merge',
                    'target_work_id': target,
                }
            ],
        }

        updated = work_catalog.apply_review_decisions(catalog, manifest)

        self.assertEqual(len(updated['works_master']), 1)
        self.assertEqual(updated['review_queue'][0]['status'], 'resolved')
        self.assertEqual(
            [(row['title'], row['url']) for row in work_catalog.materialize_fetish_works(updated)[1]],
            [(row['title'], row['url']) for row in before[1]],
        )
        self.assertEqual(work_catalog.apply_review_decisions(updated, manifest), updated)

    def test_review_manifest_can_add_audited_identity_override(self):
        catalog = work_catalog.build_catalog_from_inline(
            [
                {
                    'id': 1,
                    'works': [
                        {'title': 'Given', 'url': 'https://www.amazon.co.jp/dp/B000000001'},
                        {'title': 'ギヴン', 'url': 'https://www.amazon.co.jp/dp/B000000002'},
                    ],
                }
            ]
        )
        self.assertEqual(catalog['review_queue'], [])
        before = work_catalog.materialize_fetish_works(catalog)
        by_title = {row['canonical_title']: row['work_id'] for row in catalog['works_master']}
        candidate_key = 'identity_override:given-ja-en'
        manifest = {
            'schema_version': 1,
            'reviewed_at': '2026-07-28',
            'decisions': [
                {
                    'review_id': work_catalog._stable_id('wrv', candidate_key),
                    'review_type': 'identity_override',
                    'candidate_key': candidate_key,
                    'work_ids': sorted(by_title.values()),
                    'decision': 'merge',
                    'target_work_id': by_title['ギヴン'],
                }
            ],
        }

        updated = work_catalog.apply_review_decisions(catalog, manifest)

        self.assertEqual(len(updated['works_master']), 1)
        self.assertEqual(updated['review_queue'][0]['review_type'], 'identity_override')
        self.assertEqual(updated['review_queue'][0]['status'], 'resolved')
        self.assertEqual(
            [(row['title'], row['url']) for row in work_catalog.materialize_fetish_works(updated)[1]],
            [(row['title'], row['url']) for row in before[1]],
        )
        self.assertEqual(work_catalog.apply_review_decisions(updated, manifest), updated)

    def test_review_manifest_rejects_malformed_schema_and_decision_rows(self):
        catalog = work_catalog.build_catalog_from_inline([])
        for manifest in (
            {'schema_version': None, 'decisions': []},
            {'schema_version': {}, 'decisions': []},
            {'schema_version': 1, 'decisions': [None]},
        ):
            with self.assertRaises(ValueError):
                work_catalog.apply_review_decisions(catalog, manifest)

    def test_review_decision_manifest_rejects_input_drift_and_incomplete_coverage(self):
        catalog = work_catalog.build_catalog_from_inline(
            [{'id': 1, 'works': ['Same（A）', 'Same（B）', 'Other（A）', 'Other（B）']}]
        )
        review = catalog['review_queue'][0]
        decision = {
            'review_id': review['review_id'],
            'candidate_key': review['candidate_key'],
            'work_ids': review['work_ids'],
            'decision': 'keep_separate',
            'target_work_id': None,
        }
        with self.assertRaisesRegex(ValueError, 'complete review queue'):
            work_catalog.apply_review_decisions(
                catalog,
                {'schema_version': 1, 'reviewed_at': '2026-07-28', 'decisions': [decision]},
            )
        decision['work_ids'] = decision['work_ids'][:-1]
        decisions = [decision]
        for remaining in catalog['review_queue'][1:]:
            decisions.append(
                {
                    'review_id': remaining['review_id'],
                    'candidate_key': remaining['candidate_key'],
                    'work_ids': remaining['work_ids'],
                    'decision': 'keep_separate',
                    'target_work_id': None,
                }
            )
        with self.assertRaisesRegex(ValueError, 'candidates changed'):
            work_catalog.apply_review_decisions(
                catalog,
                {'schema_version': 1, 'reviewed_at': '2026-07-28', 'decisions': decisions},
            )


if __name__ == '__main__':
    unittest.main()
