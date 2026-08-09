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
from services.csv_safety import csv_text
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
    'work_click',
    'diagnosis_summary',
}
ALLOWED_SOURCES = {'start', 'result', 'history', 'resume', 'feedback', 'works', 'draft'}
ALLOWED_OUTCOMES = {'success', 'failure', 'yes', 'maybe', 'no', 'discarded', 'expired'}
ALLOWED_SUMMARY_STATUSES = {'completed', 'abandoned', 'restarted', 'discarded', 'expired'}
ALLOWED_RETRY_KINDS = {'', 'new', 'retry', 'exclude_retry', 'resume'}
SCHEMA_VERSION = 2
SUMMARY_SESSION_KEY = '_gameplay_summary_v2'
_LOCK = threading.Lock()
_MAX_LOG_BYTES = 5 * 1024 * 1024
POSTGRES_RETENTION_DAYS = 90


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
    if not value or len(value) > max_len or not all(char.isalnum() or char in '._-' for char in value):
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
    summary_status='',
    retry_kind='',
    feedback_outcome='',
    result_reached=None,
    continued=None,
    correction_count=None,
    work_impressions=None,
    work_clicks=None,
    question_repeats=None,
    release='',
    environ=None,
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
    summary_status = str(summary_status or '').strip()
    retry_kind = str(retry_kind or '').strip()
    feedback_outcome = str(feedback_outcome or '').strip()
    if summary_status and summary_status not in ALLOWED_SUMMARY_STATUSES:
        raise ValueError('unknown gameplay summary status')
    if retry_kind not in ALLOWED_RETRY_KINDS:
        raise ValueError('unknown gameplay retry kind')
    if feedback_outcome and feedback_outcome not in {'yes', 'maybe', 'no'}:
        raise ValueError('unknown gameplay feedback outcome')
    environ = environ or os.environ
    release = _safe_id(release or environ.get('RENDER_GIT_COMMIT') or environ.get('RELEASE_VERSION') or 'dev')
    now = now_fn() if now_fn else datetime.now(timezone.utc)
    event = {
        'timestamp': now.astimezone(timezone.utc).isoformat(timespec='seconds'),
        'event_name': event_name,
        'schema_version': SCHEMA_VERSION,
        'release': release or 'dev',
    }
    if source:
        event['source'] = source
    if outcome:
        event['outcome'] = outcome
    for key, value, maximum in (
        ('result_id', result_id, 1000000000),
        ('question_id', question_id, 1000000),
        ('answered_count', answered_count, 1000),
        ('correction_count', correction_count, 100),
        ('work_impressions', work_impressions, 1000),
        ('work_clicks', work_clicks, 1000),
        ('question_repeats', question_repeats, 1000),
    ):
        parsed = _bounded_int(value, maximum=maximum)
        if parsed is not None:
            event[key] = parsed
    for key, value in (('work_id', work_id), ('edition_id', edition_id)):
        clean = _safe_id(value)
        if clean:
            event[key] = clean
    if summary_status:
        event['summary_status'] = summary_status
    if retry_kind:
        event['retry_kind'] = retry_kind
    if feedback_outcome:
        event['feedback_outcome'] = feedback_outcome
    if result_reached is not None:
        event['result_reached'] = bool(result_reached)
    if continued is not None:
        event['continued'] = bool(continued)
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
    event = build_event(event_name, now_fn=now_fn, environ=environ, **fields)
    if path is None and event_store.enabled(environ):
        try:
            return event_store.record_event('gameplay', event, retention_days=POSTGRES_RETENTION_DAYS)
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
        status = event_store.storage_status('gameplay')
        status['retention'] = {'mode': 'age', 'days': POSTGRES_RETENTION_DAYS}
        return status
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
        'retention': {'mode': 'size_rotation', 'max_bytes_per_generation': _MAX_LOG_BYTES, 'generations': 2},
    }


def _rate(numerator, denominator):
    return round(numerator / denominator * 100, 1) if denominator else None


def begin_summary(session, *, retry_kind='new'):
    if retry_kind not in ALLOWED_RETRY_KINDS - {''}:
        raise ValueError('unknown gameplay retry kind')
    session[SUMMARY_SESSION_KEY] = {
        'retry_kind': retry_kind,
        'answered_count': 0,
        'result_reached': False,
        'result_id': None,
        'continued': False,
        'feedback_outcome': '',
        'correction_count': 0,
        'work_impressions': 0,
        'work_clicks': 0,
        'question_repeats': 0,
    }
    return session[SUMMARY_SESSION_KEY]


def update_summary(session, event_name, **fields):
    state = session.get(SUMMARY_SESSION_KEY)
    if not isinstance(state, dict):
        retry_kinds = {
            'diagnosis_started': 'new',
            'retry_started': 'retry',
            'exclude_retry_started': 'exclude_retry',
            'resume_started': 'resume',
        }
        retry_kind = retry_kinds.get(event_name)
        if not retry_kind:
            return None
        state = begin_summary(session, retry_kind=retry_kind)
    if event_name == 'result_shown':
        state['result_reached'] = True
        state['result_id'] = _bounded_int(fields.get('result_id'), maximum=1000000000)
    if event_name == 'continue_started':
        state['continued'] = True
    if event_name == 'feedback_completed':
        outcome = str(fields.get('outcome') or '')
        state['feedback_outcome'] = outcome if outcome in {'yes', 'maybe', 'no'} else 'yes'
        state['correction_count'] = _bounded_int(fields.get('correction_count'), maximum=100) or 0
    if event_name == 'work_impression':
        state['work_impressions'] = int(state.get('work_impressions', 0)) + 1
    if event_name == 'work_click':
        state['work_clicks'] = int(state.get('work_clicks', 0)) + 1
    if event_name == 'question_repeated':
        state['question_repeats'] = int(state.get('question_repeats', 0)) + 1
    answered_count = _bounded_int(fields.get('answered_count'), maximum=1000)
    if answered_count is not None:
        state['answered_count'] = max(int(state.get('answered_count', 0)), answered_count)
    session[SUMMARY_SESSION_KEY] = state
    return state


def finalize_summary(session, status, recorder):
    state = session.get(SUMMARY_SESSION_KEY)
    if not isinstance(state, dict):
        return None
    if state.get('result_reached') and status == 'abandoned':
        status = 'completed'
    event = recorder(
        'diagnosis_summary',
        summary_status=status,
        retry_kind=state.get('retry_kind', ''),
        feedback_outcome=state.get('feedback_outcome', ''),
        result_reached=bool(state.get('result_reached')),
        result_id=state.get('result_id'),
        answered_count=state.get('answered_count', 0),
        continued=bool(state.get('continued')),
        correction_count=state.get('correction_count', 0),
        work_impressions=state.get('work_impressions', 0),
        work_clicks=state.get('work_clicks', 0),
        question_repeats=state.get('question_repeats', 0),
    )
    if event:
        session.pop(SUMMARY_SESSION_KEY, None)
    return event


def _summary_metrics(summaries):
    summary_count = len(summaries)
    results = sum(bool(event.get('result_reached')) for event in summaries)
    feedback = sum(bool(event.get('feedback_outcome')) for event in summaries)
    impressions = sum(int(event.get('work_impressions') or 0) for event in summaries)
    clicks = sum(int(event.get('work_clicks') or 0) for event in summaries)
    answered = sum(int(event.get('answered_count') or 0) for event in summaries)
    repeats = sum(int(event.get('question_repeats') or 0) for event in summaries)
    return {
        'summary_total': summary_count,
        'result_reach_rate': _rate(results, summary_count),
        'retry_rate': _rate(sum(event.get('retry_kind') == 'retry' for event in summaries), summary_count),
        'exclude_retry_rate': _rate(
            sum(event.get('retry_kind') == 'exclude_retry' for event in summaries), summary_count
        ),
        'continue_rate': _rate(sum(bool(event.get('continued')) for event in summaries), results),
        'feedback_completion_rate': _rate(feedback, results),
        'work_click_rate': _rate(clicks, impressions),
        'question_repeat_rate': _rate(repeats, answered),
    }


def _summary_invariants(summaries):
    results = sum(bool(event.get('result_reached')) for event in summaries)
    feedback = sum(bool(event.get('feedback_outcome')) for event in summaries)
    impressions = sum(int(event.get('work_impressions') or 0) for event in summaries)
    clicks = sum(int(event.get('work_clicks') or 0) for event in summaries)
    violations = []
    if feedback > results:
        violations.append('feedback_without_result')
    if clicks > impressions:
        violations.append('work_clicks_exceed_impressions')
    if any(int(event.get('correction_count') or 0) > 0 and not event.get('feedback_outcome') for event in summaries):
        violations.append('correction_without_feedback')
    if any(bool(event.get('continued')) and not bool(event.get('result_reached')) for event in summaries):
        violations.append('continue_without_result')
    if any(
        int(event.get('work_impressions') or 0) > 0 and not bool(event.get('result_reached')) for event in summaries
    ):
        violations.append('work_impression_without_result')
    return {'valid': not violations, 'violations': violations}


def event_report(*, events=None, path=None, environ=None, limit=5000, work_clicks=0, questions_shown=0):
    rows = list(events) if events is not None else read_events(path=path, environ=environ, limit=limit)
    versioned = [event for event in rows if event.get('schema_version') == SCHEMA_VERSION]
    legacy = [event for event in rows if event.get('schema_version') != SCHEMA_VERSION]
    summaries = [event for event in versioned if event.get('event_name') == 'diagnosis_summary']
    counts = Counter(str(event.get('event_name') or '') for event in versioned)
    legacy_counts = Counter(str(event.get('event_name') or '') for event in legacy)
    summary_count = len(summaries)
    release_names = sorted({str(event.get('release') or 'unknown') for event in summaries})
    by_release = {}
    for release in release_names:
        release_summaries = [event for event in summaries if str(event.get('release') or 'unknown') == release]
        by_release[release] = {
            **_summary_metrics(release_summaries),
            'invariants': _summary_invariants(release_summaries),
        }
    return {
        'total': len(rows),
        'storage': (
            storage_status(path=path, environ=environ)
            if events is None
            else {'storage': 'provided_events', 'retention': None}
        ),
        'schema_version': SCHEMA_VERSION,
        'versioned_total': len(versioned),
        'summary_total': summary_count,
        'by_event': dict(sorted(counts.items())),
        'metrics': _summary_metrics(summaries),
        'invariants': _summary_invariants(summaries),
        'by_release': by_release,
        'legacy': {
            'total': len(legacy),
            'by_event': dict(sorted(legacy_counts.items())),
            'metrics_trusted': False,
            'reason': 'events without schema_version=2 do not share a reliable diagnosis denominator',
        },
        'summaries': summaries,
        'recent': versioned[-20:],
    }


def summary_csv(report):
    fieldnames = [
        'timestamp',
        'schema_version',
        'release',
        'summary_status',
        'retry_kind',
        'answered_count',
        'result_reached',
        'result_id',
        'continued',
        'feedback_outcome',
        'correction_count',
        'work_impressions',
        'work_clicks',
        'question_repeats',
    ]
    return csv_text(report.get('summaries', []), fieldnames)
