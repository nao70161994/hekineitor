#!/usr/bin/env python3
"""Compare production/local analytics data before and after log-quality filtering."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.operations_check import admin_headers, base_url
from services import question_events, result_exposure, share_events

DEFAULT_DATES = ('2026-06-19', '2026-06-20', '2026-06-21')
HEAVY_RESULTS = {'共依存', '激重感情', '共生関係', '執着'}


def _count_value(row: dict[str, Any]) -> int:
    return int(row.get('count') or row.get('total') or row.get('guessed') or 0)


def _row_name(row: dict[str, Any]) -> str:
    return str(row.get('fetish_name') or row.get('result_name') or row.get('name') or 'unknown')


def _ranking_names(report: dict[str, Any]) -> set[str]:
    return {_row_name(row) for row in report.get('ranking') or []}


def _top_share(report: dict[str, Any]) -> tuple[str, int, int, float]:
    rows = report.get('ranking') or []
    total = sum(_count_value(row) for row in rows)
    if not rows or total <= 0:
        return 'none', 0, total, 0.0
    top = rows[0]
    count = _count_value(top)
    return _row_name(top), count, total, count / total


def _same_top_ranking(left: dict[str, Any], right: dict[str, Any], *, limit: int = 3) -> bool:
    left_rows = [(_row_name(row), _count_value(row)) for row in (left.get('ranking') or [])[:limit]]
    right_rows = [(_row_name(row), _count_value(row)) for row in (right.get('ranking') or [])[:limit]]
    return left_rows == right_rows


def _parse_expected_counts(values: list[str] | None, label: str) -> dict[str, int]:
    parsed: dict[str, int] = {}
    for value in values or []:
        if '=' not in value:
            raise SystemExit(f'--{label} must be DATE=COUNT')
        date, count = value.split('=', 1)
        try:
            parsed[date.strip()[:10]] = int(count)
        except ValueError as exc:
            raise SystemExit(f'--{label} count must be an integer: {value}') from exc
    return parsed


class EmptyEngine:
    questions: list[dict[str, Any]] = []

    def _question_axis(self, question_id):
        return None


def _fetch_json(path: str, environ: dict[str, str], timeout: int) -> dict[str, Any]:
    url = f'{base_url(environ)}{path}'
    request = Request(url, headers=admin_headers(environ) if path.startswith('/api/admin/') else {})
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode('utf-8'))


def _query(path: str, **params: Any) -> str:
    clean = {key: value for key, value in params.items() if value not in (None, '')}
    return path + ('?' + urlencode(clean) if clean else '')


def _ranking_summary(rows: list[dict[str, Any]], limit: int = 5) -> str:
    parts = []
    for row in rows[:limit]:
        name = _row_name(row)
        count = _count_value(row)
        percent = row.get('percent')
        suffix = f' ({percent}%)' if isinstance(percent, (int, float)) else ''
        parts.append(f'{name}={count}{suffix}')
    return ', '.join(parts) if parts else 'none'


def _dropoff_summary(rows: list[dict[str, Any]], limit: int = 3) -> str:
    parts = []
    for row in rows[:limit]:
        qid = row.get('question_id', '?')
        dropoff = int(row.get('dropoff') or 0)
        shown = int(row.get('shown') or 0)
        rate = row.get('dropoff_rate')
        suffix = f'{rate}%' if isinstance(rate, (int, float)) else 'n/a'
        parts.append(f'Q{qid} {suffix} ({dropoff}/{shown})')
    return ', '.join(parts) if parts else 'none'


def _by_event_summary(by_event: dict[str, Any]) -> str:
    keys = (
        'result_page_view',
        'share_button_click',
        'x_share_click',
        'web_share_success',
        'copy_success',
        'ogp_png_view',
        'ogp_svg_view',
        'work_click',
    )
    parts = [f'{key}={int(by_event.get(key) or 0)}' for key in keys if int(by_event.get(key) or 0)]
    return ', '.join(parts) if parts else 'none'


def _heavy_ratio(report: dict[str, Any]) -> str:
    rows = report.get('ranking') or []
    total = sum(_count_value(row) for row in rows)
    if total <= 0:
        return '0/0 unavailable'
    heavy = sum(_count_value(row) for row in rows if _row_name(row) in HEAVY_RESULTS)
    return f'{heavy}/{total} ({heavy / total * 100:.1f}%)'


def _local_reports(date: str, limit: int) -> dict[str, Any]:
    q_path = ROOT / 'data' / 'question_events.jsonl'
    s_path = ROOT / 'data' / 'share_events.jsonl'
    r_path = ROOT / 'data' / 'result_exposures.jsonl'
    engine = EmptyEngine()
    return {
        'question_filtered': question_events.event_report(
            engine, path=str(q_path), limit=limit, date=date, exclude_suspicious=True
        ),
        'question_raw': question_events.event_report(
            engine, path=str(q_path), limit=limit, date=date, exclude_suspicious=False
        ),
        'share': share_events.event_report(path=str(s_path), limit=limit, since=date, until=date),
        'result_displayed': result_exposure.ranking_report(
            path=str(r_path), limit=limit, date=date, top_n=10, include_secondary=True
        ),
        'result_primary': result_exposure.ranking_report(
            path=str(r_path), limit=limit, date=date, top_n=10, include_secondary=False
        ),
        'result_candidates': result_exposure.ranking_report(
            path=str(r_path), limit=limit, date=date, top_n=10, include_secondary=True, include_candidates=True
        ),
    }


def _api_reports(date: str, limit: int, environ: dict[str, str], timeout: int) -> dict[str, Any]:
    return {
        'question_filtered': _fetch_json(
            _query('/api/admin/question_events', date=date, limit=limit, exclude_suspicious=1), environ, timeout
        ),
        'question_raw': _fetch_json(
            _query('/api/admin/question_events', date=date, limit=limit, exclude_suspicious=0), environ, timeout
        ),
        'share': _fetch_json(_query('/api/admin/share_events', since=date, until=date, limit=limit), environ, timeout),
        'result_displayed': _fetch_json(
            _query('/api/admin/result_exposures', days=1, date=date, top_n=10, include_secondary=1), environ, timeout
        ),
        'result_primary': _fetch_json(
            _query('/api/admin/result_exposures', days=1, date=date, top_n=10), environ, timeout
        ),
        'result_candidates': _fetch_json(
            _query(
                '/api/admin/result_exposures', days=1, date=date, top_n=10, include_secondary=1, include_candidates=1
            ),
            environ,
            timeout,
        ),
    }


def _date_findings(
    date: str,
    reports: dict[str, Any],
    *,
    expected_question_events: dict[str, int] | None = None,
    expected_share_events: dict[str, int] | None = None,
    expected_results: list[str] | None = None,
    min_result_samples: int = 20,
    dominant_ratio: float = 0.65,
) -> list[str]:
    expected_question_events = expected_question_events or {}
    expected_share_events = expected_share_events or {}
    expected_results = expected_results or []
    qf = reports['question_filtered']
    qr = reports['question_raw']
    share = reports['share']
    displayed = reports['result_displayed']
    primary = reports['result_primary']
    candidates = reports.get('result_candidates') or {'ranking': []}
    findings: list[str] = []

    analyzed = int(qf.get('total') or 0)
    raw_total = int(qr.get('total_available', qr.get('raw_loaded', qr.get('total', 0))) or 0)
    excluded = int((qf.get('quality') or {}).get('excluded_suspicious_events') or 0)
    if excluded > 0:
        findings.append(
            f'question_events excluded suspicious rows={excluded}; compare analyzed={analyzed} vs raw={raw_total}'
        )
    if date in expected_question_events and expected_question_events[date] != raw_total:
        findings.append(
            f'question_events mismatch previous_log={expected_question_events[date]} current_api={raw_total}'
        )

    share_total = int(share.get('total') or 0)
    metrics = share.get('metrics') or {}
    result_views = int(metrics.get('result_page_views') or 0)
    share_actions = int(metrics.get('share_actions') or 0)
    if date in expected_share_events and expected_share_events[date] != share_total:
        findings.append(f'share_events mismatch previous_log={expected_share_events[date]} current_api={share_total}')
    if result_views == 0 and share_total > 0:
        findings.append('share_rate denominator missing: share events exist but result_page_view=0')
    if share_total > 0 and share_actions == 0:
        findings.append('share_events contain no share actions; totals are views/OGP/work events only')

    displayed_total = int(displayed.get('total') or 0)
    primary_total = int(primary.get('total') or 0)
    if displayed_total > primary_total:
        findings.append(
            f'displayed results exceed primary by {displayed_total - primary_total}; compound/secondary exposure affects displayed ranking'
        )
    elif displayed_total == primary_total and displayed_total > 0 and _same_top_ranking(displayed, primary):
        findings.append('displayed and primary rankings match; observed bias is not from secondary result inflation')
    if primary_total and primary_total < min_result_samples:
        findings.append(f'result sample is small primary_total={primary_total}; treat dominance as reference only')
    top_name, top_count, top_total, top_ratio = _top_share(primary)
    if top_total and top_ratio >= dominant_ratio:
        findings.append(f'primary result dominated by {top_name}: {top_count}/{top_total} ({top_ratio * 100:.1f}%)')

    displayed_names = _ranking_names(displayed)
    primary_names = _ranking_names(primary)
    candidate_names = _ranking_names(candidates)
    for expected in expected_results:
        if expected not in displayed_names and expected not in primary_names and expected not in candidate_names:
            findings.append(f'expected observed result missing from result_exposures ranking: {expected}')
        elif expected in candidate_names and expected not in displayed_names and expected not in primary_names:
            findings.append(f'expected observed result appears only in candidate/top_chart exposures: {expected}')
    return findings


def _print_date_report(date: str, reports: dict[str, Any], findings: list[str] | None = None) -> None:
    qf = reports['question_filtered']
    qr = reports['question_raw']
    quality = qf.get('quality') or {}
    excluded = int(quality.get('excluded_suspicious_events') or 0)
    suspicious = int(quality.get('suspicious_timestamp_count') or 0)
    print(f'## {date}')
    print(
        f'question_events: analyzed={int(qf.get("total") or 0)} raw_loaded={int(qr.get("raw_loaded", qr.get("total", 0)) or 0)} total_available={int(qr.get("total_available", qr.get("total", 0)) or 0)} excluded={excluded} suspicious_buckets={suspicious}'
    )
    print(f'question_dropoff_filtered: {_dropoff_summary(qf.get("dropoff_ranking") or [])}')
    print(f'question_dropoff_raw: {_dropoff_summary(qr.get("dropoff_ranking") or [])}')
    if qf.get('warnings'):
        print('question_warnings: ' + ', '.join(str(row.get('type') or row) for row in qf.get('warnings') or []))

    share = reports['share']
    metrics = share.get('metrics') or {}
    result_views = int(metrics.get('result_page_views') or 0)
    share_actions = int(metrics.get('share_actions') or 0)
    denominator_note = ' denominator_missing' if result_views == 0 and int(share.get('total') or 0) > 0 else ''
    print(
        f'share_events: total={int(share.get("total") or 0)} result_views={result_views} share_actions={share_actions}{denominator_note}'
    )
    print(f'share_events_breakdown: {_by_event_summary(share.get("by_event") or {})}')

    displayed = reports['result_displayed']
    primary = reports['result_primary']
    candidates = reports.get('result_candidates') or {'ranking': []}
    displayed_total = int(displayed.get('total') or 0)
    primary_total = int(primary.get('total') or 0)
    print(f'result_displayed: total={displayed_total} top={_ranking_summary(displayed.get("ranking") or [])}')
    print(f'result_primary: total={primary_total} top={_ranking_summary(primary.get("ranking") or [])}')
    print(
        f'result_candidates: total={int(candidates.get("total") or 0)} top={_ranking_summary(candidates.get("ranking") or [])}'
    )
    print(f'result_secondary_extra: {max(0, displayed_total - primary_total)}')
    print(f'heavy_result_ratio_displayed: {_heavy_ratio(displayed)}')
    print(f'heavy_result_ratio_primary: {_heavy_ratio(primary)}')
    if findings:
        print('findings:')
        for finding in findings:
            print(f'- {finding}')
    print('')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', choices=('local', 'api'), default='local')
    parser.add_argument('--date', action='append', dest='dates', help='YYYY-MM-DD. Can be repeated.')
    parser.add_argument('--limit', type=int, default=50000)
    parser.add_argument('--timeout', type=int, default=20)
    parser.add_argument(
        '--expected-question-events',
        action='append',
        default=[],
        help='Previous daily log question count as YYYY-MM-DD=COUNT.',
    )
    parser.add_argument(
        '--expected-share-events',
        action='append',
        default=[],
        help='Previous daily log share count as YYYY-MM-DD=COUNT.',
    )
    parser.add_argument(
        '--expected-result',
        action='append',
        default=[],
        help='Result name observed elsewhere that should appear in exposure rankings.',
    )
    parser.add_argument('--min-result-samples', type=int, default=20)
    parser.add_argument('--dominant-ratio', type=float, default=0.65)
    args = parser.parse_args(argv)

    dates = args.dates or list(DEFAULT_DATES)
    expected_question_events = _parse_expected_counts(args.expected_question_events, 'expected-question-events')
    expected_share_events = _parse_expected_counts(args.expected_share_events, 'expected-share-events')
    environ = dict(os.environ)
    if args.source == 'api' and not environ.get('ADMIN_READ_TOKEN'):
        print('ERROR: ADMIN_READ_TOKEN is not set; cannot read production admin APIs.', file=sys.stderr)
        return 2

    print(f'analytics_data_diff source={args.source} dates={",".join(dates)}')
    print('')
    for date in dates:
        reports = (
            _api_reports(date, args.limit, environ, args.timeout)
            if args.source == 'api'
            else _local_reports(date, args.limit)
        )
        findings = _date_findings(
            date,
            reports,
            expected_question_events=expected_question_events,
            expected_share_events=expected_share_events,
            expected_results=args.expected_result,
            min_result_samples=args.min_result_samples,
            dominant_ratio=args.dominant_ratio,
        )
        _print_date_report(date, reports, findings)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
