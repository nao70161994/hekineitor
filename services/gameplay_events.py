"""Privacy-safe gameplay-loop analytics.

Events deliberately exclude IP addresses, user agents, session identifiers,
free-form text, and answer values.  They measure product flow rather than
individual players.
"""

import json
import os
import threading
from collections import Counter, deque
from datetime import datetime, timezone

from services import event_store
from storage import data_path

ALLOWED_EVENTS = {
    'diagnosis_started',
    'result_shown',
    'retry_started',
    'exclude_retry_started',
    'continue_started',
    'feedback_completed',
    'work_impression',
    'history_reopened',
    'resume_started',
    'draft_discarded',
    'question_repeated',
}
ALLOWED_SOURCES = {'start', 'result', 'history', 'resume', 'feedback', 'works', 'draft'}
ALLOWED_OUTCOMES = {'success', 'failure', 'yes', 'maybe', 'no', 'discarded', 'expired'}
_LOCK = threading.Lock()
_MAX_LOG_BYTES = 5 * 1024 * 1024


def event_log_path(environ=None):
    environ = environ or os.environ
    return environ.get('GAMEPLAY_EVENT_LOG_PATH') or data_path('gameplay_events.jsonl')


def _bounded_int(value, *, minimum=0, maximum=100000):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return max(minimum, min(parsed, maximum))


def _safe_id(value, max_len=64):
    value = str(value or '').strip()
    if not value or len(value) > max_len or not all(char.isalnum() or char in '_-' for char in value):
        return ''
    return value


def build_event(
    event_name,
    *,
    source='',
    outcome='',
    result_id=None,
    question_id=None,
    answered_count=None,
    work_id='',
    edition_id='',
    now_fn=None,
):
    event_name = str(event_name or '').strip()
    source = str(source or '').strip()
    outcome = str(outcome or '').strip()
    if event_name not in ALLOWED_EVENTS:
        raise ValueError('unknown gameplay event')
    if source and source not in ALLOWED_SOURCES:
        raise ValueError('unknown gameplay source')
    if outcome and outcome not in ALLOWED_OUTCOMES:
        raise ValueError('unknown gameplay outcome')
    now = now_fn() if now_fn else datetime.now(timezone.utc)
    event = {
        'timestamp': now.astimezone(timezone.utc).isoformat(timespec='seconds'),
        'event_name': event_name,
    }
    if source:
        event['source'] = source
    if outcome:
        event['outcome'] = outcome
    for key, value, maximum in (
        ('result_id', result_id, 1000000000),
        ('question_id', question_id, 1000000),
        ('answered_count', answered_count, 1000),
    ):
        parsed = _bounded_int(value, maximum=maximum)
        if parsed is not None:
            event[key] = parsed
    for key, value in (('work_id', work_id), ('edition_id', edition_id)):
        clean = _safe_id(value)
        if clean:
            event[key] = clean
    return event


def _rotate_if_needed(path):
    try:
        if os.path.getsize(path) <= _MAX_LOG_BYTES:
            return
    except OSError:
        return
    rotated = path + '.1'
    try:
        if os.path.exists(rotated):
            os.remove(rotated)
        os.replace(path, rotated)
    except OSError:
        pass


def record_event(event_name, *, path=None, environ=None, now_fn=None, **fields):
    event = build_event(event_name, now_fn=now_fn, **fields)
    if path is None and event_store.enabled(environ):
        try:
            return event_store.record_event('gameplay', event)
        except Exception:
            pass
    target = path or event_log_path(environ)
    os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)
    line = json.dumps(event, ensure_ascii=False, separators=(',', ':')) + '\n'
    with _LOCK:
        _rotate_if_needed(target)
        with open(target, 'a', encoding='utf-8') as output:
            output.write(line)
    return event


def safe_record_event(*args, **kwargs):
    try:
        return record_event(*args, **kwargs)
    except Exception:
        return None


def read_events(*, path=None, environ=None, limit=5000):
    if path is None and event_store.enabled(environ):
        try:
            return event_store.read_events('gameplay', limit=limit)
        except Exception:
            return []
    try:
        limit = max(1, min(int(limit or 5000), 50000))
    except (TypeError, ValueError):
        limit = 5000
    try:
        with open(path or event_log_path(environ), encoding='utf-8') as source:
            lines = list(deque(source, maxlen=limit))
    except OSError:
        return []
    events = []
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and event.get('event_name') in ALLOWED_EVENTS:
            events.append(event)
    return events


def event_count(*, path=None, environ=None):
    if path is None and event_store.enabled(environ):
        try:
            return event_store.event_count('gameplay')
        except Exception:
            return 0
    return len(read_events(path=path, environ=environ, limit=50000))


def storage_status(*, path=None, environ=None):
    if path is None and event_store.enabled(environ):
        return event_store.storage_status('gameplay')
    target = os.path.abspath(path or event_log_path(environ))
    parent = os.path.dirname(target)
    exists = os.path.exists(target)
    parent_exists = os.path.isdir(parent)
    parent_writable = os.access(parent, os.W_OK) if parent_exists else False
    return {
        'path': target,
        'parent': parent,
        'exists': exists,
        'parent_exists': parent_exists,
        'parent_writable': bool(parent_writable),
        'file_writable': bool(os.access(target, os.W_OK) if exists else parent_writable),
        'count': event_count(path=target),
    }


def _rate(numerator, denominator):
    return round(numerator / denominator * 100, 1) if denominator else None


def event_report(*, events=None, path=None, environ=None, limit=5000, work_clicks=0, questions_shown=0):
    rows = list(events) if events is not None else read_events(path=path, environ=environ, limit=limit)
    counts = Counter(str(event.get('event_name') or '') for event in rows)
    results = counts['result_shown']
    return {
        'total': len(rows),
        'by_event': dict(sorted(counts.items())),
        'metrics': {
            'retry_rate': _rate(counts['retry_started'], results),
            'exclude_retry_rate': _rate(counts['exclude_retry_started'], results),
            'continue_rate': _rate(counts['continue_started'], results),
            'feedback_completion_rate': _rate(counts['feedback_completed'], results),
            'work_click_rate': _rate(int(work_clicks or 0), counts['work_impression']),
            'question_repeat_rate': _rate(counts['question_repeated'], int(questions_shown or 0)),
        },
        'recent': rows[-20:],
    }
