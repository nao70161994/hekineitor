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
        self.assertEqual(len(corrected['work_editions']), len(self.catalog['work_editions']))
        self.assertEqual(len(corrected['work_aliases']), len(self.catalog['work_aliases']) - 4)
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
            }
        ]
        source_ids = {
            update['expected']['link_id']
            for correction in self.manifest['corrections']
            for update in correction['link_updates']
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

    def test_manifest_schema_and_duplicate_ids_are_rejected(self):
        for manifest in ({}, {'schema_version': 1, 'catalog_schema_version': 1, 'corrections': [{}, {}]}):
            with self.subTest(manifest=manifest):
                with self.assertRaisesRegex(ValueError, 'schema_version|missing or duplicate'):
                    self.apply(manifest=manifest)


if __name__ == '__main__':
    unittest.main()
