import copy
import json
import tempfile
import unittest
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
                ],
            }
        operation = payload['operation']
        if operation == 'review_apply_manifest':
            self.catalog = work_catalog.apply_review_decisions(self.catalog, payload['payload']['decision_manifest'])
            result = {'resolved_count': 74, 'pending_count': 0}
        else:
            before = len(self.catalog['works_master'])
            self.catalog = work_catalog.apply_seed_overrides(self.catalog, payload['payload']['seed_overrides'])
            result = {
                'normalized_title_count': 46,
                'removed_work_count': before - len(self.catalog['works_master']),
            }
        return {'status': 'ok', 'digest': work_catalog.catalog_digest(self.catalog), 'result': result}


class ApplyWorkCatalogManifestsTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1]
        self.catalog = json.loads((self.root / 'data/work_catalog.json').read_text(encoding='utf-8'))

    def test_rejects_non_https_or_wrong_host(self):
        for url in ('http://example.com', 'https://other.example', 'https://example.com/path'):
            with self.subTest(url=url), self.assertRaises(RuntimeError):
                apply_work_catalog_manifests._validate_target(url, 'example.com')

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
                    backup_path=backup,
                )
        mutations = [call for call in fake.calls if call[0].endswith('/mutate')]
        self.assertEqual(
            [call[2]['operation'] for call in mutations],
            ['review_apply_manifest', 'seed_overrides_apply_manifest'],
        )
        self.assertTrue(all(call[2]['confirm_text'] == 'WORK_CATALOG' for call in mutations))
        self.assertEqual(evidence['final_digest'], work_catalog.catalog_digest(self.catalog))
        self.assertNotIn('secret', json.dumps(evidence))

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
                    seed_path=self.root / 'data/work_catalog_seed_overrides.json',
                    backup_path=backup,
                )
        self.assertFalse(any(call[0].endswith('/mutate') for call in fake.calls))


if __name__ == '__main__':
    unittest.main()
