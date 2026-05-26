import json
import os
import re
import threading
from collections import deque
from datetime import datetime, timezone

from storage import data_path
from services.csv_safety import csv_text

_ALLOWED_EVENTS = {
    'share_button_click',
    'web_share_success',
    'web_share_failure',
    'copy_success',
    'copy_failure',
    'x_share_click',
    'result_page_view',
    'ogp_png_view',
    'ogp_svg_view',
}
_ALLOWED_CHANNELS = {'button', 'web_share', 'clipboard', 'x', 'result_page', 'ogp'}
_LOCK = threading.Lock()
_MAX_LOG_BYTES = 5 * 1024 * 1024
_SENSITIVE_RESULT_RE = re.compile(r'(@|https?://|postgres(?:ql)?://|\b(?:token|secret|passwd|password|api[_-]?key)\b|(?=[A-Za-z0-9_-]*\d)[A-Za-z0-9_-]{32,})', re.IGNORECASE)


def event_log_path(environ=None):
    environ = environ or os.environ
    return environ.get('SHARE_EVENT_LOG_PATH') or data_path('share_events.jsonl')


def _clean_text(value, max_len=80):
    return str(value or '').strip()[:max_len]


def _clean_result_name(value, max_len=80):
    text = _clean_text(value, max_len)
    if _SENSITIVE_RESULT_RE.search(text):
        return ''
    return text


def _clean_bool(value):
    if value is None:
        return None
    return bool(value)


def build_event(event_name, *, result_name='', channel='', success=None, now_fn=None):
    event_name = _clean_text(event_name, 40)
    channel = _clean_text(channel, 32)
    if event_name not in _ALLOWED_EVENTS:
        raise ValueError('unknown share event')
    if channel and channel not in _ALLOWED_CHANNELS:
        raise ValueError('unknown share channel')
    now = now_fn() if now_fn else datetime.now(timezone.utc)
    return {
        'timestamp': now.astimezone(timezone.utc).isoformat(timespec='seconds'),
        'event_name': event_name,
        'result_name': _clean_result_name(result_name, 80),
        'channel': channel,
        'success': _clean_bool(success),
    }


def _rotate_if_needed(target, max_bytes=_MAX_LOG_BYTES):
    try:
        if os.path.getsize(target) <= max_bytes:
            return
    except OSError:
        return
    rotated = target + '.1'
    try:
        if os.path.exists(rotated):
            os.remove(rotated)
        os.replace(target, rotated)
    except OSError:
        pass


def record_event(event_name, *, result_name='', channel='', success=None, path=None, environ=None, now_fn=None):
    event = build_event(event_name, result_name=result_name, channel=channel, success=success, now_fn=now_fn)
    target = path or event_log_path(environ)
    os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)
    line = json.dumps(event, ensure_ascii=False, separators=(',', ':')) + '\n'
    with _LOCK:
        _rotate_if_needed(target)
        with open(target, 'a', encoding='utf-8') as file_obj:
            file_obj.write(line)
    return event


def safe_record_event(*args, **kwargs):
    try:
        return record_event(*args, **kwargs)
    except Exception:
        return None


def event_count(*, path=None, environ=None):
    target = path or event_log_path(environ)
    count = 0
    try:
        with open(target, encoding='utf-8') as file_obj:
            for line in file_obj:
                if line.strip():
                    count += 1
    except OSError:
        return 0
    return count


def read_events(path=None, environ=None, limit=500):
    target = path or event_log_path(environ)
    try:
        max_lines = min(max(1, int(limit or 500)), 5000)
    except (TypeError, ValueError):
        max_lines = 500
    try:
        with open(target, encoding='utf-8') as file_obj:
            lines = list(deque(file_obj, maxlen=max_lines))
    except OSError:
        return []
    events = []
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def _event_date(event):
    timestamp = str(event.get('timestamp') or '')
    if len(timestamp) >= 10:
        return timestamp[:10]
    return 'unknown'


def _clean_date(value):
    value = _clean_text(value, 10)
    if len(value) == 10 and value[4] == '-' and value[7] == '-':
        year, month, day = value.split('-')
        if year.isdigit() and month.isdigit() and day.isdigit():
            return value
    return ''


def _clean_positive_int(value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def filter_events(events, *, since=None, until=None, days=None):
    since = _clean_date(since)
    until = _clean_date(until)
    days = _clean_positive_int(days)
    rows = list(events)
    if days:
        dates = sorted({_event_date(event) for event in rows if _event_date(event) != 'unknown'})
        if dates:
            since = max(since, dates[-days]) if since else dates[-days]
    if since:
        rows = [event for event in rows if _event_date(event) >= since]
    if until:
        rows = [event for event in rows if _event_date(event) <= until]
    return rows


def _summary_metrics(by_event):
    return {
        'share_button_clicks': by_event.get('share_button_click', 0),
        'result_page_views': by_event.get('result_page_view', 0),
        'ogp_views': by_event.get('ogp_png_view', 0) + by_event.get('ogp_svg_view', 0),
        'ogp_png_views': by_event.get('ogp_png_view', 0),
        'ogp_svg_views': by_event.get('ogp_svg_view', 0),
        'x_clicks': by_event.get('x_share_click', 0),
        'web_share_successes': by_event.get('web_share_success', 0),
        'web_share_failures': by_event.get('web_share_failure', 0),
        'copy_successes': by_event.get('copy_success', 0),
        'copy_failures': by_event.get('copy_failure', 0),
        'share_actions': (
            by_event.get('x_share_click', 0)
            + by_event.get('web_share_success', 0)
            + by_event.get('copy_success', 0)
        ),
        'share_successes': by_event.get('web_share_success', 0) + by_event.get('copy_success', 0),
    }


def _empty_daily_row(date):
    return {
        'date': date,
        'total': 0,
        'share_button_clicks': 0,
        'result_page_views': 0,
        'ogp_views': 0,
        'x_clicks': 0,
        'web_share_successes': 0,
        'copy_successes': 0,
    }


def daily_summary(events, days=14):
    daily = {}
    for event in events:
        date = _event_date(event)
        row = daily.setdefault(date, _empty_daily_row(date))
        row['total'] += 1
        name = event.get('event_name') or ''
        if name == 'share_button_click':
            row['share_button_clicks'] += 1
        elif name == 'result_page_view':
            row['result_page_views'] += 1
        elif name in ('ogp_png_view', 'ogp_svg_view'):
            row['ogp_views'] += 1
        elif name == 'x_share_click':
            row['x_clicks'] += 1
        elif name == 'web_share_success':
            row['web_share_successes'] += 1
        elif name == 'copy_success':
            row['copy_successes'] += 1
    rows = [daily[key] for key in sorted(daily)]
    return rows[-max(1, int(days or 14)):]


def _empty_result_row(result_name):
    return {
        'result_name': result_name,
        'total': 0,
        'share_button_clicks': 0,
        'result_page_views': 0,
        'ogp_views': 0,
        'x_clicks': 0,
        'web_share_successes': 0,
        'copy_successes': 0,
        'share_actions': 0,
        'share_successes': 0,
        'ogp_to_result_rate': None,
        'result_to_share_rate': None,
        'share_success_rate': None,
    }


def _percentage(numerator, denominator):
    if not denominator:
        return None
    return round(numerator / denominator * 100, 1)


def _finalize_result_row(row):
    row['share_actions'] = row['x_clicks'] + row['web_share_successes'] + row['copy_successes']
    row['share_successes'] = row['web_share_successes'] + row['copy_successes']
    row['ogp_to_result_rate'] = _percentage(row['result_page_views'], row['ogp_views'])
    row['result_to_share_rate'] = _percentage(row['share_button_clicks'], row['result_page_views'])
    row['share_success_rate'] = _percentage(row['share_successes'], row['share_button_clicks'])
    return row


def result_ranking(events, limit=20):
    ranking = {}
    for event in events:
        result_name = _clean_result_name(event.get('result_name'), 80)
        if not result_name:
            continue
        row = ranking.setdefault(result_name, _empty_result_row(result_name))
        row['total'] += 1
        name = event.get('event_name') or ''
        if name == 'share_button_click':
            row['share_button_clicks'] += 1
        elif name == 'result_page_view':
            row['result_page_views'] += 1
        elif name in ('ogp_png_view', 'ogp_svg_view'):
            row['ogp_views'] += 1
        elif name == 'x_share_click':
            row['x_clicks'] += 1
        elif name == 'web_share_success':
            row['web_share_successes'] += 1
        elif name == 'copy_success':
            row['copy_successes'] += 1
    rows = sorted(
        [_finalize_result_row(row) for row in ranking.values()],
        key=lambda row: (
            row['share_button_clicks'],
            row['share_actions'],
            row['ogp_views'],
            row['result_page_views'],
            row['total'],
            row['result_name'],
        ),
        reverse=True,
    )
    return rows[:max(1, int(limit or 20))]


def _report_for_events(events):
    by_event = {}
    by_channel = {}
    success = {'true': 0, 'false': 0, 'unknown': 0}
    for event in events:
        name = event.get('event_name') or 'unknown'
        channel = event.get('channel') or 'unknown'
        by_event[name] = by_event.get(name, 0) + 1
        by_channel[channel] = by_channel.get(channel, 0) + 1
        flag = event.get('success')
        if flag is True:
            success['true'] += 1
        elif flag is False:
            success['false'] += 1
        else:
            success['unknown'] += 1
    return {
        'total': len(events),
        'by_event': by_event,
        'by_channel': by_channel,
        'success': success,
        'metrics': _summary_metrics(by_event),
        'daily': daily_summary(events, days=14),
        'ranking': result_ranking(events, limit=20),
        'recent': events[-20:],
    }


def _delta(current, previous):
    return current - previous


def _growth_rate(current, previous):
    if previous == 0:
        return None
    return round((current - previous) / previous * 100, 1)


def _ranking_with_comparison(current_rows, previous_rows):
    previous_by_name = {row['result_name']: row for row in previous_rows}
    rows = []
    for row in current_rows:
        previous = previous_by_name.get(row['result_name'], {})
        merged = dict(row)
        previous_share_actions = previous.get('share_actions', 0)
        previous_total = previous.get('total', 0)
        merged['previous_total'] = previous_total
        merged['previous_share_actions'] = previous_share_actions
        merged['share_actions_delta'] = _delta(row.get('share_actions', 0), previous_share_actions)
        merged['share_actions_growth_rate'] = _growth_rate(row.get('share_actions', 0), previous_share_actions)
        merged['total_delta'] = _delta(row.get('total', 0), previous_total)
        merged['total_growth_rate'] = _growth_rate(row.get('total', 0), previous_total)
        rows.append(merged)
    rows.sort(key=lambda row: (row['share_actions_delta'], row['total_delta'], row['share_actions']), reverse=True)
    return rows


def _comparison(current_report, previous_report):
    keys = ['total', 'share_actions', 'share_successes', 'ogp_views', 'result_page_views']
    current_metrics = {'total': current_report['total'], **current_report['metrics']}
    previous_metrics = {'total': previous_report['total'], **previous_report['metrics']}
    metrics = {}
    for key in keys:
        current = current_metrics.get(key, 0)
        previous = previous_metrics.get(key, 0)
        metrics[key] = {
            'current': current,
            'previous': previous,
            'delta': _delta(current, previous),
            'growth_rate': _growth_rate(current, previous),
        }
    return {
        'enabled': True,
        'sample_warning': current_report['total'] < 10 or previous_report['total'] < 10,
        'metrics': metrics,
        'ranking': _ranking_with_comparison(current_report['ranking'], previous_report['ranking']),
    }


def event_report(path=None, environ=None, limit=500, since=None, until=None, days=None, compare_since=None, compare_until=None):
    all_events = read_events(path=path, environ=environ, limit=limit)
    events = filter_events(all_events, since=since, until=until, days=days)
    report = _report_for_events(events)
    report['filters'] = {
        'days': _clean_positive_int(days),
        'since': _clean_date(since),
        'until': _clean_date(until),
        'compare_since': _clean_date(compare_since),
        'compare_until': _clean_date(compare_until),
    }
    if compare_since or compare_until:
        previous_events = filter_events(all_events, since=compare_since, until=compare_until)
        comparison = _comparison(report, _report_for_events(previous_events))
        report['comparison'] = comparison
        report['ranking'] = comparison['ranking']
    else:
        report['comparison'] = {'enabled': False}
    return report


_META_FIELDS = ['filter_days', 'filter_since', 'filter_until', 'compare_since', 'compare_until']


def _filter_metadata(report):
    filters = report.get('filters') or {}
    return {
        'filter_days': filters.get('days') or '',
        'filter_since': filters.get('since') or '',
        'filter_until': filters.get('until') or '',
        'compare_since': filters.get('compare_since') or '',
        'compare_until': filters.get('compare_until') or '',
    }


def _rows_with_metadata(report, rows):
    meta = _filter_metadata(report)
    return [{**row, **meta} for row in rows]

def ranking_csv(report):
    return csv_text(_rows_with_metadata(report, report.get('ranking', [])), [
        'result_name', 'total', 'share_button_clicks', 'result_page_views', 'ogp_views',
        'x_clicks', 'web_share_successes', 'copy_successes', 'share_actions',
        'share_successes', 'ogp_to_result_rate', 'result_to_share_rate', 'share_success_rate',
        'previous_total', 'total_delta', 'total_growth_rate',
        'previous_share_actions', 'share_actions_delta', 'share_actions_growth_rate',
        *_META_FIELDS,
    ])


def daily_csv(report):
    return csv_text(_rows_with_metadata(report, report.get('daily', [])), [
        'date', 'total', 'share_button_clicks', 'result_page_views', 'ogp_views',
        'x_clicks', 'web_share_successes', 'copy_successes',
        *_META_FIELDS,
    ])


def comparison_csv(report):
    comparison = report.get('comparison') or {}
    rows = []
    for key, values in (comparison.get('metrics') or {}).items():
        row = {'metric': key}
        row.update(values)
        rows.append(row)
    return csv_text(
        _rows_with_metadata(report, rows),
        ['metric', 'current', 'previous', 'delta', 'growth_rate', *_META_FIELDS],
    )
