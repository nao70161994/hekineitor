#!/usr/bin/env python3
"""Restore a v3 matrix backup to staging and emit non-secret evidence."""

from __future__ import annotations

import argparse
import base64
import http.cookiejar
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from engine.work_catalog import catalog_digest
from scripts.validate_matrix_backup import validate

CONFIRM_TEXT = 'RESTORE V3 TO STAGING'
CSRF_RE = re.compile(r'csrfToken\s*[:=]\s*["\']([^"\']+)')


def guarded_staging_url(base_url: str, expected_host: str, production_url: str, confirm: str) -> str:
    """Validate the destructive target before any network request."""
    if confirm != CONFIRM_TEXT:
        raise ValueError(f'confirmation must be exactly {CONFIRM_TEXT!r}')
    expected_host = str(expected_host or '').strip().lower().rstrip('.')
    if not expected_host or any(char in expected_host for char in '/:@'):
        raise ValueError('expected staging host must be a bare hostname')
    parsed = urllib.parse.urlsplit(str(base_url or '').strip())
    production = urllib.parse.urlsplit(str(production_url or '').strip())
    if parsed.scheme != 'https':
        raise ValueError('staging URL must use HTTPS')
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('staging URL must not contain credentials, query, or fragment')
    if parsed.path not in ('', '/'):
        raise ValueError('staging URL must not contain a path')
    host = (parsed.hostname or '').lower().rstrip('.')
    if host != expected_host:
        raise ValueError('staging URL host does not match expected staging host')
    if production.scheme != 'https' or not production.hostname:
        raise ValueError('production URL must be an absolute HTTPS URL')
    normalized = f'https://{parsed.netloc}'.rstrip('/')
    normalized_production = f'https://{production.netloc}'.rstrip('/')
    if normalized == normalized_production or host == (production.hostname or '').lower().rstrip('.'):
        raise ValueError('staging target must differ from production')
    return normalized


def _int(value: Any, label: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f'{label} must be an integer >= {minimum}')
    return value


def validate_dry_run(result: Mapping[str, Any]) -> dict[str, int]:
    if result.get('status') != 'ok' or result.get('complete') is not True:
        raise ValueError('staging dry-run did not report a complete import')
    expected = _int(result.get('expected_rows'), 'dry-run expected_rows', 1)
    valid = _int(result.get('valid_rows'), 'dry-run valid_rows', 1)
    skipped = _int(result.get('skipped_rows'), 'dry-run skipped_rows')
    ignored = _int(result.get('ignored_source_rows'), 'dry-run ignored_source_rows')
    if valid != expected or skipped or ignored:
        raise ValueError('staging dry-run row counts are not lossless')
    return {'expected_rows': expected, 'valid_rows': valid, 'skipped_rows': skipped, 'ignored_source_rows': ignored}


def validate_import_result(result: Mapping[str, Any], expected_rows: int) -> dict[str, int]:
    if result.get('status') != 'ok':
        raise ValueError('staging import did not report status=ok')
    imported = _int(result.get('imported_rows'), 'imported_rows', 1)
    response_expected = _int(result.get('expected_rows'), 'import expected_rows', 1)
    skipped = _int(result.get('skipped_rows'), 'import skipped_rows')
    ignored = _int(result.get('ignored_source_rows'), 'import ignored_source_rows')
    restored = _int(result.get('restored_source_rows'), 'restored_source_rows', 1)
    if imported != expected_rows or response_expected != expected_rows or skipped or ignored:
        raise ValueError('staging import row counts are not lossless')
    return {
        'expected_rows': response_expected,
        'imported_rows': imported,
        'skipped_rows': skipped,
        'ignored_source_rows': ignored,
        'restored_source_rows': restored,
    }


def validate_works_health(payload: Mapping[str, Any]) -> dict[str, Any]:
    if payload.get('status') != 'ok':
        raise ValueError('works_health did not report status=ok')
    migration = payload.get('migration')
    if not isinstance(migration, Mapping) or migration.get('status') != 'ok':
        raise ValueError('works_health migration report is unavailable')
    revisions = {key: migration.get(key) for key in ('snapshot_revision', 'database_revision', 'cached_revision')}
    if any(value is None for value in revisions.values()) or len(set(revisions.values())) != 1:
        raise ValueError('work catalog revisions do not match')
    runtime = migration.get('runtime_observation') or {}
    errors = []
    if migration.get('automated_parity_ok') is not True or _int(migration.get('mismatch_count'), 'mismatch_count'):
        errors.append('catalog parity mismatch')
    if _int(migration.get('pending_review_count'), 'pending_review_count'):
        errors.append('pending identity reviews')
    if migration.get('cache_revision_matches_database') is not True:
        errors.append('cache/database revision mismatch')
    if _int(runtime.get('legacy_fallback_reads_since_start'), 'legacy fallback reads'):
        errors.append('legacy fallback observed')
    if _int(runtime.get('catalog_load_failures_since_start'), 'catalog load failures'):
        errors.append('catalog load failure observed')
    if errors:
        raise ValueError('; '.join(errors))
    return {
        **revisions,
        'worker_id': str(migration.get('worker_id') or ''),
        'automated_parity_ok': True,
        'mismatch_count': 0,
        'pending_review_count': 0,
        'legacy_fallback_reads_since_start': 0,
        'catalog_load_failures_since_start': 0,
    }


class RehearsalClient:
    def __init__(self, base_url: str, user: str, password: str, timeout: int = 30):
        if not user or not password:
            raise ValueError('staging admin credentials are required')
        self.base_url = base_url
        self.timeout = timeout
        self._basic = base64.b64encode(f'{user}:{password}'.encode()).decode('ascii')
        self._opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def request(
        self,
        path: str,
        *,
        method: str = 'GET',
        payload: Mapping[str, Any] | None = None,
        admin: bool = False,
        csrf: str = '',
    ) -> tuple[int, bytes, Mapping[str, str]]:
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode('utf-8')
        headers = {'Accept': 'application/json, text/html;q=0.9', 'User-Agent': 'Hekineitor-Staging-Rehearsal/1'}
        if data is not None:
            headers['Content-Type'] = 'application/json'
        if admin:
            headers['Authorization'] = f'Basic {self._basic}'
        if csrf:
            headers['X-CSRF-Token'] = csrf
        request = urllib.request.Request(self.base_url + path, data=data, headers=headers, method=method)
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                return response.status, response.read(), dict(response.headers.items())
        except urllib.error.HTTPError as exc:
            exc.read()
            raise RuntimeError(f'{method} {path} failed with HTTP {exc.code}') from None

    def json(
        self,
        path: str,
        *,
        method: str = 'GET',
        payload: Mapping[str, Any] | None = None,
        admin: bool = False,
        csrf: str = '',
    ) -> dict[str, Any]:
        status, body, _headers = self.request(path, method=method, payload=payload, admin=admin, csrf=csrf)
        if status != 200:
            raise RuntimeError(f'{method} {path} returned HTTP {status}')
        try:
            result = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise RuntimeError(f'{method} {path} did not return JSON') from None
        if not isinstance(result, dict):
            raise RuntimeError(f'{method} {path} did not return a JSON object')
        return result

    def csrf_token(self) -> str:
        status, body, _headers = self.request('/admin', admin=True)
        if status != 200:
            raise RuntimeError(f'GET /admin returned HTTP {status}')
        match = CSRF_RE.search(body.decode('utf-8', errors='replace'))
        if not match:
            raise RuntimeError('CSRF token not found in staging /admin response')
        return match.group(1)


def _catalog_counts(catalog: Mapping[str, Any]) -> dict[str, int]:
    keys = ('works_master', 'work_editions', 'work_aliases', 'fetish_work_links', 'compound_work_links', 'review_queue')
    return {key: len(catalog.get(key) or []) for key in keys}


def _public_fetish_id(catalog: Mapping[str, Any]) -> int:
    active_editions = set()
    for row in catalog.get('work_editions') or []:
        if not isinstance(row, Mapping) or row.get('status') != 'active':
            continue
        parsed = urllib.parse.urlsplit(str(row.get('canonical_url') or ''))
        hostname = (parsed.hostname or '').lower().rstrip('.')
        if parsed.scheme == 'https' and (hostname == 'amazon.co.jp' or hostname.endswith('.amazon.co.jp')):
            active_editions.add(row.get('edition_id'))
    candidates = [
        row.get('fetish_id')
        for row in catalog.get('fetish_work_links') or []
        if isinstance(row, Mapping)
        and isinstance(row.get('fetish_id'), int)
        and row['fetish_id'] < 10000
        and row.get('edition_id') in active_editions
    ]
    if not candidates:
        raise ValueError('backup catalog has no public fetish linked to an active Amazon HTTPS edition')
    return min(candidates)


def public_smoke(client: RehearsalClient, catalog: Mapping[str, Any]) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    health = client.json('/health')
    healthy = (
        health.get('status') == 'ok'
        and health.get('storage') == 'postgres'
        and health.get('db') is True
        and isinstance(health.get('matrix'), Mapping)
        and health['matrix'].get('ok') is True
    )
    if not healthy:
        raise ValueError('public health is not healthy PostgreSQL with a valid matrix')
    checks['health'] = {'status': 'ok', 'storage': 'postgres', 'db': True, 'matrix_shape_ok': True}

    status, body, _ = client.request('/')
    root = body.decode('utf-8', errors='replace')
    if status != 200 or '<meta property="og:title"' not in root or '<link rel="canonical"' not in root:
        raise ValueError('root SEO smoke failed')
    checks['root'] = {'status': status, 'seo': True}

    status, body, _ = client.request('/fetishes')
    if status != 200 or '<meta property="og:title"' not in body.decode('utf-8', errors='replace'):
        raise ValueError('fetish index smoke failed')
    checks['fetish_index'] = {'status': status, 'seo': True}

    fetish_id = _public_fetish_id(catalog)
    status, body, _ = client.request(f'/fetish/{fetish_id}')
    detail = body.decode('utf-8', errors='replace')
    if status != 200 or '<link rel="canonical"' not in detail or 'application/ld+json' not in detail:
        raise ValueError('fetish detail SEO smoke failed')
    amazon_links = re.findall(r'href="(https://www\.amazon\.co\.jp/[^"]+)"', detail)
    if not amazon_links or not any('tag=' in url.replace('&amp;', '&') for url in amazon_links):
        raise ValueError('fetish detail affiliate smoke failed')
    checks['fetish_detail'] = {'status': status, 'fetish_id': fetish_id, 'seo': True, 'affiliate': True}

    diagnosis = client.json('/api/start', method='POST', payload={})
    if not isinstance(diagnosis.get('question_id'), int) or not str(diagnosis.get('question') or '').strip():
        raise ValueError('diagnosis start smoke failed')
    checks['diagnosis_start'] = {'status': 'ok', 'question_contract': True}

    compound_count = len(catalog.get('compound_work_links') or [])
    if compound_count <= 0:
        raise ValueError('restored catalog has no compound recommendations')
    checks['compound_catalog'] = {
        'status': 'ok',
        'link_count': compound_count,
        'automated_scope': 'normalized catalog restore and digest only',
        'manual_compound_result_signoff_required': True,
    }
    return checks


def run_rehearsal(*, backup: Mapping[str, Any], client: RehearsalClient, backup_run_id: int) -> dict[str, Any]:
    validation = validate(backup, max_age_days=30)
    if validation.get('version') != 3 or not isinstance(backup.get('work_catalog'), Mapping):
        raise ValueError('rehearsal requires a v3 backup with work_catalog')
    source_catalog = backup['work_catalog']
    source_digest = catalog_digest(source_catalog)
    csrf = client.csrf_token()
    dry = client.json('/api/admin/import_matrix/dry_run', method='POST', payload=backup, admin=True, csrf=csrf)
    dry_counts = validate_dry_run(dry)
    import_payload = dict(backup)
    import_payload['confirm_text'] = 'IMPORT'
    imported = client.json('/api/admin/import_matrix', method='POST', payload=import_payload, admin=True, csrf=csrf)
    import_counts = validate_import_result(imported, dry_counts['expected_rows'])
    exported = client.json('/api/admin/export_matrix', admin=True)
    exported_validation = validate(exported)
    if exported_validation.get('version') != 3:
        raise ValueError('staging re-export is not backup format v3')
    restored_digest = catalog_digest(exported.get('work_catalog'))
    if restored_digest != source_digest:
        raise ValueError('work catalog digest changed across staging restore')
    health = validate_works_health(client.json('/api/admin/works_health', admin=True))
    smoke = public_smoke(client, exported['work_catalog'])
    return {
        'schema_version': 1,
        'status': 'passed',
        'completed_at': datetime.now(timezone.utc).isoformat(),
        'backup_run_id': backup_run_id,
        'backup_validation': validation,
        'dry_run': dry_counts,
        'import': import_counts,
        'work_catalog': {'digest_match': True, 'digest': source_digest, 'counts': _catalog_counts(source_catalog)},
        'works_health': health,
        'public_smoke': smoke,
        'production_targeted': False,
        'manual_signoff_required': True,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('backup_path')
    parser.add_argument('--report', default='artifacts/staging_v3_restore_rehearsal.json')
    args = parser.parse_args()
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        base_url = guarded_staging_url(
            os.environ.get('STAGING_BASE_URL', ''),
            os.environ.get('EXPECTED_STAGING_HOST', ''),
            os.environ.get('PRODUCTION_BASE_URL', ''),
            os.environ.get('STAGING_RESTORE_CONFIRM', ''),
        )
        run_id = int(os.environ.get('BACKUP_RUN_ID', ''))
        if run_id <= 0:
            raise ValueError('BACKUP_RUN_ID must be a positive integer')
        with open(args.backup_path, encoding='utf-8') as source:
            backup = json.load(source)
        client = RehearsalClient(
            base_url, os.environ.get('STAGING_ADMIN_USER', ''), os.environ.get('STAGING_ADMIN_PASS', '')
        )
        report = run_rehearsal(backup=backup, client=client, backup_run_id=run_id)
        exit_code = 0
    except Exception as exc:
        report = {
            'schema_version': 1,
            'status': 'failed',
            'completed_at': datetime.now(timezone.utc).isoformat(),
            'error_type': exc.__class__.__name__,
            'error': str(exc),
            'production_targeted': False,
            'manual_signoff_required': True,
        }
        exit_code = 1
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return exit_code


if __name__ == '__main__':
    sys.exit(main())
