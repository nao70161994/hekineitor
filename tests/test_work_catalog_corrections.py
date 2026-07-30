import copy
import json
import unittest
from pathlib import Path

from engine import work_catalog

ROOT = Path(__file__).resolve().parents[1]


class WorkCatalogCorrectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        data = ROOT / 'data'
        fetishes = json.loads((data / 'fetishes.json').read_text(encoding='utf-8'))
        compounds = json.loads((data / 'compound_works.json').read_text(encoding='utf-8'))
        compound_rows = []
        for key, works in sorted(compounds.items()):
            id_a, id_b = key.split(',', 1)
            compound_rows.append({'key': key, 'id_a': int(id_a), 'id_b': int(id_b), 'works': works})
        corrections = json.loads((data / 'work_catalog_corrections.json').read_text(encoding='utf-8'))
        source = work_catalog.project_approved_inline_corrections(
            fetishes,
            compound_rows=compound_rows,
            corrections=corrections,
            direction='reverse',
        )
        seed = json.loads((data / 'work_catalog_seed_overrides.json').read_text(encoding='utf-8'))
        review = json.loads((data / 'work_catalog_review_decisions.json').read_text(encoding='utf-8'))
        catalog = work_catalog.build_catalog_from_inline(
            source['fetishes'],
            compound_rows=source['compound_rows'],
            seed_overrides=seed,
        )
        cls.catalog = work_catalog.apply_review_decisions(catalog, review)
        cls.manifest = corrections

    def apply(self, catalog=None, manifest=None):
        return work_catalog.apply_catalog_corrections(
            copy.deepcopy(self.catalog if catalog is None else catalog),
            copy.deepcopy(self.manifest if manifest is None else manifest),
        )

    def test_checked_seed_corrections_split_retitle_and_preserve_link_owners(self):
        before_locations = {
            link['link_id']: (
                table,
                link.get('fetish_id'),
                link.get('id_a'),
                link.get('id_b'),
                link['position'],
            )
            for table in ('fetish_work_links', 'compound_work_links')
            for link in self.catalog[table]
        }

        corrected = self.apply()

        self.assertTrue(work_catalog.validate_catalog(corrected))
        self.assertEqual(len(corrected['works_master']), len(self.catalog['works_master']) + 1)
        edition_delta = sum(
            len(correction.get('edition_additions') or []) - len(correction.get('edition_removals') or [])
            for correction in self.manifest['corrections']
        )
        alias_delta = sum(
            len(correction.get('alias_additions') or []) - len(correction.get('alias_removals') or [])
            for correction in self.manifest['corrections']
        )
        self.assertEqual(len(corrected['work_editions']), len(self.catalog['work_editions']) + edition_delta)
        self.assertEqual(len(corrected['work_aliases']), len(self.catalog['work_aliases']) + alias_delta)
        works = {row['work_id']: row for row in corrected['works_master']}
        editions = {row['edition_id']: row for row in corrected['work_editions']}
        self.assertEqual(works['wrk_76a08381045d290abf30']['canonical_title'], 'ゼロの使い魔')
        self.assertEqual(
            works['wrk_c5214e34ec2b68ce172b']['canonical_title'],
            'Lv2からチートだった元勇者候補のまったり異世界ライフ',
        )
        self.assertEqual(
            editions['wed_c5214e34ec2b68ce172b']['work_id'],
            'wrk_c5214e34ec2b68ce172b',
        )
        expected_titles = {
            'B0FYCVC6BF': '学園物の乙女ゲームの世界に転生したけど、チート持ちの背景男子生徒だったようです。',
            'B07N19VKLX': 'テイルズ オブ ヴェスペリア REMASTER パーフェクトガイド',
            'B011KZQVH4': '由羅カイリ画集 ～アンジェリーク 20th Anniversary～',
        }
        for asin, title in expected_titles.items():
            edition = next(row for row in corrected['work_editions'] if row['asin'] == asin)
            self.assertEqual(works[edition['work_id']]['canonical_title'], title)
        exposure_work = works['wrk_d870201346843e8d88db']
        self.assertEqual(exposure_work['canonical_title'], '露出少女日記')
        self.assertEqual(exposure_work['media_type'], 'manga')
        self.assertNotIn('B097ZSFLYR', {row['asin'] for row in corrected['work_editions']})
        self.assertEqual(
            editions['wed_31d146e9bdd8d864e274'],
            {
                'edition_id': 'wed_31d146e9bdd8d864e274',
                'work_id': 'wrk_d870201346843e8d88db',
                'asin': '',
                'canonical_url': 'https://fantia.jp/products/685549',
                'format': 'digital',
                'status': 'active',
                'edition_title': '露出少女日記総集編１冊目',
                'publisher': '',
            },
        )

        materialized = work_catalog.materialize_fetish_works(corrected)
        corrected_links = [
            link
            for table in ('fetish_work_links', 'compound_work_links')
            for link in corrected[table]
            if link['work_id']
            in {
                'wrk_c5214e34ec2b68ce172b',
                'wrk_5d1a3d2f9813efa92de1',
                'wrk_875e300c4de51e82ed13',
                'wrk_635907b25c09a91c33a9',
                'wrk_d870201346843e8d88db',
            }
        ]
        source_ids = {
            update['expected']['link_id']
            for correction in self.manifest['corrections']
            for update in correction.get('link_updates') or []
            if update['expected']['work_id']
            in {
                'wrk_76a08381045d290abf30',
                'wrk_5d1a3d2f9813efa92de1',
                'wrk_875e300c4de51e82ed13',
                'wrk_635907b25c09a91c33a9',
                'wrk_d870201346843e8d88db',
            }
        }
        expected_locations = {before_locations[link_id] for link_id in source_ids}
        actual_locations = {
            (
                'fetish_work_links' if 'fetish_id' in link else 'compound_work_links',
                link.get('fetish_id'),
                link.get('id_a'),
                link.get('id_b'),
                link['position'],
            )
            for link in corrected_links
            if (
                ('fetish_work_links', link.get('fetish_id'), None, None, link['position']) in expected_locations
                or ('compound_work_links', None, link.get('id_a'), link.get('id_b'), link['position'])
                in expected_locations
            )
        }
        self.assertEqual(actual_locations, expected_locations)
        self.assertEqual(materialized[23][1]['context_label'], 'フェンリース（CV：釘宮理恵）')
        self.assertEqual(materialized[13][2]['context_label'], '乙女ゲーム転生もの')
        self.assertEqual(materialized[71][2]['context_label'], '悪役令嬢系')
        self.assertEqual(materialized[86][2]['context_label'], '執事キャラ')
        self.assertEqual(materialized[55][1]['title'], '露出少女日記（成人向け漫画）')
        self.assertEqual(materialized[55][1]['url'], 'https://fantia.jp/products/685549')
        exposure_link = next(
            row for row in corrected['fetish_work_links'] if row['fetish_id'] == 55 and row['position'] == 1
        )
        self.assertEqual(exposure_link['link_id'], 'fwl_48c4eb3f1ab94a99f39f')
        self.assertEqual(exposure_link['edition_id'], 'wed_31d146e9bdd8d864e274')
        self.assertEqual(exposure_link['alias_id'], 'wal_163bdd5ff438f9e6e0f7')
        self.assertFalse(
            {
                'wal_461f29db4e2b82b4ea07',
                'wal_737e31ce734e769e93f6',
                'wal_d6cfef435e8063b178c5',
                'wal_e40db4294f780d1b4c4f',
            }
            & {row['alias_id'] for row in corrected['work_aliases']}
        )

    def test_apply_is_idempotent_and_does_not_mutate_input(self):
        source = copy.deepcopy(self.catalog)
        before = copy.deepcopy(source)

        once = work_catalog.apply_catalog_corrections(source, self.manifest)
        twice = work_catalog.apply_catalog_corrections(once, self.manifest)

        self.assertEqual(source, before)
        self.assertEqual(twice, once)

    def test_review_source_lock_accepts_date_and_equivalent_iso_timestamps(self):
        for updated_at in (
            '2026-07-28',
            '2026-07-28T00:00:00+00:00',
            '2026-07-28T09:00:00+09:00',
            '2026-07-29',
            '2026-07-29T00:00:00+00:00',
            '2026-07-29T09:00:00+09:00',
        ):
            with self.subTest(updated_at=updated_at):
                catalog = copy.deepcopy(self.catalog)
                review = next(row for row in catalog['review_queue'] if row['review_id'] == 'wrv_66989c04b744aa1a5b64')
                review['updated_at'] = updated_at

                corrected = self.apply(catalog)
                corrected_review = next(
                    row for row in corrected['review_queue'] if row['review_id'] == 'wrv_66989c04b744aa1a5b64'
                )

                self.assertEqual(corrected_review['updated_at'], '2026-07-29T00:00:00+00:00')
                self.assertEqual(self.apply(corrected), corrected)

    def test_review_source_lock_rejects_unlisted_timestamp(self):
        catalog = copy.deepcopy(self.catalog)
        review = next(row for row in catalog['review_queue'] if row['review_id'] == 'wrv_66989c04b744aa1a5b64')
        review['updated_at'] = '2026-07-30T00:00:00+00:00'

        with self.assertRaisesRegex(ValueError, 'source drift'):
            self.apply(catalog)

    def test_review_source_lock_rejects_non_timestamp_field_drift(self):
        catalog = copy.deepcopy(self.catalog)
        review = next(row for row in catalog['review_queue'] if row['review_id'] == 'wrv_66989c04b744aa1a5b64')
        review['updated_at'] = '2026-07-28T00:00:00+00:00'
        review['decision'] = 'keep_separate'

        with self.assertRaisesRegex(ValueError, 'source drift'):
            self.apply(catalog)

    def test_source_drift_fails_closed_and_is_atomic(self):
        mutations = []
        work_drift = copy.deepcopy(self.catalog)
        next(row for row in work_drift['works_master'] if row['work_id'] == 'wrk_875e300c4de51e82ed13')['status'] = (
            'inactive'
        )
        mutations.append(work_drift)
        edition_drift = copy.deepcopy(self.catalog)
        next(row for row in edition_drift['work_editions'] if row['edition_id'] == 'wed_5d1a3d2f9813efa92de1')[
            'format'
        ] = 'kindle'
        mutations.append(edition_drift)
        link_drift = copy.deepcopy(self.catalog)
        next(row for row in link_drift['fetish_work_links'] if row['link_id'] == 'fwl_457e0d3155f4cc762cfb')[
            'context_label'
        ] = 'changed'
        mutations.append(link_drift)
        alias_drift = copy.deepcopy(self.catalog)
        next(row for row in alias_drift['work_aliases'] if row['alias_id'] == 'wal_737e31ce734e769e93f6')['alias'] = (
            'changed'
        )
        mutations.append(alias_drift)

        for drifted in mutations:
            with self.subTest(drift=drifted):
                before = copy.deepcopy(drifted)
                with self.assertRaisesRegex(ValueError, 'source drift'):
                    work_catalog.apply_catalog_corrections(drifted, self.manifest)
                self.assertEqual(drifted, before)

    def test_canonical_and_link_collisions_fail_closed(self):
        canonical_collision = copy.deepcopy(self.catalog)
        canonical_collision['works_master'][0]['normalized_title'] = (
            'テイルズ オブ ヴェスペリア remaster パーフェクトガイド'
        )
        with self.assertRaisesRegex(ValueError, 'canonical collision'):
            self.apply(canonical_collision)

        link_collision = copy.deepcopy(self.catalog)
        next(row for row in link_collision['fetish_work_links'] if row['link_id'] == 'fwl_26d5e1fe9ef832b0cf69')[
            'link_id'
        ] = 'fwl_02e6dd08dc303434f38c'
        with self.assertRaisesRegex(ValueError, 'link collision'):
            self.apply(link_collision)

    def test_optional_seed_link_cleanup_preserves_player_replacement(self):
        catalog = copy.deepcopy(self.catalog)
        catalog['fetish_work_links'] = [
            row for row in catalog['fetish_work_links'] if row['link_id'] != 'fwl_0491358730a92c95b5dc'
        ]
        catalog['work_aliases'] = [
            row for row in catalog['work_aliases'] if row['alias_id'] != 'wal_d6cfef435e8063b178c5'
        ]
        replacement = copy.deepcopy(next(row for row in catalog['fetish_work_links'] if row['fetish_id'] == 104))
        replacement.update({'link_id': 'fwl_player_replacement', 'position': 1})
        catalog['fetish_work_links'].append(replacement)

        corrected = self.apply(catalog)

        self.assertIn(replacement, corrected['fetish_work_links'])
        self.assertEqual(self.apply(corrected), corrected)

    def test_optional_seed_rows_still_reject_present_drift(self):
        for collection, row_id, field in (
            ('fetish_work_links', 'fwl_0491358730a92c95b5dc', 'context_label'),
            ('work_aliases', 'wal_d6cfef435e8063b178c5', 'alias'),
        ):
            with self.subTest(collection=collection):
                catalog = copy.deepcopy(self.catalog)
                id_field = 'link_id' if collection == 'fetish_work_links' else 'alias_id'
                next(row for row in catalog[collection] if row[id_field] == row_id)[field] = 'drift'
                with self.assertRaisesRegex(ValueError, 'source drift'):
                    self.apply(catalog)

    def test_dangling_alias_and_non_deterministic_split_fail_closed(self):
        dangling = copy.deepcopy(self.catalog)
        dangling['fetish_work_links'].append(
            {
                'link_id': 'fwl_additional_production_link',
                'fetish_id': 999,
                'work_id': 'wrk_76a08381045d290abf30',
                'edition_id': 'wed_76a08381045d290abf30',
                'alias_id': 'wal_461f29db4e2b82b4ea07',
                'position': 0,
                'context_label': '',
                'recommendation_reason': '',
            }
        )
        with self.assertRaisesRegex(ValueError, 'alias still referenced'):
            self.apply(dangling)

        manifest = copy.deepcopy(self.manifest)
        manifest['corrections'][0]['target_work']['work_id'] = 'wrk_invented'
        with self.assertRaisesRegex(ValueError, 'non-deterministic work_id'):
            self.apply(manifest=manifest)

    def test_manifest_rejects_invalid_or_duplicate_accepted_timestamps(self):
        for values in (
            ['2026-07-29T00:00:00'],
            ['2026-07-29', '2026-07-29T00:00:00+00:00'],
        ):
            with self.subTest(values=values):
                manifest = copy.deepcopy(self.manifest)
                manifest['corrections'][0]['review_updates'][0]['accepted_source_updated_at'] = values
                with self.assertRaisesRegex(ValueError, 'invalid review update|duplicate accepted'):
                    self.apply(manifest=manifest)

    def test_v2_additions_removal_and_projection_fail_closed(self):
        correction = copy.deepcopy(
            next(
                row
                for row in self.manifest['corrections']
                if row['correction_id'] == 'replace-misassigned-exposure-diary-b097zsflyr'
            )
        )
        manifest = {
            'schema_version': 2,
            'catalog_schema_version': 2,
            'corrections': [correction],
        }

        invented_id = copy.deepcopy(manifest)
        invented_id['corrections'][0]['edition_additions'][0]['target']['edition_id'] = 'wed_invented'
        with self.assertRaisesRegex(ValueError, 'non-deterministic edition addition'):
            self.apply(manifest=invented_id)

        invented_alias_id = copy.deepcopy(manifest)
        invented_alias_id['corrections'][0]['alias_additions'][0]['target']['alias_id'] = 'wal_invented'
        with self.assertRaisesRegex(ValueError, 'non-deterministic alias addition'):
            self.apply(manifest=invented_alias_id)

        extra_work_field = copy.deepcopy(manifest)
        extra_work_field['corrections'][0]['target_work']['unexpected'] = True
        with self.assertRaisesRegex(ValueError, 'invalid target work'):
            self.apply(manifest=extra_work_field)

        extra_edition_field = copy.deepcopy(manifest)
        extra_edition_field['corrections'][0]['edition_additions'][0]['target']['unexpected'] = True
        with self.assertRaisesRegex(ValueError, 'invalid edition addition'):
            self.apply(manifest=extra_edition_field)

        invalid_wrappers = []
        extra_correction_field = copy.deepcopy(manifest)
        extra_correction_field['corrections'][0]['unexpected'] = True
        invalid_wrappers.append(extra_correction_field)
        misspelled_identifiers = copy.deepcopy(manifest)
        addition = misspelled_identifiers['corrections'][0]['edition_additions'][0]
        addition['identifier'] = addition.pop('identifiers')
        invalid_wrappers.append(misspelled_identifiers)
        extra_removal_field = copy.deepcopy(manifest)
        extra_removal_field['corrections'][0]['edition_removals'][0]['unexpected'] = True
        invalid_wrappers.append(extra_removal_field)
        extra_alias_wrapper_field = copy.deepcopy(manifest)
        extra_alias_wrapper_field['corrections'][0]['alias_additions'][0]['unexpected'] = True
        invalid_wrappers.append(extra_alias_wrapper_field)
        invalid_collection = copy.deepcopy(manifest)
        invalid_collection['corrections'][0]['edition_updates'] = {}
        invalid_wrappers.append(invalid_collection)
        missing_alias_source = copy.deepcopy(manifest)
        missing_alias_source['corrections'][0]['alias_removals'] = [{}]
        invalid_wrappers.append(missing_alias_source)
        missing_link_owner = copy.deepcopy(manifest)
        missing_link_owner['corrections'][0]['link_updates'] = [{'expected': {}}]
        invalid_wrappers.append(missing_link_owner)
        for invalid_manifest in invalid_wrappers:
            with self.subTest(invalid_manifest=invalid_manifest):
                with self.assertRaisesRegex(ValueError, 'unknown fields|invalid edition|invalid alias|invalid link'):
                    self.apply(manifest=invalid_manifest)
                with self.assertRaisesRegex(ValueError, 'unknown fields|invalid edition|invalid alias|invalid link'):
                    work_catalog.project_approved_inline_corrections([], corrections=invalid_manifest)

        unexpected_identifier = copy.deepcopy(self.catalog)
        unexpected_identifier['work_edition_identifiers'].append(
            work_catalog.build_edition_identifier(
                'wed_d870201346843e8d88db',
                scheme='platform',
                authority='amazon',
                value='B097ZSFLYR',
            )
        )
        with self.assertRaisesRegex(ValueError, 'identifier drift'):
            work_catalog.apply_catalog_corrections(unexpected_identifier, manifest)

        remaining_link = copy.deepcopy(self.catalog)
        remaining_link['fetish_work_links'].append(
            {
                'link_id': work_catalog._stable_id(
                    'fwl', 999, 'wrk_d870201346843e8d88db', 'wed_d870201346843e8d88db', None
                ),
                'fetish_id': 999,
                'work_id': 'wrk_d870201346843e8d88db',
                'edition_id': 'wed_d870201346843e8d88db',
                'alias_id': None,
                'position': 0,
                'context_label': '',
                'recommendation_reason': '',
            }
        )
        with self.assertRaisesRegex(ValueError, 'edition still referenced'):
            work_catalog.apply_catalog_corrections(remaining_link, manifest)

        inline = [
            {
                'id': 55,
                'works': [
                    {'title': 'other', 'url': ''},
                    {
                        'title': '露出少女日記（成人向け漫画）',
                        'url': 'https://www.amazon.co.jp/dp/B097ZSFLYR?tag=hekinator-22',
                    },
                ],
            }
        ]
        forward = work_catalog.project_approved_inline_corrections(inline, corrections=manifest)
        self.assertEqual(
            forward['fetishes'][0]['works'][1],
            {'title': '露出少女日記（成人向け漫画）', 'url': 'https://fantia.jp/products/685549'},
        )
        reverse = work_catalog.project_approved_inline_corrections(
            forward['fetishes'], corrections=manifest, direction='reverse'
        )
        self.assertEqual(reverse['fetishes'], inline)

    def quarantine_fixture(self, *, allow_missing=False):
        inline = [{'id': 1, 'name': 'owner', 'works': ['Before', 'Remove me', 'After']}]
        catalog = work_catalog.build_catalog_from_inline(inline)
        expected_work = next(row for row in catalog['works_master'] if row['canonical_title'] == 'Remove me')
        expected_link = next(row for row in catalog['fetish_work_links'] if row['work_id'] == expected_work['work_id'])
        target_work = copy.deepcopy(expected_work)
        target_work['status'] = 'archived'
        removal = {'table': 'fetish_work_links', 'expected': copy.deepcopy(expected_link)}
        if allow_missing:
            removal['allow_missing'] = True
        manifest = {
            'schema_version': 3,
            'catalog_schema_version': 2,
            'corrections': [
                {
                    'correction_id': 'wcc_test_quarantine',
                    'type': 'quarantine_recommendation',
                    'expected_work': copy.deepcopy(expected_work),
                    'target_work': target_work,
                    'edition_updates': [],
                    'edition_additions': [],
                    'edition_removals': [],
                    'alias_additions': [],
                    'alias_removals': [],
                    'link_updates': [],
                    'link_removals': [removal],
                    'review_updates': [],
                }
            ],
        }
        return inline, catalog, manifest, expected_work, expected_link

    def test_v3_quarantine_is_atomic_idempotent_and_reindexes_owner(self):
        _, catalog, manifest, expected_work, expected_link = self.quarantine_fixture()
        original = copy.deepcopy(catalog)

        corrected = work_catalog.apply_catalog_corrections(catalog, manifest)

        self.assertEqual(catalog, original)
        self.assertEqual(
            next(row for row in corrected['works_master'] if row['work_id'] == expected_work['work_id'])['status'],
            'archived',
        )
        self.assertNotIn(expected_link['link_id'], {row['link_id'] for row in corrected['fetish_work_links']})
        owner_links = sorted(corrected['fetish_work_links'], key=lambda row: row['position'])
        self.assertEqual([row['position'] for row in owner_links], [0, 1])
        self.assertEqual(
            [
                next(work['canonical_title'] for work in corrected['works_master'] if work['work_id'] == row['work_id'])
                for row in owner_links
            ],
            ['Before', 'After'],
        )
        self.assertEqual(work_catalog.apply_catalog_corrections(corrected, manifest), corrected)

        drifted = copy.deepcopy(catalog)
        next(row for row in drifted['fetish_work_links'] if row['link_id'] == expected_link['link_id'])[
            'context_label'
        ] = 'drift'
        before = copy.deepcopy(drifted)
        with self.assertRaisesRegex(ValueError, 'source drift'):
            work_catalog.apply_catalog_corrections(drifted, manifest)
        self.assertEqual(drifted, before)

    def test_v3_quarantine_allow_missing_is_explicit_and_fail_closed(self):
        _, catalog, manifest, expected_work, expected_link = self.quarantine_fixture(allow_missing=True)
        catalog['fetish_work_links'] = [
            row for row in catalog['fetish_work_links'] if row['link_id'] != expected_link['link_id']
        ]
        for position, row in enumerate(sorted(catalog['fetish_work_links'], key=lambda item: item['position'])):
            row['position'] = position

        corrected = work_catalog.apply_catalog_corrections(catalog, manifest)

        self.assertEqual(
            next(row for row in corrected['works_master'] if row['work_id'] == expected_work['work_id'])['status'],
            'archived',
        )

        drifted = copy.deepcopy(catalog)
        moved = copy.deepcopy(expected_link)
        moved.update(fetish_id=2, link_id='fwl_moved', position=0)
        drifted['fetish_work_links'].append(moved)
        before = copy.deepcopy(drifted)
        with self.assertRaisesRegex(ValueError, 'quarantined work still referenced'):
            work_catalog.apply_catalog_corrections(drifted, manifest)
        self.assertEqual(drifted, before)

    def test_v3_inline_quarantine_forward_reverse_and_drift_guards(self):
        inline, _, manifest, _, _ = self.quarantine_fixture()

        forward = work_catalog.project_approved_inline_corrections(inline, corrections=manifest)
        self.assertEqual(forward['fetishes'][0]['works'], ['Before', 'After'])
        reverse = work_catalog.project_approved_inline_corrections(
            forward['fetishes'], corrections=manifest, direction='reverse'
        )
        self.assertEqual(reverse['fetishes'], inline)
        reverse_again = work_catalog.project_approved_inline_corrections(
            reverse['fetishes'], corrections=manifest, direction='reverse'
        )
        self.assertEqual(reverse_again['fetishes'], inline)

        cases = []
        moved_owner = copy.deepcopy(inline)
        moved_owner[0]['works'].pop(1)
        moved_owner.append({'id': 2, 'name': 'other', 'works': ['Remove me']})
        cases.append((moved_owner, 'source_owner_drift'))
        moved_position = copy.deepcopy(inline)
        moved_position[0]['works'] = ['Remove me', 'Before', 'After']
        cases.append((moved_position, 'source_position_drift'))
        signature_drift = copy.deepcopy(inline)
        signature_drift[0]['works'][1] = 'Changed'
        cases.append((signature_drift, 'source_absent'))
        duplicate = copy.deepcopy(inline)
        duplicate.append({'id': 2, 'name': 'other', 'works': ['Remove me']})
        cases.append((duplicate, 'duplicate_source_signature'))
        for rows, reason in cases:
            with self.subTest(reason=reason):
                with self.assertRaisesRegex(ValueError, reason):
                    work_catalog.project_approved_inline_corrections(rows, corrections=manifest)

    def test_v3_reverse_restores_removal_before_reversing_shifted_update(self):
        compounds = {'1,2': ['Remove me', 'Middle', 'Old title']}
        compound_rows = [{'key': '1,2', 'id_a': 1, 'id_b': 2, 'works': compounds['1,2']}]
        fetishes = [{'id': 1, 'name': 'one', 'works': []}, {'id': 2, 'name': 'two', 'works': []}]
        catalog = work_catalog.build_catalog_from_inline(fetishes, compound_rows=compound_rows)
        remove_work = next(row for row in catalog['works_master'] if row['canonical_title'] == 'Remove me')
        update_work = next(row for row in catalog['works_master'] if row['canonical_title'] == 'Old title')
        remove_link = next(row for row in catalog['compound_work_links'] if row['work_id'] == remove_work['work_id'])
        update_link = next(row for row in catalog['compound_work_links'] if row['work_id'] == update_work['work_id'])
        archived = copy.deepcopy(remove_work)
        archived['status'] = 'archived'
        renamed = copy.deepcopy(update_work)
        renamed.update(canonical_title='New title', normalized_title='new title')
        empty_rows = {
            'edition_updates': [],
            'edition_additions': [],
            'edition_removals': [],
            'alias_additions': [],
            'alias_removals': [],
            'review_updates': [],
        }
        manifest = {
            'schema_version': 3,
            'catalog_schema_version': 2,
            'corrections': [
                {
                    'correction_id': 'wcc_update_original_pos_2',
                    'type': 'retitle_identity',
                    'expected_work': update_work,
                    'target_work': renamed,
                    **copy.deepcopy(empty_rows),
                    'link_updates': [
                        {
                            'table': 'compound_work_links',
                            'expected': update_link,
                            'edition_id': None,
                            'alias_id': None,
                            'context_label': '',
                        }
                    ],
                    'link_removals': [],
                },
                {
                    'correction_id': 'wcc_remove_pos_0',
                    'type': 'quarantine_recommendation',
                    'expected_work': remove_work,
                    'target_work': archived,
                    **copy.deepcopy(empty_rows),
                    'link_updates': [],
                    'link_removals': [{'table': 'compound_work_links', 'expected': remove_link, 'allow_missing': True}],
                },
            ],
        }

        forward = work_catalog.project_approved_inline_corrections([], compound_rows=compounds, corrections=manifest)
        self.assertEqual(forward['compound_rows'], {'1,2': ['Middle', 'New title']})
        forward_again = work_catalog.project_approved_inline_corrections(
            [], compound_rows=forward['compound_rows'], corrections=manifest
        )
        self.assertEqual(forward_again['compound_rows'], forward['compound_rows'])
        reverse = work_catalog.project_approved_inline_corrections(
            [], compound_rows=forward['compound_rows'], corrections=manifest, direction='reverse'
        )
        self.assertEqual(reverse['compound_rows'], compounds)

        corrected = work_catalog.apply_catalog_corrections(catalog, manifest)
        self.assertEqual(work_catalog.apply_catalog_corrections(corrected, manifest), corrected)
        drifted = copy.deepcopy(corrected)
        owner_links = [row for row in drifted['compound_work_links'] if (row['id_a'], row['id_b']) == (1, 2)]
        updated_link = next(row for row in owner_links if row['work_id'] == update_work['work_id'])
        other_link = next(row for row in owner_links if row['work_id'] != update_work['work_id'])
        updated_link['position'], other_link['position'] = other_link['position'], updated_link['position']
        with self.assertRaisesRegex(ValueError, 'source drift'):
            work_catalog.apply_catalog_corrections(drifted, manifest)

    def test_v3_source_url_locks_existing_removal_edition_for_projection(self):
        url = 'https://www.amazon.co.jp/dp/B07WRK3MF8?tag=hekinator-22'
        inline = [{'id': 1, 'name': 'owner', 'works': [{'title': 'Remove me', 'url': url}]}]
        catalog = work_catalog.build_catalog_from_inline(inline)
        expected_work = next(row for row in catalog['works_master'] if row['canonical_title'] == 'Remove me')
        expected_link = next(row for row in catalog['fetish_work_links'] if row['work_id'] == expected_work['work_id'])
        expected_edition = next(
            row for row in catalog['work_editions'] if row['edition_id'] == expected_link['edition_id']
        )
        archived = copy.deepcopy(expected_work)
        archived['status'] = 'archived'
        manifest = {
            'schema_version': 3,
            'catalog_schema_version': 2,
            'corrections': [
                {
                    'correction_id': 'wcc_existing_edition_quarantine',
                    'type': 'quarantine_recommendation',
                    'expected_work': expected_work,
                    'target_work': archived,
                    'edition_updates': [],
                    'edition_additions': [],
                    'edition_removals': [],
                    'alias_additions': [],
                    'alias_removals': [],
                    'link_updates': [],
                    'link_removals': [{'table': 'fetish_work_links', 'expected': expected_link, 'source_url': url}],
                    'review_updates': [],
                }
            ],
        }

        forward = work_catalog.project_approved_inline_corrections(inline, corrections=manifest)
        self.assertEqual(forward['fetishes'][0]['works'], [])
        reverse = work_catalog.project_approved_inline_corrections(
            forward['fetishes'], corrections=manifest, direction='reverse'
        )
        self.assertEqual(reverse['fetishes'], inline)
        corrected = work_catalog.apply_catalog_corrections(catalog, manifest)
        self.assertEqual(work_catalog.apply_catalog_corrections(corrected, manifest), corrected)

        drifted_inline = copy.deepcopy(inline)
        drifted_inline[0]['works'][0]['url'] = 'https://www.amazon.co.jp/dp/B000000000?tag=hekinator-22'
        with self.assertRaisesRegex(ValueError, 'source_absent'):
            work_catalog.project_approved_inline_corrections(drifted_inline, corrections=manifest)
        drifted_catalog = copy.deepcopy(catalog)
        next(
            row for row in drifted_catalog['work_editions'] if row['edition_id'] == expected_edition['edition_id']
        ).update(
            asin='B000000000',
            canonical_url='https://www.amazon.co.jp/dp/B000000000?tag=hekinator-22',
        )
        with self.assertRaisesRegex(ValueError, 'edition source drift'):
            work_catalog.apply_catalog_corrections(drifted_catalog, manifest)

        missing_lock = copy.deepcopy(manifest)
        missing_lock['corrections'][0]['link_removals'][0].pop('source_url')
        with self.assertRaisesRegex(ValueError, 'invalid_link_removal'):
            work_catalog.project_approved_inline_corrections(inline, corrections=missing_lock)

    def test_v3_manifest_wide_quarantine_removals_are_atomic_and_position_safe(self):
        inline = [
            {'id': 1, 'name': 'one', 'works': ['A', 'B', 'C', 'D']},
            {'id': 2, 'name': 'two', 'works': ['X', 'Y', 'Z']},
        ]
        catalog = work_catalog.build_catalog_from_inline(inline)
        works_by_title = {row['canonical_title']: row for row in catalog['works_master']}
        links_by_owner_title = {}
        for link in catalog['fetish_work_links']:
            title = next(row['canonical_title'] for row in catalog['works_master'] if row['work_id'] == link['work_id'])
            links_by_owner_title[(link['fetish_id'], title)] = link

        corrections = []
        for title, owner in (('A', 1), ('B', 1), ('D', 1), ('Y', 2)):
            expected_work = copy.deepcopy(works_by_title[title])
            target_work = copy.deepcopy(expected_work)
            target_work['status'] = 'archived'
            corrections.append(
                {
                    'correction_id': f'wcc_quarantine_{owner}_{title}',
                    'type': 'quarantine_recommendation',
                    'expected_work': expected_work,
                    'target_work': target_work,
                    'edition_updates': [],
                    'edition_additions': [],
                    'edition_removals': [],
                    'alias_additions': [],
                    'alias_removals': [],
                    'link_updates': [],
                    'link_removals': [
                        {
                            'table': 'fetish_work_links',
                            'expected': copy.deepcopy(links_by_owner_title[(owner, title)]),
                            'allow_missing': True,
                        }
                    ],
                    'review_updates': [],
                }
            )
        manifest = {'schema_version': 3, 'catalog_schema_version': 2, 'corrections': corrections}

        corrected = work_catalog.apply_catalog_corrections(catalog, manifest)
        materialized = work_catalog.materialize_fetish_works(corrected)
        self.assertEqual([row['title'] for row in materialized[1]], ['C'])
        self.assertEqual([row['title'] for row in materialized[2]], ['X', 'Z'])
        self.assertEqual(work_catalog.apply_catalog_corrections(corrected, manifest), corrected)

        partial = copy.deepcopy(catalog)
        partial_works = {row['work_id']: row for row in partial['works_master']}
        partial_works[works_by_title['A']['work_id']]['status'] = 'archived'
        absent_ids = {
            links_by_owner_title[(1, 'A')]['link_id'],
            links_by_owner_title[(2, 'Y')]['link_id'],
        }
        partial['fetish_work_links'] = [row for row in partial['fetish_work_links'] if row['link_id'] not in absent_ids]
        for owner in (1, 2):
            owner_links = sorted(
                (row for row in partial['fetish_work_links'] if row['fetish_id'] == owner),
                key=lambda row: row['position'],
            )
            for position, link in enumerate(owner_links):
                link['position'] = position
        self.assertEqual(work_catalog.apply_catalog_corrections(partial, manifest), corrected)

        drift_cases = []
        signature_drift = copy.deepcopy(catalog)
        next(
            row
            for row in signature_drift['fetish_work_links']
            if row['link_id'] == links_by_owner_title[(1, 'B')]['link_id']
        )['context_label'] = 'drift'
        drift_cases.append(signature_drift)
        position_drift = copy.deepcopy(catalog)
        owner_links = {row['work_id']: row for row in position_drift['fetish_work_links'] if row['fetish_id'] == 1}
        b_link = owner_links[works_by_title['B']['work_id']]
        c_link = owner_links[works_by_title['C']['work_id']]
        b_link['position'], c_link['position'] = c_link['position'], b_link['position']
        drift_cases.append(position_drift)
        for drifted in drift_cases:
            with self.subTest(drift=drifted):
                before = copy.deepcopy(drifted)
                with self.assertRaisesRegex(ValueError, 'link removal source drift'):
                    work_catalog.apply_catalog_corrections(drifted, manifest)
                self.assertEqual(drifted, before)

    def link_rebind_fixture(self):
        old_title = '逃げるは恥だが役に立つ（漫画）'
        canonical_title = '逃げるは恥だが役に立つ'
        url = 'https://www.amazon.co.jp/dp/B00GWVP77W?tag=hekinator-22'
        inline = [{'id': 107, 'name': 'owner', 'works': [{'title': old_title, 'url': url}]}]
        catalog = work_catalog.build_catalog_from_inline(inline)
        work = catalog['works_master'][0]
        work.update(
            canonical_title=canonical_title,
            normalized_title=work_catalog.normalized_work_title(canonical_title),
            media_type='manga',
        )
        alias = {
            'alias_id': work_catalog._stable_id('wal', work['work_id'], work_catalog.normalized_work_title(old_title)),
            'work_id': work['work_id'],
            'alias': old_title,
            'normalized_alias': work_catalog.normalized_work_title(old_title),
        }
        catalog['work_aliases'].append(alias)
        expected_link = copy.deepcopy(catalog['fetish_work_links'][0])
        target_link_id = work_catalog._stable_id(
            'fwl',
            expected_link['fetish_id'],
            expected_link['work_id'],
            expected_link['edition_id'],
            alias['alias_id'],
        )
        manifest = {
            'schema_version': 3,
            'catalog_schema_version': 2,
            'corrections': [
                {
                    'correction_id': 'wcc_optional_production_alias_rebind',
                    'type': 'link_rebind',
                    'expected_work': copy.deepcopy(work),
                    'target_work': copy.deepcopy(work),
                    'alias_references': [{'expected': copy.deepcopy(alias)}],
                    'edition_updates': [],
                    'edition_additions': [],
                    'edition_removals': [],
                    'alias_additions': [],
                    'alias_removals': [],
                    'link_updates': [
                        {
                            'table': 'fetish_work_links',
                            'expected': copy.deepcopy(expected_link),
                            'edition_id': expected_link['edition_id'],
                            'alias_id': alias['alias_id'],
                            'context_label': expected_link['context_label'],
                            'source_url': url,
                            'source_title': old_title,
                            'allow_missing': True,
                        }
                    ],
                    'link_removals': [],
                    'review_updates': [],
                }
            ],
        }
        return inline, catalog, manifest, work, alias, expected_link, target_link_id

    def test_v3_optional_production_link_rebind_is_locked_idempotent_and_parity_neutral(self):
        inline, catalog, manifest, work, alias, expected_link, target_link_id = self.link_rebind_fixture()
        original = copy.deepcopy(catalog)

        corrected = work_catalog.apply_catalog_corrections(catalog, manifest)

        self.assertEqual(catalog, original)
        self.assertEqual(
            next(row for row in corrected['works_master'] if row['work_id'] == work['work_id']),
            work,
        )
        rebound = next(row for row in corrected['fetish_work_links'] if row['link_id'] == target_link_id)
        self.assertEqual(rebound['alias_id'], alias['alias_id'])
        self.assertEqual(rebound['edition_id'], expected_link['edition_id'])
        self.assertNotIn(expected_link['link_id'], {row['link_id'] for row in corrected['fetish_work_links']})
        self.assertEqual(work_catalog.apply_catalog_corrections(corrected, manifest), corrected)
        materialized = work_catalog.materialize_fetish_works(corrected)
        self.assertEqual(materialized[107][0]['title'], alias['alias'])
        self.assertEqual(materialized[107][0]['url'], manifest['corrections'][0]['link_updates'][0]['source_url'])

        seed = copy.deepcopy(catalog)
        seed['fetish_work_links'] = []
        seed['work_editions'] = []
        self.assertEqual(work_catalog.apply_catalog_corrections(seed, manifest), seed)

        forward = work_catalog.project_approved_inline_corrections(inline, corrections=manifest)
        self.assertEqual(forward['fetishes'], inline)
        reverse = work_catalog.project_approved_inline_corrections(
            forward['fetishes'], corrections=manifest, direction='reverse'
        )
        self.assertEqual(reverse['fetishes'], inline)

    def test_v3_optional_production_link_rebind_rejects_all_source_drift(self):
        inline, catalog, manifest, work, alias, expected_link, target_link_id = self.link_rebind_fixture()
        cases = []

        work_drift = copy.deepcopy(catalog)
        next(row for row in work_drift['works_master'] if row['work_id'] == work['work_id'])['media_type'] = 'novel'
        cases.append((work_drift, 'source drift'))
        alias_drift = copy.deepcopy(catalog)
        alias_row = next(row for row in alias_drift['work_aliases'] if row['alias_id'] == alias['alias_id'])
        alias_row.update(alias='different', normalized_alias='different')
        cases.append((alias_drift, 'source drift'))
        link_drift = copy.deepcopy(catalog)
        next(row for row in link_drift['fetish_work_links'] if row['link_id'] == expected_link['link_id'])[
            'context_label'
        ] = 'drift'
        cases.append((link_drift, 'source drift'))
        url_drift = copy.deepcopy(catalog)
        edition = next(row for row in url_drift['work_editions'] if row['edition_id'] == expected_link['edition_id'])
        edition.update(
            asin='B000000000',
            canonical_url='https://www.amazon.co.jp/dp/B000000000?tag=hekinator-22',
        )
        cases.append((url_drift, 'edition source drift'))
        moved = copy.deepcopy(catalog)
        moved_link = next(row for row in moved['fetish_work_links'] if row['link_id'] == expected_link['link_id'])
        moved_link.update(
            fetish_id=108,
            link_id=work_catalog._stable_id(
                'fwl',
                108,
                expected_link['work_id'],
                expected_link['edition_id'],
                None,
            ),
        )
        cases.append((moved, 'source moved'))

        for drifted, message in cases:
            with self.subTest(message=message):
                before = copy.deepcopy(drifted)
                with self.assertRaisesRegex(ValueError, message):
                    work_catalog.apply_catalog_corrections(drifted, manifest)
                self.assertEqual(drifted, before)

        applied = work_catalog.apply_catalog_corrections(catalog, manifest)
        applied_alias_drift = copy.deepcopy(applied)
        next(row for row in applied_alias_drift['work_aliases'] if row['alias_id'] == alias['alias_id']).update(
            alias='different', normalized_alias='different'
        )
        with self.assertRaisesRegex(ValueError, 'source drift'):
            work_catalog.apply_catalog_corrections(applied_alias_drift, manifest)

        inline_drift = copy.deepcopy(inline)
        inline_drift[0]['works'][0]['title'] = 'different'
        with self.assertRaisesRegex(ValueError, 'source_signature_drift'):
            work_catalog.project_approved_inline_corrections(inline_drift, corrections=manifest)

        invalid_url = copy.deepcopy(manifest)
        invalid_url['corrections'][0]['link_updates'][0]['source_url'] = (
            'https://www.amazon.co.jp/dp/B000000000?tag=hekinator-22'
        )
        with self.assertRaisesRegex(ValueError, 'edition source drift'):
            work_catalog.apply_catalog_corrections(catalog, invalid_url)
        invalid_alias = copy.deepcopy(manifest)
        invalid_alias['corrections'][0]['alias_references'][0]['expected']['unexpected'] = True
        with self.assertRaisesRegex(ValueError, 'invalid alias reference'):
            work_catalog.apply_catalog_corrections(catalog, invalid_alias)
        with self.assertRaisesRegex(ValueError, 'invalid link rebind projection'):
            work_catalog.project_approved_inline_corrections(inline, corrections=invalid_alias)

        partial_duplicate = copy.deepcopy(applied)
        duplicate_source = copy.deepcopy(expected_link)
        duplicate_source['position'] = 1
        partial_duplicate['fetish_work_links'].append(duplicate_source)
        with self.assertRaisesRegex(ValueError, 'link rebind source remains'):
            work_catalog.apply_catalog_corrections(partial_duplicate, manifest)

        for schema_version, correction_type in ((3, 'retitle_identity'), (2, 'retitle_identity')):
            invalid_source_fields = copy.deepcopy(manifest)
            invalid_source_fields['schema_version'] = schema_version
            invalid_source_fields['corrections'][0]['type'] = correction_type
            invalid_source_fields['corrections'][0].pop('alias_references')
            invalid_source_fields['corrections'][0].pop('link_removals')
            with self.subTest(schema_version=schema_version, correction_type=correction_type):
                with self.assertRaisesRegex(ValueError, 'invalid link_updates'):
                    work_catalog.apply_catalog_corrections(catalog, invalid_source_fields)
                with self.assertRaisesRegex(ValueError, 'invalid link_updates'):
                    work_catalog.project_approved_inline_corrections(inline, corrections=invalid_source_fields)

        invalid_link = copy.deepcopy(manifest)
        invalid_link['corrections'][0]['link_updates'][0]['expected']['position'] = 999
        with self.assertRaisesRegex(ValueError, 'source drift'):
            work_catalog.apply_catalog_corrections(catalog, invalid_link)

    def test_v3_quarantine_manifest_schema_is_strict(self):
        _, catalog, manifest, _, _ = self.quarantine_fixture()
        invalid_manifests = []

        v2 = copy.deepcopy(manifest)
        v2['schema_version'] = 2
        invalid_manifests.append((v2, 'version 3 fields'))
        active_target = copy.deepcopy(manifest)
        active_target['corrections'][0]['target_work']['status'] = 'active'
        invalid_manifests.append((active_target, 'invalid quarantine target'))
        moved_target = copy.deepcopy(manifest)
        moved_target['corrections'][0]['target_work']['work_id'] = 'wrk_other'
        invalid_manifests.append((moved_target, 'invalid quarantine target'))
        extra_wrapper = copy.deepcopy(manifest)
        extra_wrapper['corrections'][0]['link_removals'][0]['unexpected'] = True
        invalid_manifests.append((extra_wrapper, 'invalid link_removals'))
        incomplete_expected = copy.deepcopy(manifest)
        incomplete_expected['corrections'][0]['link_removals'][0]['expected'].pop('context_label')
        invalid_manifests.append((incomplete_expected, 'invalid link removal'))
        non_bool = copy.deepcopy(manifest)
        non_bool['corrections'][0]['link_removals'][0]['allow_missing'] = 1
        invalid_manifests.append((non_bool, 'invalid link removal'))
        source_url_without_edition = copy.deepcopy(manifest)
        source_url_without_edition['corrections'][0]['link_removals'][0]['source_url'] = (
            'https://example.com/not-allowed'
        )
        invalid_manifests.append((source_url_without_edition, 'invalid link removal'))
        mixed_mutation = copy.deepcopy(manifest)
        mixed_mutation['corrections'][0]['alias_removals'] = [
            {'expected': {'alias_id': 'wal_unknown', 'work_id': 'wrk_unknown'}}
        ]
        invalid_manifests.append((mixed_mutation, 'quarantine must only remove links'))

        for invalid, message in invalid_manifests:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    work_catalog.apply_catalog_corrections(catalog, invalid)
                with self.assertRaises(ValueError):
                    work_catalog.project_approved_inline_corrections([], corrections=invalid)

    def test_v1_manifest_compatibility_and_v2_field_guard(self):
        legacy = copy.deepcopy(self.manifest)
        legacy['schema_version'] = 1
        legacy['catalog_schema_version'] = 1
        legacy['corrections'] = legacy['corrections'][:4]
        corrected = self.apply(manifest=legacy)
        self.assertTrue(work_catalog.validate_catalog(corrected))

        invalid = copy.deepcopy(legacy)
        invalid['corrections'][0]['edition_additions'] = []
        with self.assertRaisesRegex(ValueError, 'version 2 fields'):
            self.apply(manifest=invalid)

    def test_manifest_schema_and_duplicate_ids_are_rejected(self):
        for manifest in ({}, {'schema_version': 1, 'catalog_schema_version': 1, 'corrections': [{}, {}]}):
            with self.subTest(manifest=manifest):
                with self.assertRaisesRegex(ValueError, 'schema_version|missing or duplicate'):
                    self.apply(manifest=manifest)


if __name__ == '__main__':
    unittest.main()
