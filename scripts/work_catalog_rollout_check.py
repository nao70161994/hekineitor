#!/usr/bin/env python3
"""Read-only production gate for catalog runtime and legacy retirement readiness."""

from __future__ import annotations

import json
import os
import sys
import time
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from scripts.operations_check import fetch_json
except ModuleNotFoundError:  # pragma: no cover - direct script execution fallback
    from operations_check import fetch_json

REPORT_PATH = Path('artifacts/work_catalog_rollout_report.json')


def _env_int(environ: Mapping[str, str], name: str, default: int, *, minimum: int = 0) -> int:
    try:
        value = int(environ.get(name, default))
    except (TypeError, ValueError):
        value = default
    return max(minimum, value)


def _migration_errors(migration: Mapping[str, Any]) -> list[str]:
    errors = []
    if migration.get('status') != 'ok':
        errors.append('migration_report_unavailable')
    if 'approved_projection_ok' in migration or 'approved_mismatch_count' in migration:
        approved_ok = migration.get('approved_projection_ok') is True
        approved_mismatches = int(migration.get('approved_mismatch_count') or 0)
    else:
        # Old workers only expose raw parity. It is a conservative fallback
        # while a deployment with the additive health fields is rolling.
        approved_ok = migration.get('automated_parity_ok') is True
        approved_mismatches = int(migration.get('mismatch_count') or 0)
    if not approved_ok or approved_mismatches:
        errors.append('catalog_approved_projection_mismatch')
    if int(migration.get('pending_review_count') or 0):
        errors.append('pending_identity_reviews')
    if not migration.get('cache_revision_matches_database'):
        errors.append('worker_catalog_revision_mismatch')
    revisions = [migration.get(field) for field in ('snapshot_revision', 'database_revision', 'cached_revision')]
    if any(value is None for value in revisions) or len(set(revisions)) != 1:
        errors.append('worker_catalog_revision_incomplete')
    runtime = migration.get('runtime_observation') or {}
    if int(runtime.get('catalog_reads_since_start') or 0) <= 0:
        errors.append('no_catalog_reads_observed')
    if int(runtime.get('legacy_fallback_reads_since_start') or 0):
        errors.append('legacy_fallback_observed')
    if int(runtime.get('catalog_load_failures_since_start') or 0):
        errors.append('catalog_load_failure_observed')
    return sorted(set(errors))


def build_report(
    payloads: list[Mapping[str, Any]],
    *,
    expected_worker_count: int,
    observation_seconds: float,
    minimum_observation_seconds: int,
    observed_at: str | None = None,
) -> dict[str, Any]:
    workers: dict[str, dict[str, Any]] = {}
    global_errors = []
    for payload in payloads:
        migration = payload.get('migration') or {}
        worker_id = str(migration.get('worker_id') or '')
        if not worker_id:
            global_errors.append('worker_id_missing')
            continue
        row = workers.setdefault(
            worker_id,
            {
                'sample_count': 0,
                'database_revisions': set(),
                'snapshot_revisions': set(),
                'cached_revisions': set(),
                'max_catalog_reads_since_start': 0,
                'max_legacy_fallback_reads_since_start': 0,
                'max_catalog_load_failures_since_start': 0,
                'errors': set(),
                'retirement_ready': True,
                'retirement_blockers': set(),
            },
        )
        row['sample_count'] += 1
        for field, target in (
            ('database_revision', 'database_revisions'),
            ('snapshot_revision', 'snapshot_revisions'),
            ('cached_revision', 'cached_revisions'),
        ):
            value = migration.get(field)
            if value is not None:
                row[target].add(value)
        runtime = migration.get('runtime_observation') or {}
        for field in (
            'catalog_reads_since_start',
            'legacy_fallback_reads_since_start',
            'catalog_load_failures_since_start',
        ):
            key = f'max_{field}'
            row[key] = max(row[key], int(runtime.get(field) or 0))
        row['errors'].update(_migration_errors(migration))
        retirement = migration.get('retirement') or {}
        raw_parity_ok = migration.get('automated_parity_ok') is True and not int(
            migration.get('mismatch_count') or 0
        )
        if not raw_parity_ok:
            row['retirement_blockers'].add('catalog_inline_mismatch')
        row['retirement_blockers'].update(str(value) for value in retirement.get('blockers') or [])
        if not retirement.get('automated_eligible') or not raw_parity_ok:
            row['retirement_ready'] = False

    if len(workers) < expected_worker_count:
        global_errors.append('expected_worker_set_not_observed')
    if observation_seconds < minimum_observation_seconds:
        global_errors.append('observation_window_too_short')
    database_revisions = set()
    serialized_workers = {}
    retirement_blockers = set()
    for worker_id, row in sorted(workers.items()):
        database_revisions.update(row['database_revisions'])
        retirement_blockers.update(row['retirement_blockers'])
        serialized_workers[worker_id] = {
            **row,
            'database_revisions': sorted(row['database_revisions']),
            'snapshot_revisions': sorted(row['snapshot_revisions']),
            'cached_revisions': sorted(row['cached_revisions']),
            'errors': sorted(row['errors']),
            'retirement_blockers': sorted(row['retirement_blockers']),
        }
    if len(database_revisions) != 1:
        global_errors.append('workers_observed_different_database_revisions')
    if any(row['errors'] for row in serialized_workers.values()):
        global_errors.append('worker_gate_failed')

    errors = sorted(set(global_errors))
    return {
        'schema_version': 1,
        'observed_at': observed_at or datetime.now(timezone.utc).isoformat(),
        'sample_count': len(payloads),
        'expected_worker_count': expected_worker_count,
        'observed_worker_count': len(workers),
        'observation_seconds': round(float(observation_seconds), 3),
        'minimum_observation_seconds': minimum_observation_seconds,
        'workers': serialized_workers,
        'errors': errors,
        'automated_gate_ok': not errors,
        'manual_signoff_required': True,
        'retirement_readiness': {
            'automated_eligible': bool(workers)
            and all(row['retirement_ready'] for row in serialized_workers.values()),
            'blockers': sorted(retirement_blockers),
            'raw_inline_parity_required': True,
        },
    }


def collect_report(
    *,
    environ: Mapping[str, str] | None = None,
    json_getter: Callable[[str], dict[str, Any]] | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    monotonic_fn: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    environ = os.environ if environ is None else environ
    expected_workers = _env_int(environ, 'WORK_CATALOG_EXPECTED_WORKERS', 1, minimum=1)
    samples = _env_int(environ, 'WORK_CATALOG_OBSERVATION_SAMPLES', 12, minimum=1)
    interval_seconds = _env_int(environ, 'WORK_CATALOG_OBSERVATION_INTERVAL_SECONDS', 5, minimum=0)
    minimum_seconds = _env_int(environ, 'WORK_CATALOG_MIN_OBSERVATION_SECONDS', 55, minimum=0)
    getter = json_getter or (lambda path: fetch_json(path, environ=environ, timeout=30))
    payloads = []
    started = monotonic_fn()
    for index in range(samples):
        payloads.append(getter('/api/admin/works_health'))
        if index + 1 < samples:
            sleep_fn(interval_seconds)
    elapsed = monotonic_fn() - started
    return build_report(
        payloads,
        expected_worker_count=expected_workers,
        observation_seconds=elapsed,
        minimum_observation_seconds=minimum_seconds,
    )


def main() -> int:
    report_path = Path(os.environ.get('WORK_CATALOG_ROLLOUT_REPORT_PATH') or REPORT_PATH)
    try:
        report = collect_report()
    except Exception as exc:
        report = {
            'schema_version': 1,
            'observed_at': datetime.now(timezone.utc).isoformat(),
            'automated_gate_ok': False,
            'manual_signoff_required': True,
            'errors': [f'collection_failed:{exc.__class__.__name__}'],
        }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get('automated_gate_ok') else 1


if __name__ == '__main__':
    sys.exit(main())
