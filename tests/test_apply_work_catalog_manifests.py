import copy
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from engine import work_catalog
from scripts import apply_work_catalog_manifests


class FakeClient:
    def __init__(self, catalog):
        self.catalog = copy.deepcopy(catalog)
        self.calls = []

    def csrf_token(self):
        return 'csrf'

    def json(self, path, *, method='GET', payload=None, csrf=''):
        self.calls.append((path, method, payload, csrf))
        if path == '/api/admin/work_catalog':
            return {
                'status': 'ok',
                'digest': work_catalog.catalog_digest(self.catalog),
                'catalog': copy.deepcopy(self.catalog),
            }
        if path == '/api/admin/works_health':
            return {
                'status': 'ok',
                'migration': {
                    'automated_parity_ok': True,
                    'mismatch_count': 0,
                    'approved_projection_ok': True,
                    'approved_mismatch_count': 0,
                    'pending_review_count': 0,
                    'snapshot_revision': 2,
                    'database_revision': 2,
                    'cached_revision': 2,
                    'cache_revision_matches_database': True,
                    'worker_id': 'worker:1',
                    'runtime_observation': {
                        'legacy_fallback_reads_since_start': 0,
                        'catalog_load_failures_since_start': 0,
                    },
                },
            }
        if path.startswith('/api/admin/audit_log'):
            return {
                'status': 'ok',
                'audit_log': [
                    {
                        'action': 'work_catalog_mutation',
                        'status': 'ok',
                        'detail': {
                            'operation': 'review_apply_manifest',
                            'manifest_sha256': apply_work_catalog_manifests.REVIEW_SHA256,
                        },
                    },
                    {
                        'action': 'work_catalog_mutation',
                        'status': 'ok',
                        'detail': {
                            'operation': 'seed_overrides_apply_manifest',
                            'manifest_sha256': apply_work_catalog_manifests.SEED_SHA256,
                        },
                    },
                    {
                        'action': 'work_catalog_mutation',
                        'status': 'ok',
                        'detail': {
                            'operation': 'corrections_apply_manifest',
                            'manifest_sha256': apply_work_catalog_manifests.CORRECTIONS_SHA256,
                        },
                    },
                    {
                        'action': 'work_catalog_mutation',
                        'status': 'ok',
                        'detail': {
                            'operation': 'bibliography_apply_manifest',
                            'manifest_sha256': apply_work_catalog_manifests.BIBLIOGRAPHY_SHA256,
                        },
                    },
                ],
            }
        operation = payload['operation']
        if operation == 'review_apply_manifest':
            self.catalog = work_catalog.apply_review_decisions(self.catalog, payload['payload']['decision_manifest'])
            result = {'resolved_count': 74, 'pending_count': 0}
        elif operation == 'seed_overrides_apply_manifest':
            before = len(self.catalog['works_master'])
            self.catalog = work_catalog.apply_seed_overrides(self.catalog, payload['payload']['seed_overrides'])
            result = {
                'normalized_title_count': 46,
                'removed_work_count': before - len(self.catalog['works_master']),
            }
        elif operation == 'bibliography_apply_manifest':
            self.catalog, result = work_catalog.apply_bibliography_manifest(
                self.catalog, payload['payload']['bibliography_manifest']
            )
        else:
            manifest = payload['payload']['corrections_manifest']
            self.catalog = work_catalog.apply_catalog_corrections(self.catalog, manifest)
            rows = manifest['corrections']
            result = {
                'correction_count': len(rows),
                'split_count': sum(row.get('type') == 'split_misassigned_edition' for row in rows),
                'retitle_count': sum(row.get('type') == 'retitle_identity' for row in rows),
                'inline_applied_link_count': 0,
                'inline_fetish_owner_count': 0,
                'inline_compound_owner_count': 0,
                'inline_missing_count': 0,
            }
        return {'status': 'ok', 'digest': work_catalog.catalog_digest(self.catalog), 'result': result}


class ApplyWorkCatalogManifestsTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1]
        data = self.root / 'data'
        fetishes = json.loads((data / 'fetishes.json').read_text(encoding='utf-8'))
        compounds = json.loads((data / 'compound_works.json').read_text(encoding='utf-8'))
        self.bibliography = json.loads((data / 'work_catalog_bibliography.json').read_text(encoding='utf-8'))
        compound_rows = []
        for key, works in compounds.items():
            id_a, id_b = key.split(',', 1)
            compound_rows.append({'key': key, 'id_a': int(id_a), 'id_b': int(id_b), 'works': works})
        corrections = json.loads((data / 'work_catalog_corrections.json').read_text(encoding='utf-8'))
        source = work_catalog.project_approved_inline_corrections(
            fetishes,
            compound_rows=compound_rows,
            corrections=corrections,
            direction='reverse',
        )
        fetishes = source['fetishes']
        compound_rows = source['compound_rows']
        self.raw_catalog = work_catalog.build_catalog_from_inline(fetishes, compound_rows=compound_rows)
        seed = json.loads((data / 'work_catalog_seed_overrides.json').read_text(encoding='utf-8'))
        review = json.loads((data / 'work_catalog_review_decisions.json').read_text(encoding='utf-8'))
        catalog = work_catalog.build_catalog_from_inline(
            fetishes,
            compound_rows=compound_rows,
            seed_overrides=seed,
        )
        self.catalog = work_catalog.apply_review_decisions(catalog, review)
        self.final_catalog = work_catalog.apply_catalog_corrections(self.catalog, corrections)
        self.bibliography_catalog = work_catalog.apply_bibliography_manifest(self.final_catalog, self.bibliography)[0]

    def test_rejects_non_https_or_wrong_host(self):
        for url in ('http://example.com', 'https://other.example', 'https://example.com/path'):
            with self.subTest(url=url), self.assertRaises(RuntimeError):
                apply_work_catalog_manifests._validate_target(url, 'example.com')

    def test_admin_client_retries_transient_get_only(self):
        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return b'{}'

        class Opener:
            def __init__(self):
                self.calls = 0

            def open(self, _request, timeout):
                self.calls += 1
                self.timeout = timeout
                if self.calls < 3:
                    raise urllib.error.URLError(ConnectionResetError('connection reset'))
                return Response()

        client = apply_work_catalog_manifests.AdminClient('https://example.com', 'admin', 'secret')
        opener = Opener()
        client._opener = opener
        with patch.object(apply_work_catalog_manifests.time, 'sleep') as sleep:
            self.assertEqual(client.request('/health'), (200, b'{}'))
        self.assertEqual(opener.calls, 3)
        self.assertEqual(opener.timeout, 60)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [1, 2])

    def test_admin_client_never_retries_post(self):
        class Opener:
            def __init__(self):
                self.calls = 0

            def open(self, _request, timeout):
                self.calls += 1
                raise urllib.error.URLError(ConnectionResetError('connection reset'))

        client = apply_work_catalog_manifests.AdminClient('https://example.com', 'admin', 'secret')
        opener = Opener()
        client._opener = opener
        with (
            patch.object(apply_work_catalog_manifests.time, 'sleep') as sleep,
            self.assertRaises(urllib.error.URLError),
        ):
            client.request('/api/admin/work_catalog/mutate', method='POST', payload={})
        self.assertEqual(opener.calls, 1)
        sleep.assert_not_called()

    def test_rejects_manifest_hash_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'manifest.json'
            path.write_text('{}', encoding='utf-8')
            with self.assertRaisesRegex(RuntimeError, 'SHA-256 mismatch'):
                apply_work_catalog_manifests._load_manifest(path, '0' * 64)

    def test_applies_in_order_with_digest_lock_backup_and_health(self):
        fake = FakeClient(self.catalog)
        with tempfile.TemporaryDirectory() as directory:
            backup = Path(directory) / 'backup.json'
            backup.write_text(json.dumps({'work_catalog': self.catalog}), encoding='utf-8')
            with patch.object(apply_work_catalog_manifests, 'AdminClient', return_value=fake):
                evidence = apply_work_catalog_manifests.apply_manifests(
                    base_url='https://hekineitor.onrender.com',
                    expected_host='hekineitor.onrender.com',
                    username='admin',
                    password='secret',
                    review_path=self.root / 'data/work_catalog_review_decisions.json',
                    legacy_review_path=self.root / 'data/work_catalog_review_decisions_legacy_v0.json',
                    seed_path=self.root / 'data/work_catalog_seed_overrides.json',
                    corrections_path=self.root / 'data/work_catalog_corrections.json',
                    bibliography_path=self.root / 'data/work_catalog_bibliography.json',
                    backup_path=backup,
                )
        mutations = [call for call in fake.calls if call[0].endswith('/mutate')]
        self.assertEqual(
            [call[2]['operation'] for call in mutations],
            [
                'review_apply_manifest',
                'seed_overrides_apply_manifest',
                'corrections_apply_manifest',
                'bibliography_apply_manifest',
            ],
        )
        self.assertTrue(all(call[2]['confirm_text'] == 'WORK_CATALOG' for call in mutations))
        self.assertEqual(evidence['final_digest'], work_catalog.catalog_digest(self.bibliography_catalog))
        self.assertNotIn('secret', json.dumps(evidence))

    def test_pre_review_source_reaches_the_same_approved_final_catalog(self):
        fake = FakeClient(self.raw_catalog)
        with tempfile.TemporaryDirectory() as directory:
            backup = Path(directory) / 'backup.json'
            backup.write_text(json.dumps({'work_catalog': self.raw_catalog}), encoding='utf-8')
            with patch.object(apply_work_catalog_manifests, 'AdminClient', return_value=fake):
                evidence = apply_work_catalog_manifests.apply_manifests(
                    base_url='https://hekineitor.onrender.com',
                    expected_host='hekineitor.onrender.com',
                    username='admin',
                    password='secret',
                    review_path=self.root / 'data/work_catalog_review_decisions.json',
                    legacy_review_path=self.root / 'data/work_catalog_review_decisions_legacy_v0.json',
                    seed_path=self.root / 'data/work_catalog_seed_overrides.json',
                    corrections_path=self.root / 'data/work_catalog_corrections.json',
                    bibliography_path=self.root / 'data/work_catalog_bibliography.json',
                    backup_path=backup,
                )
        mutations = [call[2]['operation'] for call in fake.calls if call[0].endswith('/mutate')]
        self.assertEqual(
            mutations,
            [
                'review_apply_manifest',
                'seed_overrides_apply_manifest',
                'corrections_apply_manifest',
                'bibliography_apply_manifest',
            ],
        )
        self.assertEqual(evidence['final_digest'], work_catalog.catalog_digest(self.bibliography_catalog))

    def test_accepts_durable_review_timestamp_and_preserves_player_replacement(self):
        catalog = copy.deepcopy(self.catalog)
        review = next(row for row in catalog['review_queue'] if row['review_id'] == 'wrv_66989c04b744aa1a5b64')
        review['updated_at'] = '2026-07-29T00:00:00+00:00'
        catalog['fetish_work_links'] = [
            row for row in catalog['fetish_work_links'] if row['link_id'] != 'fwl_0491358730a92c95b5dc'
        ]
        catalog['work_aliases'] = [
            row for row in catalog['work_aliases'] if row['alias_id'] != 'wal_d6cfef435e8063b178c5'
        ]
        owner_work_ids = {row['work_id'] for row in catalog['fetish_work_links'] if row['fetish_id'] == 104}
        replacement = copy.deepcopy(
            next(row for row in catalog['fetish_work_links'] if row['work_id'] not in owner_work_ids)
        )
        replacement.update({'link_id': 'fwl_player_replacement', 'fetish_id': 104, 'position': 1})
        catalog['fetish_work_links'].append(replacement)
        fake = FakeClient(catalog)

        with tempfile.TemporaryDirectory() as directory:
            backup = Path(directory) / 'backup.json'
            backup.write_text(json.dumps({'work_catalog': catalog}), encoding='utf-8')
            with patch.object(apply_work_catalog_manifests, 'AdminClient', return_value=fake):
                apply_work_catalog_manifests.apply_manifests(
                    base_url='https://hekineitor.onrender.com',
                    expected_host='hekineitor.onrender.com',
                    username='admin',
                    password='secret',
                    review_path=self.root / 'data/work_catalog_review_decisions.json',
                    legacy_review_path=self.root / 'data/work_catalog_review_decisions_legacy_v0.json',
                    seed_path=self.root / 'data/work_catalog_seed_overrides.json',
                    corrections_path=self.root / 'data/work_catalog_corrections.json',
                    bibliography_path=self.root / 'data/work_catalog_bibliography.json',
                    backup_path=backup,
                )

        self.assertTrue(
            any(
                row['fetish_id'] == 104 and row['work_id'] == replacement['work_id']
                for row in fake.catalog['fetish_work_links']
            )
        )
        corrected_review = next(
            row for row in fake.catalog['review_queue'] if row['review_id'] == 'wrv_66989c04b744aa1a5b64'
        )
        self.assertEqual(corrected_review['decision'], 'keep_separate')

    def test_reapply_skips_superseded_review_and_keeps_final_catalog(self):
        fake = FakeClient(self.bibliography_catalog)
        with tempfile.TemporaryDirectory() as directory:
            backup = Path(directory) / 'backup.json'
            backup.write_text(json.dumps({'work_catalog': self.bibliography_catalog}), encoding='utf-8')
            with patch.object(apply_work_catalog_manifests, 'AdminClient', return_value=fake):
                evidence = apply_work_catalog_manifests.apply_manifests(
                    base_url='https://hekineitor.onrender.com',
                    expected_host='hekineitor.onrender.com',
                    username='admin',
                    password='secret',
                    review_path=self.root / 'data/work_catalog_review_decisions.json',
                    legacy_review_path=self.root / 'data/work_catalog_review_decisions_legacy_v0.json',
                    seed_path=self.root / 'data/work_catalog_seed_overrides.json',
                    corrections_path=self.root / 'data/work_catalog_corrections.json',
                    bibliography_path=self.root / 'data/work_catalog_bibliography.json',
                    backup_path=backup,
                )
        mutations = [call[2]['operation'] for call in fake.calls if call[0].endswith('/mutate')]
        self.assertEqual(
            mutations,
            ['seed_overrides_apply_manifest', 'corrections_apply_manifest', 'bibliography_apply_manifest'],
        )
        self.assertTrue(evidence['review_result']['skipped'])
        self.assertEqual(evidence['before_digest'], evidence['final_digest'])

    def test_rejects_nonzero_raw_parity_after_inline_sync(self):
        fake = FakeClient(self.final_catalog)
        original_json = fake.json

        def mismatched_health(path, **kwargs):
            result = original_json(path, **kwargs)
            if path == '/api/admin/works_health':
                result['migration']['automated_parity_ok'] = False
                result['migration']['mismatch_count'] = 1
            return result

        fake.json = mismatched_health
        with tempfile.TemporaryDirectory() as directory:
            backup = Path(directory) / 'backup.json'
            backup.write_text(json.dumps({'work_catalog': self.final_catalog}), encoding='utf-8')
            with (
                patch.object(apply_work_catalog_manifests, 'AdminClient', return_value=fake),
                self.assertRaisesRegex(RuntimeError, 'catalog gates'),
            ):
                apply_work_catalog_manifests.apply_manifests(
                    base_url='https://hekineitor.onrender.com',
                    expected_host='hekineitor.onrender.com',
                    username='admin',
                    password='secret',
                    review_path=self.root / 'data/work_catalog_review_decisions.json',
                    legacy_review_path=self.root / 'data/work_catalog_review_decisions_legacy_v0.json',
                    seed_path=self.root / 'data/work_catalog_seed_overrides.json',
                    corrections_path=self.root / 'data/work_catalog_corrections.json',
                    bibliography_path=self.root / 'data/work_catalog_bibliography.json',
                    backup_path=backup,
                )

    def test_rejects_backup_catalog_drift_before_mutation(self):
        fake = FakeClient(self.catalog)
        drifted = copy.deepcopy(self.catalog)
        drifted['works_master'][0]['canonical_title'] += ' drift'
        with tempfile.TemporaryDirectory() as directory:
            backup = Path(directory) / 'backup.json'
            backup.write_text(json.dumps({'work_catalog': drifted}), encoding='utf-8')
            with (
                patch.object(apply_work_catalog_manifests, 'AdminClient', return_value=fake),
                self.assertRaisesRegex(RuntimeError, 'backup catalog digest'),
            ):
                apply_work_catalog_manifests.apply_manifests(
                    base_url='https://hekineitor.onrender.com',
                    expected_host='hekineitor.onrender.com',
                    username='admin',
                    password='secret',
                    review_path=self.root / 'data/work_catalog_review_decisions.json',
                    legacy_review_path=self.root / 'data/work_catalog_review_decisions_legacy_v0.json',
                    corrections_path=self.root / 'data/work_catalog_corrections.json',
                    bibliography_path=self.root / 'data/work_catalog_bibliography.json',
                    seed_path=self.root / 'data/work_catalog_seed_overrides.json',
                    backup_path=backup,
                )
        self.assertFalse(any(call[0].endswith('/mutate') for call in fake.calls))


if __name__ == '__main__':
    unittest.main()
