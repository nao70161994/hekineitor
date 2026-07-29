#!/usr/bin/env python3
"""Apply checked-in work catalog manifests through the protected admin API."""

from __future__ import annotations

import argparse
import base64
import hashlib
import http.cookiejar
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from engine import work_catalog

REVIEW_SHA256 = '6da3aab04feda24b114e746afab44b37f08781443fa242e0971fd6b64780767b'
LEGACY_REVIEW_SHA256 = 'e9898e8165f6772f58be05583d838b10b74a1749e666251613d7671584f1cf05'
LEGACY_SOURCE_DIGEST = '7bbadf34074f154d1e69cf40382834c641aaf30b5edb6432d05b7aa86b87bd17'
LEGACY_AFTER_REVIEW_DIGEST = '0b76ff8b17f74eba3609054305429dc5409289d31180498bc36cb207053cc79f'
LEGACY_FINAL_DIGEST = 'b09f615311de932ed41af208c02058fa711da983c2ba18d0438cf80f6dc3b4ce'
LEGACY_COMPATIBLE_DIGESTS = {LEGACY_SOURCE_DIGEST, LEGACY_AFTER_REVIEW_DIGEST, LEGACY_FINAL_DIGEST}
SEED_SHA256 = 'e960ed79e1f77c0af61275d536f311b3d8c3b93b563bf522e55b0ed4dbde32c3'
CSRF_RE = re.compile(r'csrfToken\s*[:=]\s*["\']([^"\']+)')


def _canonical_sha(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    return hashlib.sha256(raw).hexdigest()


def _load_manifest(path: Path, expected_sha256: str) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(payload, dict):
        raise RuntimeError(f'{path} must contain a JSON object')
    actual = _canonical_sha(payload)
    if actual != expected_sha256:
        raise RuntimeError(f'{path} canonical SHA-256 mismatch: {actual}')
    return payload


class AdminClient:
    def __init__(self, base_url: str, username: str, password: str):
        self.base_url = base_url.rstrip('/')
        auth = base64.b64encode(f'{username}:{password}'.encode()).decode()
        self._opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self._headers = {'Authorization': f'Basic {auth}', 'Accept': 'application/json'}

    def request(self, path: str, *, method: str = 'GET', payload=None, csrf: str = ''):
        headers = dict(self._headers)
        data = None
        if payload is not None:
            headers['Content-Type'] = 'application/json'
            data = json.dumps(payload, ensure_ascii=False).encode()
        if csrf:
            headers['X-CSRF-Token'] = csrf
        request = urllib.request.Request(f'{self.base_url}{path}', method=method, headers=headers, data=data)
        try:
            with self._opener.open(request, timeout=60) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as exc:
            body = exc.read()
            raise RuntimeError(f'{method} {path} failed with HTTP {exc.code}: {body[:500]!r}') from exc

    def json(self, path: str, *, method: str = 'GET', payload=None, csrf: str = ''):
        status, body = self.request(path, method=method, payload=payload, csrf=csrf)
        if status != 200:
            raise RuntimeError(f'{method} {path} returned HTTP {status}')
        parsed = json.loads(body)
        if not isinstance(parsed, dict):
            raise RuntimeError(f'{method} {path} did not return a JSON object')
        return parsed

    def csrf_token(self) -> str:
        status, body = self.request('/admin')
        if status != 200:
            raise RuntimeError(f'GET /admin returned HTTP {status}')
        match = CSRF_RE.search(body.decode('utf-8'))
        if not match:
            raise RuntimeError('CSRF token not found in /admin response')
        return match.group(1)


def _validate_target(base_url: str, expected_host: str) -> None:
    parsed = urllib.parse.urlparse(base_url)
    if parsed.scheme != 'https' or parsed.hostname != expected_host or parsed.path not in ('', '/'):
        raise RuntimeError('target URL must be the HTTPS root of the exact expected production host')
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.port not in (None, 443):
        raise RuntimeError('target URL contains forbidden URL components')


def _snapshot(client: AdminClient):
    response = client.json('/api/admin/work_catalog')
    digest = str(response.get('digest') or '')
    catalog = response.get('catalog')
    if response.get('status') != 'ok' or len(digest) != 64 or not isinstance(catalog, dict):
        raise RuntimeError('catalog snapshot did not include a valid catalog and digest')
    if work_catalog.catalog_digest(catalog) != digest:
        raise RuntimeError('server catalog content does not match its digest')
    return catalog, digest


def _mutate(client, csrf, *, operation, digest, payload):
    response = client.json(
        '/api/admin/work_catalog/mutate',
        method='POST',
        csrf=csrf,
        payload={
            'operation': operation,
            'expected_digest': digest,
            'confirm_text': 'WORK_CATALOG',
            'payload': payload,
        },
    )
    if response.get('status') != 'ok' or len(str(response.get('digest') or '')) != 64:
        raise RuntimeError(f'{operation} returned an invalid success payload')
    return response


def apply_manifests(
    *,
    base_url,
    expected_host,
    username,
    password,
    review_path,
    legacy_review_path,
    seed_path,
    backup_path,
):
    _validate_target(base_url, expected_host)
    primary_review = _load_manifest(review_path, REVIEW_SHA256)
    legacy_review = _load_manifest(legacy_review_path, LEGACY_REVIEW_SHA256)
    seed = _load_manifest(seed_path, SEED_SHA256)
    if len(primary_review.get('decisions', [])) != 74 or len(legacy_review.get('decisions', [])) != 79:
        raise RuntimeError('review manifest counts do not match the approved change sets')
    if len(seed.get('title_normalizations', [])) != 46 or len(seed.get('remove_display_titles', [])) != 4:
        raise RuntimeError('seed manifest counts do not match the approved change set')

    client = AdminClient(base_url, username, password)
    backup = json.loads(backup_path.read_text(encoding='utf-8'))
    backup_catalog = backup.get('work_catalog') if isinstance(backup, dict) else None
    if not isinstance(backup_catalog, dict):
        raise RuntimeError('validated v3 backup does not contain work_catalog')
    before, before_digest = _snapshot(client)
    if before_digest in LEGACY_COMPATIBLE_DIGESTS:
        review = legacy_review
        review_sha256 = LEGACY_REVIEW_SHA256
    else:
        review = primary_review
        review_sha256 = REVIEW_SHA256
    if work_catalog.catalog_digest(backup_catalog) != before_digest:
        raise RuntimeError('fresh backup catalog digest does not match production before mutation')
    expected_after_review = work_catalog.apply_review_decisions(before, review)
    expected_review_digest = work_catalog.catalog_digest(expected_after_review)
    expected_final = work_catalog.apply_seed_overrides(expected_after_review, seed)
    expected_final_digest = work_catalog.catalog_digest(expected_final)

    review_response = _mutate(
        client,
        client.csrf_token(),
        operation='review_apply_manifest',
        digest=before_digest,
        payload={'decision_manifest': review},
    )
    review_counts = review_response.get('result') or {}
    if (
        review_response['digest'] != expected_review_digest
        or review_counts.get('resolved_count') != len(review['decisions'])
        or review_counts.get('pending_count') != 0
    ):
        raise RuntimeError(f'unexpected review manifest result: {review_counts!r}')

    between, between_digest = _snapshot(client)
    if between_digest != expected_review_digest or between != expected_after_review:
        raise RuntimeError('catalog drift detected between manifest operations')
    seed_response = _mutate(
        client,
        client.csrf_token(),
        operation='seed_overrides_apply_manifest',
        digest=between_digest,
        payload={'seed_overrides': seed},
    )
    seed_counts = seed_response.get('result') or {}
    expected_removed = len(expected_after_review['works_master']) - len(expected_final['works_master'])
    if (
        seed_response['digest'] != expected_final_digest
        or seed_counts.get('normalized_title_count') != 46
        or seed_counts.get('removed_work_count') != expected_removed
    ):
        raise RuntimeError(f'unexpected seed override result: {seed_counts!r}')

    after, after_digest = _snapshot(client)
    if after_digest != expected_final_digest or after != expected_final:
        raise RuntimeError('post-mutation catalog does not match the preflight result')
    health = client.json('/api/admin/works_health')
    migration = health.get('migration') or {}
    observation = migration.get('runtime_observation') or {}
    revisions = {
        migration.get('snapshot_revision'),
        migration.get('database_revision'),
        migration.get('cached_revision'),
    }
    if (
        health.get('status') != 'ok'
        or migration.get('automated_parity_ok') is not True
        or migration.get('mismatch_count') != 0
        or migration.get('pending_review_count') != 0
        or migration.get('cache_revision_matches_database') is not True
        or len(revisions) != 1
        or observation.get('legacy_fallback_reads_since_start') != 0
        or observation.get('catalog_load_failures_since_start') != 0
    ):
        raise RuntimeError('post-mutation works health did not pass catalog gates')
    audit = client.json('/api/admin/audit_log?limit=20')
    rows = audit.get('audit_log') if isinstance(audit, dict) else None
    expected_audits = {
        ('review_apply_manifest', review_sha256),
        ('seed_overrides_apply_manifest', SEED_SHA256),
    }
    observed_audits = {
        (row.get('detail', {}).get('operation'), row.get('detail', {}).get('manifest_sha256'))
        for row in (rows or [])
        if row.get('action') == 'work_catalog_mutation' and row.get('status') == 'ok'
    }
    if not expected_audits.issubset(observed_audits):
        raise RuntimeError('work catalog mutation audit fingerprints were not observed')

    return {
        'schema_version': 1,
        'applied_at': datetime.now(timezone.utc).isoformat(),
        'target_host': expected_host,
        'review_manifest_sha256': review_sha256,
        'seed_overrides_sha256': SEED_SHA256,
        'before_digest': before_digest,
        'review_digest': expected_review_digest,
        'final_digest': expected_final_digest,
        'review_result': review_counts,
        'seed_result': seed_counts,
        'migration': {
            key: migration.get(key)
            for key in (
                'automated_parity_ok',
                'mismatch_count',
                'pending_review_count',
                'snapshot_revision',
                'database_revision',
                'cached_revision',
                'worker_id',
            )
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--expected-host', required=True)
    parser.add_argument('--backup', type=Path, required=True)
    parser.add_argument('--username', required=True)
    parser.add_argument('--password', required=True)
    parser.add_argument('--legacy-review-manifest', type=Path, required=True)
    parser.add_argument('--review-manifest', type=Path, required=True)
    parser.add_argument('--seed-overrides', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    evidence = apply_manifests(
        base_url=args.base_url,
        expected_host=args.expected_host,
        username=args.username,
        legacy_review_path=args.legacy_review_manifest,
        password=args.password,
        review_path=args.review_manifest,
        seed_path=args.seed_overrides,
        backup_path=args.backup,
    )
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    args.evidence.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(evidence, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
