#!/usr/bin/env python3
"""Build a privacy-safe daily operations report and send it through ntfy."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Any, Callable, Mapping
from urllib.request import Request, urlopen

try:
    from scripts.ntfy_notifier import notify
    from scripts.operations_check import HEAVY_RESULTS, _pct, _ratio, admin_headers, base_url
except ModuleNotFoundError:  # pragma: no cover - direct script execution fallback
    from ntfy_notifier import notify
    from operations_check import HEAVY_RESULTS, _pct, _ratio, admin_headers, base_url


def fetch_json(path: str, *, environ: Mapping[str, str] | None = None, timeout: int = 15) -> dict[str, Any]:
    url = f'{base_url(environ)}{path}'
    request = Request(url, headers=admin_headers(environ) if path.startswith('/api/admin/') else {})
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode('utf-8'))


def _yesterday() -> str:
    return (datetime.now(ZoneInfo('Asia/Tokyo')).date() - timedelta(days=1)).isoformat()


def _metric(row: dict[str, Any], *keys: str) -> int:
    for key in keys:
        value = row.get(key)
        if isinstance(value, (int, float)):
            return int(value)
    return 0


def _bounded_percent(value: float | int | None) -> float:
    if value is None:
        return 0.0
    return max(0.0, min(100.0, float(value)))


def _result_name(row: dict[str, Any]) -> str:
    return str(row.get('fetish_name') or row.get('name') or row.get('result_name') or 'unknown')


def _result_count(row: dict[str, Any]) -> int:
    return int(row.get('total') or row.get('count') or row.get('guessed') or 0)


def _previous_day_stats(funnel: dict[str, Any], target_date: str, *, min_starts: int = 20) -> dict[str, Any]:
    rows = funnel.get('stats_history') or []
    selected = None
    for row in rows:
        if str(row.get('date') or row.get('day') or '')[:10] == target_date:
            selected = row
            break
    if selected is None:
        active = [row for row in rows if _metric(row, 'start', 'play', 'completion') > 0]
        selected = active[-1] if active else (rows[-1] if rows else {})
    selected = selected or {}
    plays = _metric(selected, 'start', 'play', 'guessed', 'plays', 'total')
    completions = _metric(selected, 'completion', 'completed', 'confirmed')
    feedback = _metric(selected, 'feedback_total') or (_metric(selected, 'correct') + _metric(selected, 'wrong'))
    if plays and completions <= plays:
        rate = _bounded_percent(_ratio(completions, plays))
    else:
        rate = None
    reliable = plays >= min_starts and rate is not None and not (rate >= 99.5 and completions >= plays and plays > 0)
    return {
        'date': str(selected.get('date') or selected.get('day') or target_date)[:10],
        'plays': plays,
        'completions': completions,
        'feedback': feedback,
        'completion_rate': rate,
        'completion_reliable': reliable,
    }


def _completion_line(stats: dict[str, Any]) -> str:
    rate = stats.get('completion_rate')
    if rate is None:
        return 'completion_rate: unavailable'
    suffix = '' if stats.get('completion_reliable') else ' (参考値)'
    return f"completion_rate: {_pct(rate)}{suffix} ({stats.get('completions', 0)}/{stats.get('plays', 0)})"


def _top_results(ranking: list[dict[str, Any]], limit: int = 5) -> list[str]:
    rows = []
    total = sum(_result_count(item) for item in ranking)
    for row in ranking[:limit]:
        name = _result_name(row)
        count = _result_count(row)
        percent = row.get('percent')
        if percent is None:
            percent = _ratio(count, total)
        rows.append(f'{name} {count} ({_pct(percent)})')
    return rows


def _heavy_ratio(ranking: list[dict[str, Any]]) -> float:
    total = sum(_result_count(row) for row in ranking)
    heavy = sum(_result_count(row) for row in ranking if _result_name(row) in HEAVY_RESULTS)
    return _ratio(heavy, total)


def _fetch_result_ranking(json_getter: Callable[[str], dict[str, Any]], *, target_date: str, top_n: int = 10) -> tuple[list[dict[str, Any]], str]:
    try:
        exposure = json_getter(f'/api/admin/result_exposures?days=1&date={target_date}&top_n={top_n}')
        ranking = exposure.get('ranking') or []
        if ranking:
            return ranking, str(exposure.get('source') or 'result_exposures')
    except Exception:
        pass
    fallback = json_getter(f'/api/admin/recent_fetish_ranking?days=1&date={target_date}&top_n={top_n}')
    return fallback.get('ranking') or [], 'stats_history_fallback'


def _top_dropoff_questions(question_report: dict[str, Any], limit: int = 3) -> list[str]:
    rows = []
    for row in question_report.get('dropoff_ranking', []):
        if int(row.get('shown') or 0) <= 0 or float(row.get('dropoff_rate') or 0) <= 0:
            continue
        text = str(row.get('question_text') or '')[:28]
        rows.append(f"Q{row.get('question_id')} {_pct(row.get('dropoff_rate'))} {text}")
        if len(rows) >= limit:
            break
    return rows


def _yes_anomaly_questions(question_report: dict[str, Any], limit: int = 3, threshold: float = 90.0) -> list[str]:
    rows = []
    for row in sorted(question_report.get('questions', []), key=lambda r: (-float(r.get('yes_rate') or 0), -int(r.get('answered') or 0))):
        if int(row.get('answered') or 0) < 5 or float(row.get('yes_rate') or 0) < threshold:
            continue
        text = str(row.get('question_text') or '')[:28]
        rows.append(f"Q{row.get('question_id')} {_pct(row.get('yes_rate'))} {text}")
        if len(rows) >= limit:
            break
    return rows


def build_daily_report(
    *,
    environ: Mapping[str, str] | None = None,
    json_getter: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    environ = os.environ if environ is None else environ
    if not admin_headers(environ):
        return {
            'status': 'warning',
            'message': '[DAILY] Hekineitor analytics\nADMIN_READ_TOKEN is not set; report skipped',
        }
    json_getter = json_getter or (lambda path: fetch_json(path, environ=environ))
    target_date = str(environ.get('HEKI_REPORT_DATE') or _yesterday())[:10]

    funnel = json_getter('/api/admin/funnel_metrics')
    ranking, result_source = _fetch_result_ranking(json_getter, target_date=target_date, top_n=10)
    share = json_getter('/api/admin/share_events?days=1&limit=5000')
    questions = json_getter('/api/admin/question_events?limit=5000')

    stats = _previous_day_stats(funnel, target_date)
    share_metrics = share.get('metrics') or {}
    result_views = int(share_metrics.get('result_page_views') or 0)
    share_actions = int(share_metrics.get('share_actions') or 0)
    share_rate = _ratio(share_actions, result_views)
    top_results = _top_results(ranking)
    dropoff = _top_dropoff_questions(questions)
    yes_anomaly = _yes_anomaly_questions(questions)

    lines = [
        '[DAILY] Hekineitor analytics',
        f"date: {stats['date']}",
        f"plays: {stats['plays']}",
        _completion_line(stats),
        f"heavy_result_ratio: {_pct(_heavy_ratio(ranking))}",
        f"result_source: {result_source}",
        f"share_rate: {_pct(share_rate)} ({share_actions}/{result_views})",
        f"question_events: {questions.get('total', 0)}",
        f"share_events: {share.get('total', 0)}",
    ]
    if int(questions.get('total') or 0) == 0:
        lines.append('note: question_events未蓄積')
    if int(share.get('total') or 0) == 0:
        lines.append('note: share_events未蓄積')
    if top_results:
        lines.append('top_results:')
        lines.extend(f'- {item}' for item in top_results)
    if dropoff:
        lines.append('dropoff_questions:')
        lines.extend(f'- {item}' for item in dropoff)
    if yes_anomaly:
        lines.append('yes_rate_anomalies:')
        lines.extend(f'- {item}' for item in yes_anomaly)
    return {'status': 'ok', 'message': '\n'.join(lines)}


def main(argv: list[str] | None = None) -> int:
    try:
        report = build_daily_report()
    except Exception as exc:
        message = f'[DAILY] Hekineitor analytics\nreport failed: {exc.__class__.__name__}'
        print(message)
        try:
            result = notify('Hekineitor DAILY failed', message, priority='high', tags='warning')
            if result.get('skipped'):
                print('ntfy skipped: ' + str(result.get('reason', 'notification disabled')))
        except Exception as notify_exc:
            print(f'ntfy failed: {notify_exc.__class__.__name__}', file=sys.stderr)
        return 1
    print(report['message'])
    try:
        result = notify('Hekineitor DAILY', report['message'], priority='default', tags='bar_chart')
        if result.get('skipped'):
            print('ntfy skipped: ' + str(result.get('reason', 'notification disabled')))
    except Exception as exc:
        print(f'ntfy failed: {exc.__class__.__name__}', file=sys.stderr)
        return 0
    return 0


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
