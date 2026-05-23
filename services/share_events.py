import json
import os
import threading
from datetime import datetime, timezone

from storage import data_path

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


def event_log_path(environ=None):
    environ = environ or os.environ
    return environ.get('SHARE_EVENT_LOG_PATH') or data_path('share_events.jsonl')


def _clean_text(value, max_len=80):
    return str(value or '').strip()[:max_len]


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
        'result_name': _clean_text(result_name, 80),
        'channel': channel,
        'success': _clean_bool(success),
    }


def record_event(event_name, *, result_name='', channel='', success=None, path=None, environ=None, now_fn=None):
    event = build_event(event_name, result_name=result_name, channel=channel, success=success, now_fn=now_fn)
    target = path or event_log_path(environ)
    os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)
    line = json.dumps(event, ensure_ascii=False, separators=(',', ':')) + '\n'
    with _LOCK:
        with open(target, 'a', encoding='utf-8') as file_obj:
            file_obj.write(line)
    return event


def safe_record_event(*args, **kwargs):
    try:
        return record_event(*args, **kwargs)
    except Exception:
        return None


def read_events(path=None, environ=None, limit=500):
    target = path or event_log_path(environ)
    try:
        with open(target, encoding='utf-8') as file_obj:
            lines = file_obj.readlines()[-max(1, int(limit or 500)):]
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


def event_report(path=None, environ=None, limit=500):
    events = read_events(path=path, environ=environ, limit=limit)
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
        'recent': events[-20:],
    }
