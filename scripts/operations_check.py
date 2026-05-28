#!/usr/bin/env python3
"""Read-only production health and analytics checks for ntfy notifications."""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Callable, Mapping
from urllib.error import HTTPError
from urllib.request import Request, urlopen

try:
    from scripts.ntfy_notifier import notify
except ModuleNotFoundError:  # pragma: no cover - direct script execution fallback
    from ntfy_notifier import notify


DEFAULT_BASE_URL = 'https://hekineitor.onrender.com'
HEAVY_RESULTS = {'共依存', '激重感情', '共生関係', '執着'}
PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'


def _env_float(environ: Mapping[str, str], name: str, default: float) -> float:
    try:
        return float(environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_int(environ: Mapping[str, str], name: str, default: int) -> int:
    try:
        return int(environ.get(name, default))
    except (TypeError, ValueError):
        return default


def base_url(environ: Mapping[str, str] | None = None) -> str:
    environ = os.environ if environ is None else environ
    return str(environ.get('HEKI_BASE_URL') or DEFAULT_BASE_URL).rstrip('/')


def admin_headers(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    environ = os.environ if environ is None else environ
    token = str(environ.get('ADMIN_READ_TOKEN') or '').strip()
    return {'Authorization': f'Bearer {token}'} if token else {}


def fetch_json(path: str, *, environ: Mapping[str, str] | None = None, timeout: int = 15) -> dict[str, Any]:
    url = f'{base_url(environ)}{path}'
    headers = admin_headers(environ) if path.startswith('/api/admin/') else {}
    request = Request(url, headers=headers)
    with urlopen(request, timeout=timeout) as response:
        data = response.read()
    return json.loads(data.decode('utf-8'))


def fetch_bytes(path: str, *, environ: Mapping[str, str] | None = None, timeout: int = 15) -> bytes:
    url = f'{base_url(environ)}{path}'
    request = Request(url)
    with urlopen(request, timeout=timeout) as response:
        return response.read(512)


def _with_retries(callable_fn, *, attempts=2):
    last_error = None
    for _attempt in range(max(1, int(attempts or 1))):
        try:
            return callable_fn()
        except Exception as exc:
            last_error = exc
    if last_error:
        raise last_error
    raise RuntimeError('retry failed')


def _pct(value: float | int | None) -> str:
    if value is None:
        return 'n/a'
    return f'{float(value):.1f}%'


def _error_label(exc: Exception) -> str:
    if isinstance(exc, HTTPError):
        return f'HTTP {exc.code}'
    return exc.__class__.__name__


def _ratio(numerator: int | float, denominator: int | float) -> float:
    return round(float(numerator) / float(denominator) * 100, 1) if denominator else 0.0


def _bounded_percent(value: float | int | None) -> float | None:
    if value is None:
        return None
    return max(0.0, min(100.0, float(value)))


def _result_name(row: dict[str, Any]) -> str:
    return str(row.get('fetish_name') or row.get('name') or row.get('result_name') or 'unknown')


def _result_count(row: dict[str, Any]) -> int:
    return int(row.get('total') or row.get('count') or row.get('guessed') or 0)


def _top_heavy_ratio(ranking: list[dict[str, Any]]) -> tuple[float, list[str]]:
    total = sum(_result_count(row) for row in ranking)
    heavy_rows = [row for row in ranking if _result_name(row) in HEAVY_RESULTS]
    heavy_total = sum(_result_count(row) for row in heavy_rows)
    top = []
    for row in heavy_rows[:4]:
        top.append(f'{_result_name(row)} {_result_count(row)}')
    return _ratio(heavy_total, total), top


def _validate_health_response(health, critical, warn, environ):
    if health.get('status') != 'ok':
        critical.append(f"/health status={health.get('status', 'unknown')}")
    storage = health.get('storage')
    if storage != 'postgres':
        critical.append(f'storage={storage or "unknown"}')
    matrix = health.get('matrix') or {}
    if matrix.get('ok') is not True:
        critical.append('matrix shape mismatch')
    errors = ((health.get('runtime') or {}).get('error_counts') or {})
    five_xx = int(errors.get('5xx') or 0)
    critical_5xx = _env_int(environ, 'NTFY_5XX_CRITICAL_COUNT', 3)
    if five_xx >= critical_5xx:
        critical.append(f'5xx errors={five_xx}')
    elif five_xx > 0:
        warn.append(f'5xx errors={five_xx} (単発は様子見)')


def _works_count(works_health: dict[str, Any]) -> int | None:
    maintenance = works_health.get('maintenance') or {}
    if isinstance(maintenance.get('works_count'), int):
        return maintenance['works_count']
    seed = works_health.get('seed_backfill') or {}
    if isinstance(seed.get('works_count'), int):
        return seed['works_count']
    return None


def _completion_metric(funnel: dict[str, Any], *, min_starts: int = 20) -> dict[str, Any]:
    completion = funnel.get('completion') or {}
    for bucket_name in ('recent_7_days', 'recent_30_days'):
        bucket = completion.get(bucket_name) or {}
        starts = int(bucket.get('starts') or 0)
        completions = int(bucket.get('completions') or 0)
        value = bucket.get('completion_rate')
        if isinstance(value, (int, float)):
            if starts and completions > starts:
                return {'rate': None, 'starts': starts, 'completions': completions, 'reliable': False, 'source': bucket_name}
            rate = _bounded_percent(value)
            reliable = starts >= min_starts and not (rate >= 99.5 and completions >= starts and starts > 0)
            return {'rate': rate, 'starts': starts, 'completions': completions, 'reliable': reliable, 'source': bucket_name}
    history = funnel.get('stats_history') or []
    active_rows = [row for row in history if int(row.get('start') or row.get('play') or row.get('completion') or 0) > 0]
    if active_rows:
        row = active_rows[-1]
        starts = int(row.get('start') or row.get('play') or 0)
        completions = int(row.get('completion') or 0)
        if starts:
            if completions > starts:
                return {'rate': None, 'starts': starts, 'completions': completions, 'reliable': False, 'source': 'stats_history'}
            rate = _bounded_percent(_ratio(completions, starts))
            reliable = starts >= min_starts and not (rate >= 99.5 and completions >= starts and starts > 0)
            return {'rate': rate, 'starts': starts, 'completions': completions, 'reliable': reliable, 'source': 'stats_history'}
    for key in ('completion_rate', 'recent_completion_rate', 'complete_rate'):
        value = completion.get(key)
        if isinstance(value, (int, float)):
            return {'rate': _bounded_percent(value), 'starts': 0, 'completions': 0, 'reliable': False, 'source': key}
    return {'rate': None, 'starts': 0, 'completions': 0, 'reliable': False, 'source': 'unavailable'}


def _latest_completion_rate(funnel: dict[str, Any]) -> float | None:
    return _completion_metric(funnel).get('rate')


def _completion_label(metric: dict[str, Any]) -> str:
    rate = metric.get('rate')
    if rate is None:
        return 'completion_rate=unavailable'
    suffix = '' if metric.get('reliable') else ' (参考値)'
    starts = int(metric.get('starts') or 0)
    completions = int(metric.get('completions') or 0)
    sample = f' ({completions}/{starts})' if starts else ''
    return f'completion_rate={_pct(rate)}{suffix}{sample}'


def _demote_public_timeout_criticals(critical, warn, *, admin_signal_available=False, daily=None):
    daily = daily or []
    if not (admin_signal_available or daily):
        return critical
    remaining = []
    for item in critical:
        text = str(item)
        if text.startswith('/health failed:') or text.startswith('OGP PNG failure:'):
            warn.append(text + ' (admin metrics reachable; downgraded from CRITICAL)')
        else:
            remaining.append(item)
    return remaining


def build_report(
    *,
    environ: Mapping[str, str] | None = None,
    json_getter: Callable[[str], dict[str, Any]] | None = None,
    bytes_getter: Callable[[str], bytes] | None = None,
) -> dict[str, Any]:
    environ = os.environ if environ is None else environ
    public_timeout = _env_int(environ, 'NTFY_PUBLIC_TIMEOUT_SECONDS', 25)
    admin_timeout = _env_int(environ, 'NTFY_ADMIN_TIMEOUT_SECONDS', 15)
    json_getter = json_getter or (
        lambda path: fetch_json(
            path,
            environ=environ,
            timeout=admin_timeout if path.startswith('/api/admin/') else public_timeout,
        )
    )
    bytes_getter = bytes_getter or (lambda path: fetch_bytes(path, environ=environ, timeout=public_timeout))
    critical: list[str] = []
    warn: list[str] = []
    daily: list[str] = []

    health_failed = None
    png_failed = None
    admin_signal_available = False

    try:
        health = _with_retries(lambda: json_getter('/health'), attempts=_env_int(environ, 'NTFY_HEALTH_RETRIES', 2))
        _validate_health_response(health, critical, warn, environ)
    except Exception as exc:
        health_failed = exc
        health = {}

    try:
        png = _with_retries(
            lambda: bytes_getter('/ogp.png?f=health&p=88'),
            attempts=_env_int(environ, 'NTFY_OGP_RETRIES', 2),
        )
        if not png.startswith(PNG_SIGNATURE):
            critical.append('OGP PNG signature failure')
    except Exception as exc:
        png_failed = exc

    if admin_headers(environ):
        try:
            preflight = json_getter('/api/admin/preflight')
            admin_signal_available = True
            failed = [row.get('name') for row in preflight.get('checks', []) if row.get('ok') is False]
            if failed:
                critical.append('preflight failed: ' + ', '.join(str(name) for name in failed[:5]))
        except Exception as exc:
            warn.append(f'preflight unavailable: {_error_label(exc)}')

        try:
            works_health = json_getter('/api/admin/works_health')
            works_count = _works_count(works_health)
            min_works = _env_int(environ, 'NTFY_WORKS_MIN_COUNT', 0)
            if min_works and works_count is not None and works_count < min_works:
                critical.append(f'works_count={works_count} below {min_works}')
        except Exception as exc:
            warn.append(f'works_health unavailable: {_error_label(exc)}')

        try:
            ranking = json_getter('/api/admin/recent_fetish_ranking?days=7&top_n=20').get('ranking', [])
            admin_signal_available = True
            heavy_ratio, heavy_top = _top_heavy_ratio(ranking)
            daily.append(f'heavy_result_ratio={_pct(heavy_ratio)}')
            if heavy_ratio >= _env_float(environ, 'NTFY_HEAVY_RESULT_WARN_RATIO', 65.0):
                warn.append(f'heavy_result_ratio={_pct(heavy_ratio)} TOP: {", ".join(heavy_top[:4])}')
        except Exception as exc:
            warn.append(f'result ranking unavailable: {_error_label(exc)}')

        try:
            question_report = json_getter('/api/admin/question_events?limit=5000')
            admin_signal_available = True
            q_metrics = question_report.get('metrics') or {}
            relation_share = float(q_metrics.get('relation_attachment_share') or 0)
            question_total = int(question_report.get('total') or 0)
            daily.append(f'question_events={question_total}')
            if question_total == 0:
                warn.append('question_events=0; 質問分析ログが未蓄積です')
            if relation_share >= _env_float(environ, 'NTFY_RELATION_ATTACHMENT_WARN_RATIO', 55.0):
                warn.append(f'relation/attachment share={_pct(relation_share)}')
            min_answers = _env_int(environ, 'NTFY_QUESTION_MIN_ANSWERS', 5)
            yes_threshold = _env_float(environ, 'NTFY_QUESTION_YES_WARN_RATE', 90.0)
            yes_questions = [
                row for row in question_report.get('questions', [])
                if int(row.get('answered') or 0) >= min_answers and float(row.get('yes_rate') or 0) >= yes_threshold
            ]
            if yes_questions:
                sample = ', '.join(f"Q{row.get('question_id')} {_pct(row.get('yes_rate'))}" for row in yes_questions[:3])
                warn.append(f'YES率{yes_threshold:.0f}%以上質問: {sample}')
            drop_threshold = _env_float(environ, 'NTFY_DROPOFF_WARN_RATE', 35.0)
            drop_questions = [
                row for row in question_report.get('dropoff_ranking', [])
                if int(row.get('shown') or 0) >= min_answers and float(row.get('dropoff_rate') or 0) >= drop_threshold
            ]
            if drop_questions:
                sample = ', '.join(f"Q{row.get('question_id')} {_pct(row.get('dropoff_rate'))}" for row in drop_questions[:3])
                warn.append(f'離脱率{drop_threshold:.0f}%以上質問: {sample}')
        except Exception as exc:
            warn.append(f'question analytics unavailable: {_error_label(exc)}')

        try:
            funnel = json_getter('/api/admin/funnel_metrics')
            admin_signal_available = True
            completion_metric = _completion_metric(
                funnel,
                min_starts=_env_int(environ, 'NTFY_COMPLETION_MIN_STARTS', 20),
            )
            completion_rate = completion_metric.get('rate')
            daily.append(_completion_label(completion_metric))
            if completion_rate is None:
                warn.append('completion_rate unavailable; start/completion母数が不足しています')
            elif not completion_metric.get('reliable'):
                warn.append(_completion_label(completion_metric))
            min_feedback = _env_float(environ, 'NTFY_FEEDBACK_WARN_RATE', 5.0)
            if completion_metric.get('reliable') and completion_rate is not None and completion_rate < min_feedback:
                warn.append(f'feedback/completion rate low={_pct(completion_rate)}')
        except Exception as exc:
            warn.append(f'funnel unavailable: {_error_label(exc)}')

        try:
            share_error = None
            share_report = None
            for path in ('/api/admin/share_events?days=7&limit=5000', '/api/admin/share_events?limit=5000'):
                try:
                    share_report = json_getter(path)
                    admin_signal_available = True
                    break
                except Exception as exc:
                    share_error = exc
            if share_report is None:
                raise share_error or RuntimeError('share_events unavailable')
            share_metrics = share_report.get('metrics') or {}
            result_views = int(share_metrics.get('result_page_views') or 0)
            share_actions = int(share_metrics.get('share_actions') or 0)
            share_rate = _ratio(share_actions, result_views)
            share_total = int(share_report.get('total') or 0)
            daily.append(f'share_events={share_total}')
            daily.append(f'share_rate={_pct(share_rate)}')
            if share_total == 0:
                warn.append('share_events=0; シェア分析ログが未蓄積です')
            if result_views >= _env_int(environ, 'NTFY_SHARE_MIN_RESULT_VIEWS', 20) and share_rate < _env_float(environ, 'NTFY_SHARE_WARN_RATE', 3.0):
                warn.append(f'share rate low={_pct(share_rate)} ({share_actions}/{result_views})')
        except Exception as exc:
            warn.append(f'share analytics unavailable: {_error_label(exc)}')
    else:
        warn.append('ADMIN_READ_TOKEN is not set; admin analytics checks skipped')

    if admin_signal_available and health_failed:
        try:
            health = _with_retries(lambda: json_getter('/health'), attempts=1)
            _validate_health_response(health, critical, warn, environ)
            health_failed = None
        except Exception as exc:
            health_failed = exc
    if admin_signal_available and png_failed:
        try:
            png = _with_retries(lambda: bytes_getter('/ogp.png?f=health&p=88'), attempts=1)
            if png.startswith(PNG_SIGNATURE):
                png_failed = None
            else:
                critical.append('OGP PNG signature failure')
                png_failed = None
        except Exception as exc:
            png_failed = exc

    if health_failed:
        message = f'/health failed: {health_failed.__class__.__name__}'
        if admin_signal_available:
            warn.append(message + ' (admin analytics reachable; treated as transient)')
        else:
            critical.append(message)
    if png_failed:
        message = f'OGP PNG failure: {png_failed.__class__.__name__}'
        if admin_signal_available:
            warn.append(message + ' (admin analytics reachable; treated as transient)')
        else:
            critical.append(message)

    critical = _demote_public_timeout_criticals(
        critical,
        warn,
        admin_signal_available=admin_signal_available,
        daily=daily,
    )
    severity = 'CRITICAL' if critical else 'WARN' if warn else 'OK'
    lines = [f'[{severity}] Hekineitor operations check']
    if critical:
        lines.append('CRITICAL:')
        lines.extend(f'- {item}' for item in critical[:8])
    if warn:
        lines.append('WARN:')
        lines.extend(f'- {item}' for item in warn[:10])
    if daily:
        lines.append('metrics:')
        lines.extend(f'- {item}' for item in daily[:10])
    return {'severity': severity, 'critical': critical, 'warn': warn, 'message': '\n'.join(lines)}


def main(argv: list[str] | None = None) -> int:
    report = build_report()
    print(report['message'])
    if report['severity'] in ('CRITICAL', 'WARN') or os.environ.get('NTFY_NOTIFY_OK') == '1':
        priority = 'urgent' if report['severity'] == 'CRITICAL' else 'high' if report['severity'] == 'WARN' else 'default'
        tags = 'rotating_light' if report['severity'] == 'CRITICAL' else 'warning' if report['severity'] == 'WARN' else 'white_check_mark'
        try:
            result = notify(f'Hekineitor {report["severity"]}', report['message'], priority=priority, tags=tags)
            if result.get('skipped'):
                print('ntfy skipped: ' + str(result.get('reason', 'notification disabled')))
        except Exception as exc:
            print(f'ntfy failed: {exc.__class__.__name__}', file=sys.stderr)
            return 1 if report['severity'] == 'CRITICAL' else 0
    return 1 if report['severity'] == 'CRITICAL' else 0


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
