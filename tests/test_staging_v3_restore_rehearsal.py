import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import staging_v3_restore_rehearsal as rehearsal


class FakePublicClient:
    def json(self, path, **kwargs):
        if path == '/health':
            return {'status': 'ok', 'storage': 'postgres', 'db': True, 'matrix': {'ok': True}}
        if path == '/api/start':
            return {'question_id': 3, 'question': '質問ですか？'}
        raise AssertionError(path)

    def request(self, path, **kwargs):
        if path == '/':
            body = '<link rel="canonical"><meta property="og:title">'
        elif path == '/fetishes':
            body = '<meta property="og:title">'
        elif path == '/fetish/2':
            body = (
                '<link rel="canonical"><script type="application/ld+json"></script>'
                '<a href="https://www.amazon.co.jp/dp/ABCDEFGHIJ?tag=hekinator-22">work</a>'
            )
        else:
            raise AssertionError(path)
        return 200, body.encode(), {}


class StagingV3RestoreRehearsalTests(unittest.TestCase):
    def test_target_guard_accepts_only_explicit_distinct_https_staging(self):
        self.assertEqual(
            rehearsal.guarded_staging_url(
                'https://staging.example.test/',
                'staging.example.test',
                'https://www.example.test',
                rehearsal.CONFIRM_TEXT,
            ),
            'https://staging.example.test',
        )
        bad_cases = [
            ('http://staging.example.test', 'staging.example.test', 'https://www.example.test', rehearsal.CONFIRM_TEXT),
            ('https://www.example.test', 'www.example.test', 'https://www.example.test', rehearsal.CONFIRM_TEXT),
            (
                'https://staging.example.test/path',
                'staging.example.test',
                'https://www.example.test',
                rehearsal.CONFIRM_TEXT,
            ),
            ('https://staging.example.test', 'other.example.test', 'https://www.example.test', rehearsal.CONFIRM_TEXT),
            ('https://staging.example.test', 'staging.example.test', 'https://www.example.test', 'restore'),
        ]
        for args in bad_cases:
            with self.subTest(args=args), self.assertRaises(ValueError):
                rehearsal.guarded_staging_url(*args)

    def test_import_count_validation_is_lossless(self):
        dry = rehearsal.validate_dry_run(
            {
                'status': 'ok',
                'complete': True,
                'expected_rows': 12,
                'valid_rows': 12,
                'skipped_rows': 0,
                'restorable_fetish_count': 2,
                'ignored_source_rows': 0,
            }
        )
        result = rehearsal.validate_import_result(
            {
                'status': 'ok',
                'expected_rows': 12,
                'imported_rows': 12,
                'skipped_rows': 0,
                'ignored_source_rows': 0,
                'restored_source_rows': 12,
                'restored_fetish_count': 2,
            },
            12,
            2,
        )
        self.assertEqual(dry['expected_rows'], 12)
        self.assertEqual(result['restored_source_rows'], 12)
        self.assertEqual(result['restored_fetish_count'], 2)
        with self.assertRaises(ValueError):
            rehearsal.validate_import_result(
                {
                    'status': 'ok',
                    'expected_rows': 12,
                    'imported_rows': 11,
                    'skipped_rows': 1,
                    'ignored_source_rows': 0,
                    'restored_source_rows': 11,
                },
                12,
            )

    def test_works_health_requires_parity_revision_and_no_fallback(self):
        migration = {
            'status': 'ok',
            'automated_parity_ok': True,
            'mismatch_count': 0,
            'pending_review_count': 0,
            'cache_revision_matches_database': True,
            'snapshot_revision': 9,
            'database_revision': 9,
            'cached_revision': 9,
            'worker_id': 'worker:1',
            'runtime_observation': {'legacy_fallback_reads_since_start': 0, 'catalog_load_failures_since_start': 0},
        }
        report = rehearsal.validate_works_health({'status': 'ok', 'migration': migration})
        self.assertEqual(report['database_revision'], 9)
        migration['pending_review_count'] = 1
        with self.assertRaisesRegex(ValueError, 'pending identity reviews'):
            rehearsal.validate_works_health({'status': 'ok', 'migration': migration})

    def test_public_smoke_covers_root_fetish_diagnosis_compound_and_affiliate(self):
        catalog = {
            'work_editions': [
                {
                    'edition_id': 'e1',
                    'status': 'active',
                    'canonical_url': 'https://www.amazon.co.jp/dp/ABCDEFGHIJ',
                }
            ],
            'fetish_work_links': [{'fetish_id': 2, 'edition_id': 'e1'}],
            'compound_work_links': [{'link_id': 'c1'}],
        }
        report = rehearsal.public_smoke(FakePublicClient(), catalog)
        self.assertTrue(report['compound_catalog']['manual_compound_result_signoff_required'])
        self.assertTrue(report['fetish_detail']['affiliate'])
        self.assertTrue(report['diagnosis_start']['question_contract'])
        self.assertEqual(report['compound_catalog']['link_count'], 1)

    def test_workflow_uses_staging_only_credentials_and_guards_before_download(self):
        workflow = (Path(__file__).parents[1] / '.github/workflows/staging_v3_restore_rehearsal.yml').read_text()
        self.assertLess(
            workflow.index('Fail closed before staging access'),
            workflow.index('Download Matrix Backup artifact by run_id'),
        )
        self.assertIn('environment: staging', workflow)
        self.assertIn('secrets.STAGING_APP_URL', workflow)
        self.assertIn('secrets.STAGING_ADMIN_USER', workflow)
        self.assertIn('secrets.STAGING_ADMIN_PASS', workflow)
        self.assertIn('secrets.PRODUCTION_APP_URL', workflow)
        self.assertNotIn('secrets.APP_URL', workflow)
        self.assertNotIn('secrets.ADMIN_USER', workflow)
        self.assertNotIn('secrets.ADMIN_PASS', workflow)

    def test_provision_workflow_creates_only_isolated_staging_resources(self):
        workflow = (Path(__file__).parents[1] / '.github/workflows/provision-isolated-staging.yml').read_text()
        self.assertIn("inputs.confirm == 'PROVISION ISOLATED STAGING'", workflow)
        self.assertIn('environment: staging', workflow)
        self.assertIn("'name': STAGING_NAME", workflow)
        self.assertIn("'plan': 'starter'", workflow)
        self.assertIn("'plan': 'basic_256mb'", workflow)
        self.assertIn("'cidrBlock': '192.0.2.0/32'", workflow)
        self.assertIn("'ipAllowList': DENY_EXTERNAL_IP_ALLOW_LIST", workflow)
        self.assertIn("api('PATCH', f'/postgres/{database_id}'", workflow)
        self.assertIn('Staging database external access could not be disabled', workflow)
        self.assertIn("'autoDeploy': 'no'", workflow)
        self.assertIn("'branch': 'main'", workflow)
        self.assertIn('secrets.STAGING_ADMIN_USER', workflow)
        self.assertIn('secrets.STAGING_ADMIN_PASS', workflow)
        self.assertNotIn('secrets.RENDER_POSTGRES_ID', workflow)
        self.assertNotIn('secrets.ADMIN_USER', workflow)
        self.assertNotIn('secrets.ADMIN_PASS', workflow)

    def test_run_rehearsal_rejects_catalog_digest_drift_after_import(self):
        class Client:
            def csrf_token(self):
                return 'csrf'

            def json(self, path, **kwargs):
                if path.endswith('dry_run'):
                    return {
                        'status': 'ok',
                        'complete': True,
                        'expected_rows': 1,
                        'valid_rows': 1,
                        'skipped_rows': 0,
                        'ignored_source_rows': 0,
                    }
                if path == '/api/admin/import_matrix':
                    return {
                        'status': 'ok',
                        'expected_rows': 1,
                        'imported_rows': 1,
                        'skipped_rows': 0,
                        'ignored_source_rows': 0,
                        'restored_source_rows': 1,
                    }
                if path == '/api/admin/export_matrix':
                    return {'work_catalog': {'schema_version': 1}}
                raise AssertionError(path)

        with (
            patch.object(rehearsal, 'validate', return_value={'version': 3}),
            patch.object(rehearsal, 'catalog_digest', side_effect=['before', 'after']),
            self.assertRaisesRegex(ValueError, 'digest changed'),
        ):
            rehearsal.run_rehearsal(backup={'work_catalog': {'schema_version': 1}}, client=Client(), backup_run_id=1)


if __name__ == '__main__':
    unittest.main()
