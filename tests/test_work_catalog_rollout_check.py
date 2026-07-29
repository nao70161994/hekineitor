import unittest

from scripts import work_catalog_rollout_check


def migration_payload(worker_id='worker-a:1', revision=7, **overrides):
    migration = {
        'status': 'ok',
        'automated_parity_ok': True,
        'mismatch_count': 0,
        'pending_review_count': 0,
        'worker_id': worker_id,
        'snapshot_revision': revision,
        'database_revision': revision,
        'cached_revision': revision,
        'cache_revision_matches_database': True,
        'runtime_observation': {
            'catalog_reads_since_start': 10,
            'legacy_fallback_reads_since_start': 0,
            'catalog_load_failures_since_start': 0,
        },
        'retirement': {'automated_eligible': True, 'blockers': []},
    }
    migration.update(overrides)
    return {'status': 'ok', 'migration': migration}


class WorkCatalogRolloutCheckTests(unittest.TestCase):
    def test_build_report_accepts_complete_consistent_worker_set(self):
        report = work_catalog_rollout_check.build_report(
            [migration_payload(), migration_payload('worker-b:2'), migration_payload()],
            expected_worker_count=2,
            observation_seconds=60,
            minimum_observation_seconds=55,
            observed_at='2026-07-28T00:00:00+00:00',
        )

        self.assertTrue(report['automated_gate_ok'])
        self.assertTrue(report['manual_signoff_required'])
        self.assertEqual(report['observed_worker_count'], 2)
        self.assertEqual(report['workers']['worker-a:1']['sample_count'], 2)
        self.assertEqual(report['workers']['worker-b:2']['database_revisions'], [7])

    def test_build_report_rejects_pending_fallback_revision_and_missing_worker(self):
        bad = migration_payload(
            pending_review_count=3,
            snapshot_revision=6,
            cache_revision_matches_database=False,
            runtime_observation={
                'catalog_reads_since_start': 0,
                'legacy_fallback_reads_since_start': 2,
                'catalog_load_failures_since_start': 1,
            },
            retirement={
                'automated_eligible': False,
                'blockers': ['pending_identity_reviews', 'legacy_fallback_observed'],
            },
        )
        report = work_catalog_rollout_check.build_report(
            [bad],
            expected_worker_count=2,
            observation_seconds=10,
            minimum_observation_seconds=55,
        )

        self.assertFalse(report['automated_gate_ok'])
        self.assertIn('expected_worker_set_not_observed', report['errors'])
        self.assertIn('observation_window_too_short', report['errors'])
        self.assertIn('worker_gate_failed', report['errors'])
        worker_errors = report['workers']['worker-a:1']['errors']
        self.assertIn('pending_identity_reviews', worker_errors)
        self.assertIn('legacy_fallback_observed', worker_errors)
        self.assertIn('catalog_load_failure_observed', worker_errors)
        self.assertIn('worker_catalog_revision_mismatch', worker_errors)

    def test_build_report_rejects_cross_worker_database_revision_drift(self):
        report = work_catalog_rollout_check.build_report(
            [migration_payload(revision=7), migration_payload('worker-b:2', revision=8)],
            expected_worker_count=2,
            observation_seconds=60,
            minimum_observation_seconds=55,
        )

        self.assertFalse(report['automated_gate_ok'])
        self.assertIn('workers_observed_different_database_revisions', report['errors'])

    def test_collect_report_uses_bounded_environment_and_observation_clock(self):
        times = iter([100.0, 106.0])
        calls = []
        sleeps = []
        report = work_catalog_rollout_check.collect_report(
            environ={
                'WORK_CATALOG_EXPECTED_WORKERS': 'bad',
                'WORK_CATALOG_OBSERVATION_SAMPLES': '2',
                'WORK_CATALOG_OBSERVATION_INTERVAL_SECONDS': '3',
                'WORK_CATALOG_MIN_OBSERVATION_SECONDS': '5',
            },
            json_getter=lambda path: calls.append(path) or migration_payload(),
            sleep_fn=sleeps.append,
            monotonic_fn=lambda: next(times),
        )

        self.assertTrue(report['automated_gate_ok'])
        self.assertEqual(report['expected_worker_count'], 1)
        self.assertEqual(report['observation_seconds'], 6.0)
        self.assertEqual(calls, ['/api/admin/works_health', '/api/admin/works_health'])
        self.assertEqual(sleeps, [3])


if __name__ == '__main__':
    unittest.main()
