import json
import os
import threading
from collections import Counter, defaultdict, deque
from datetime import datetime, timezone

from services.csv_safety import csv_text
from storage import data_path
from services import event_store


_ALLOWED_EVENTS = {
    'question_shown',
    'question_answered',
    'question_dropoff',
    'question_result_contribution',
}
_MAX_LOG_BYTES = 5 * 1024 * 1024
_LOCK = threading.Lock()


ANSWER_BUCKETS = {
    1.0: 'yes',
    0.5: 'yes',
    0.0: 'unknown',
    -0.5: 'no',
    -1.0: 'no',
}


def _now_iso(now_fn=None):
    now = now_fn() if now_fn else datetime.now(timezone.utc)
    if hasattr(now, 'astimezone'):
        now = now.astimezone(timezone.utc)
    return now.isoformat(timespec='seconds')


def _clean_text(value, limit):
    text = str(value or '').strip().replace('\r', ' ').replace('\n', ' ')
    return text[:limit]


def _clean_int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _clean_float(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def event_log_path(environ=None):
    environ = environ or os.environ
    return environ.get('QUESTION_EVENT_LOG_PATH') or data_path('question_events.jsonl')


def build_event(
    event_name,
    *,
    question_id=None,
    question_text='',
    category='',
    axis='',
    answer=None,
    result_name='',
    result_rank=None,
    answered_count=None,
    now_fn=None,
):
    event_name = _clean_text(event_name, 48)
    if event_name not in _ALLOWED_EVENTS:
        raise ValueError('unknown question event')
    event = {
        'timestamp': _now_iso(now_fn),
        'event_name': event_name,
    }
    q_id = _clean_int(question_id)
    if q_id is not None:
        event['question_id'] = q_id
    text = _clean_text(question_text, 120)
    if text:
        event['question_text'] = text
    category = _clean_text(category, 32)
    if category:
        event['category'] = category
    axis = _clean_text(axis, 32)
    if axis:
        event['axis'] = axis
    answer_value = _clean_float(answer)
    if answer_value is not None:
        event['answer'] = answer_value
        event['answer_bucket'] = ANSWER_BUCKETS.get(answer_value, 'unknown')
    result_name = _clean_text(result_name, 80)
    if result_name:
        event['result_name'] = result_name
    rank = _clean_int(result_rank)
    if rank is not None:
        event['result_rank'] = rank
    count = _clean_int(answered_count)
    if count is not None:
        event['answered_count'] = max(0, count)
    return event


def _append_event(event, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with _LOCK:
        if os.path.exists(path) and os.path.getsize(path) > _MAX_LOG_BYTES:
            os.replace(path, path + '.1')
        with open(path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(event, ensure_ascii=False, separators=(',', ':')) + '\n')


def record_event(event_name, *, path=None, environ=None, now_fn=None, **kwargs):
    event = build_event(event_name, now_fn=now_fn, **kwargs)
    if path is None and event_store.enabled(environ):
        try:
            return event_store.record_event('question', event)
        except Exception:
            pass
    _append_event(event, path or event_log_path(environ),)
    return event


def safe_record_event(event_name, *, path=None, environ=None, now_fn=None, **kwargs):
    try:
        return record_event(event_name, path=path, environ=environ, now_fn=now_fn, **kwargs)
    except Exception:
        return None


def storage_status(*, path=None, environ=None):
    if path is None and event_store.enabled(environ):
        return event_store.storage_status('question')
    target = os.path.abspath(path or event_log_path(environ))
    parent = os.path.dirname(target)
    exists = os.path.exists(target)
    parent_exists = os.path.isdir(parent)
    parent_writable = os.access(parent, os.W_OK) if parent_exists else False
    file_writable = os.access(target, os.W_OK) if exists else parent_writable
    return {
        'path': target,
        'parent': parent,
        'exists': exists,
        'parent_exists': parent_exists,
        'parent_writable': bool(parent_writable),
        'file_writable': bool(file_writable),
        'count': event_count(path=target),
    }


def event_count(*, path=None, environ=None):
    if path is None and event_store.enabled(environ):
        try:
            return event_store.event_count('question')
        except Exception:
            return 0
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


def read_events(*, path=None, environ=None, limit=5000):
    limit = max(1, min(int(limit or 5000), 50000))
    if path is None and event_store.enabled(environ):
        try:
            return [event for event in event_store.read_events('question', limit=limit) if event.get('event_name') in _ALLOWED_EVENTS]
        except Exception:
            return []
    path = path or event_log_path(environ)
    rows = deque(maxlen=limit)
    try:
        with open(path, encoding='utf-8') as f:
            for line in f:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict) and row.get('event_name') in _ALLOWED_EVENTS:
                    rows.append(row)
    except OSError:
        return []
    return list(rows)


def _question_meta(engine, question_id, event=None):
    event = event or {}
    question = {}
    if question_id is not None and 0 <= question_id < len(getattr(engine, 'questions', [])):
        question = engine.questions[question_id]
    text = event.get('question_text') or question.get('text', '')
    category = event.get('category') or question.get('category', '') or 'uncategorized'
    axis = event.get('axis') or question.get('axis', '') or ''
    return text, category, axis


def event_report(engine, *, path=None, environ=None, limit=5000):
    events = read_events(path=path, environ=environ, limit=limit)
    rows = {}
    category = defaultdict(lambda: Counter({'shown': 0, 'answered': 0, 'yes': 0, 'no': 0, 'unknown': 0, 'dropoff': 0}))
    contribution = defaultdict(lambda: Counter())
    totals = Counter()

    def ensure_row(question_id, event=None):
        question_id = _clean_int(question_id)
        if question_id is None:
            return None
        if question_id not in rows:
            text, cat, axis = _question_meta(engine, question_id, event)
            rows[question_id] = Counter({
                'question_id': question_id,
                'shown': 0,
                'answered': 0,
                'yes': 0,
                'no': 0,
                'unknown': 0,
                'dropoff': 0,
                'contribution': 0,
            })
            rows[question_id]['question_text'] = text
            rows[question_id]['category'] = cat
            rows[question_id]['axis'] = axis
        return rows[question_id]

    for event in events:
        event_name = event.get('event_name')
        q_id = _clean_int(event.get('question_id'))
        row = ensure_row(q_id, event)
        totals[event_name] += 1
        if row is None:
            continue
        cat = row.get('category') or 'uncategorized'
        if event_name == 'question_shown':
            row['shown'] += 1
            category[cat]['shown'] += 1
        elif event_name == 'question_answered':
            bucket = event.get('answer_bucket') or ANSWER_BUCKETS.get(_clean_float(event.get('answer')), 'unknown')
            if bucket not in ('yes', 'no', 'unknown'):
                bucket = 'unknown'
            row['answered'] += 1
            row[bucket] += 1
            category[cat]['answered'] += 1
            category[cat][bucket] += 1
        elif event_name == 'question_dropoff':
            row['dropoff'] += 1
            category[cat]['dropoff'] += 1
        elif event_name == 'question_result_contribution':
            row['contribution'] += 1
            result_name = event.get('result_name') or '(unknown)'
            contribution[q_id][result_name] += 1

    question_rows = []
    for row in rows.values():
        shown = int(row.get('shown', 0))
        answered = int(row.get('answered', 0))
        dropoff = int(row.get('dropoff', 0))
        question_rows.append({
            'question_id': row['question_id'],
            'question_text': row.get('question_text', ''),
            'category': row.get('category', 'uncategorized'),
            'axis': row.get('axis', ''),
            'shown': shown,
            'answered': answered,
            'yes': int(row.get('yes', 0)),
            'no': int(row.get('no', 0)),
            'unknown': int(row.get('unknown', 0)),
            'dropoff': dropoff,
            'contribution': int(row.get('contribution', 0)),
            'yes_rate': round(row.get('yes', 0) / answered * 100, 1) if answered else 0,
            'no_rate': round(row.get('no', 0) / answered * 100, 1) if answered else 0,
            'unknown_rate': round(row.get('unknown', 0) / answered * 100, 1) if answered else 0,
            'unanswered_rate': round(max(shown - answered, 0) / shown * 100, 1) if shown else 0,
            'dropoff_rate': round(dropoff / shown * 100, 1) if shown else 0,
            'top_results': [
                {'result_name': name, 'count': count}
                for name, count in contribution[row['question_id']].most_common(3)
            ],
        })

    total_shown = sum(row['shown'] for row in question_rows)
    category_rows = []
    for cat, counts in category.items():
        shown = counts['shown']
        answered = counts['answered']
        category_rows.append({
            'category': cat,
            'shown': shown,
            'answered': answered,
            'yes': counts['yes'],
            'no': counts['no'],
            'unknown': counts['unknown'],
            'dropoff': counts['dropoff'],
            'shown_share': round(shown / total_shown * 100, 1) if total_shown else 0,
            'yes_rate': round(counts['yes'] / answered * 100, 1) if answered else 0,
            'dropoff_rate': round(counts['dropoff'] / shown * 100, 1) if shown else 0,
        })

    relation_attachment_shown = sum(row['shown'] for row in category_rows if row['category'] in ('relation', 'attachment'))
    relation_attachment_share = round(relation_attachment_shown / total_shown * 100, 1) if total_shown else 0
    warnings = []
    if total_shown >= 10 and relation_attachment_share >= 55:
        warnings.append({
            'type': 'relation_attachment_bias',
            'message': f'relation/attachment の表示比率が {relation_attachment_share}% です。序盤質問の偏りを確認してください。',
        })

    contribution_rows = sorted(
        [row for row in question_rows if row['contribution'] > 0],
        key=lambda row: (-row['contribution'], -row['shown'], row['question_id']),
    )
    question_rows = sorted(question_rows, key=lambda row: (-row['shown'], -row['answered'], row['question_id']))
    dropoff_rows = sorted(question_rows, key=lambda row: (-row['dropoff_rate'], -row['dropoff'], row['question_id']))
    category_rows = sorted(category_rows, key=lambda row: (-row['shown'], row['category']))

    return {
        'total': len(events),
        'metrics': {
            'shown': totals['question_shown'],
            'answered': totals['question_answered'],
            'dropoffs': totals['question_dropoff'],
            'contributions': totals['question_result_contribution'],
            'relation_attachment_share': relation_attachment_share,
        },
        'questions': question_rows,
        'dropoff_ranking': dropoff_rows,
        'categories': category_rows,
        'contribution_ranking': contribution_rows,
        'warnings': warnings,
    }


def question_csv(report):
    fieldnames = [
        'question_id', 'category', 'axis', 'shown', 'answered', 'yes', 'no', 'unknown',
        'yes_rate', 'no_rate', 'unknown_rate', 'unanswered_rate', 'dropoff',
        'dropoff_rate', 'contribution', 'question_text',
    ]
    return csv_text(report.get('questions', []), fieldnames)


def category_csv(report):
    fieldnames = ['category', 'shown', 'shown_share', 'answered', 'yes', 'no', 'unknown', 'yes_rate', 'dropoff', 'dropoff_rate']
    return csv_text(report.get('categories', []), fieldnames)
