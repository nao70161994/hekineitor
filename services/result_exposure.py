import json
import math
import os
import random
import threading
from collections import Counter, deque
from datetime import datetime, timedelta, timezone

from storage import data_path
from services import event_store


_LOCK = threading.Lock()
_MAX_LOG_BYTES = 5 * 1024 * 1024
HEAVY_RESULT_NAMES = {'共依存', '激重感情', '共生関係', '執着'}
BACKFILL_SOURCE = 'stats_history_backfill'
BACKFILL_CONFIRM_TEXT = 'BACKFILL_RESULT_EXPOSURES'
MAIN_WINDOW = 1000
SHORT_WINDOW = 300
MIN_SAMPLES = 50
CANDIDATE_POOL = 12
LOW_EXPOSURE_POOL = 30
SMOOTHING = 2.0
MIN_FACTOR = 0.5
MAX_FACTOR = 1.6
HEAVY_FACTOR_CAP = 0.55
DOMINANT_RATIO = None
DOMINANT_MIN_FACTOR = None


def event_log_path(environ=None):
    environ = environ or os.environ
    return environ.get('RESULT_EXPOSURE_LOG_PATH') or data_path('result_exposures.jsonl')


def _now_iso(now_fn=None):
    now = now_fn() if now_fn else datetime.now(timezone.utc)
    if hasattr(now, 'astimezone'):
        now = now.astimezone(timezone.utc)
    return now.isoformat(timespec='seconds')


def _clean_text(value, max_len=80):
    return str(value or '').strip().replace('\r', ' ').replace('\n', ' ')[:max_len]


def _clean_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _clean_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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


def build_event(fetish_id, fetish_name='', probability=None, *, rank=1, source=None, now_fn=None):
    event = {
        'timestamp': _now_iso(now_fn),
        'event_name': 'result_exposed',
        'rank': max(1, _clean_int(rank) or 1),
    }
    clean_source = _clean_text(source, 40)
    if clean_source:
        event['source'] = clean_source
    clean_id = _clean_int(fetish_id)
    if clean_id is not None:
        event['fetish_id'] = clean_id
    name = _clean_text(fetish_name, 80)
    if name:
        event['fetish_name'] = name
    prob = _clean_float(probability)
    if prob is not None:
        event['probability'] = round(prob, 4)
    return event


def record_result(fetish_id, fetish_name='', probability=None, *, rank=1, source=None, path=None, environ=None, now_fn=None):
    event = build_event(fetish_id, fetish_name, probability, rank=rank, source=source, now_fn=now_fn)
    if path is None and event_store.enabled(environ):
        try:
            return event_store.record_event('result_exposure', event)
        except Exception:
            pass
    target = path or event_log_path(environ)
    os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)
    line = json.dumps(event, ensure_ascii=False, separators=(',', ':')) + '\n'
    with _LOCK:
        _rotate_if_needed(target)
        with open(target, 'a', encoding='utf-8') as file_obj:
            file_obj.write(line)
    return event


def safe_record_result(*args, **kwargs):
    try:
        return record_result(*args, **kwargs)
    except Exception:
        return None


def read_events(*, path=None, environ=None, limit=MAIN_WINDOW):
    if path is None and event_store.enabled(environ):
        try:
            return [event for event in event_store.read_events('result_exposure', limit=limit) if event.get('event_name') == 'result_exposed']
        except Exception:
            return []
    target = path or event_log_path(environ)
    try:
        max_lines = min(max(1, int(limit or MAIN_WINDOW)), 5000)
    except (TypeError, ValueError):
        max_lines = MAIN_WINDOW
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
        if isinstance(event, dict) and event.get('event_name') == 'result_exposed':
            events.append(event)
    return events



def _event_date(event):
    timestamp = str(event.get('timestamp') or '')
    return timestamp[:10] if len(timestamp) >= 10 else ''


def _date_window(*, days=None, date=None, until=None):
    end_date = str(date or until or '').strip()[:10]
    try:
        day_count = max(1, min(int(days or 0), 365))
    except (TypeError, ValueError):
        day_count = 0
    if not end_date and day_count <= 0:
        return None, None
    try:
        end = datetime.fromisoformat(end_date).date() if end_date else datetime.now(timezone.utc).date()
    except ValueError:
        return None, None
    start = end if day_count <= 1 else end - timedelta(days=day_count - 1)
    return start.isoformat(), end.isoformat()


def filter_events(events, *, days=None, date=None, until=None):
    start, end = _date_window(days=days, date=date, until=until)
    if not start or not end:
        return list(events)
    return [event for event in events if start <= _event_date(event) <= end]


def ranking_from_events(events, *, top_n=10, include_backfill=False):
    try:
        limit = max(1, min(int(top_n or 10), 100))
    except (TypeError, ValueError):
        limit = 10
    counts = Counter()
    names = {}
    for event in events:
        if int(event.get('rank') or 1) != 1:
            continue
        if not include_backfill and event.get('source') == BACKFILL_SOURCE:
            continue
        fetish_id = _clean_int(event.get('fetish_id'))
        name = _clean_text(event.get('fetish_name') or 'unknown', 80) or 'unknown'
        key = fetish_id if fetish_id is not None else name
        counts[key] += 1
        names[key] = name
    total = sum(counts.values())
    rows = []
    for key, count in counts.most_common(limit):
        row = {
            'fetish_name': names.get(key, 'unknown'),
            'count': count,
            'total': count,
            'guessed': count,
            'percent': round(count / total * 100, 1) if total else 0.0,
            'source': 'result_exposures',
        }
        if isinstance(key, int):
            row['fetish_id'] = key
        rows.append(row)
    return {'total': total, 'ranking': rows}


def ranking_report(*, path=None, environ=None, limit=5000, days=None, date=None, until=None, top_n=10, include_backfill=False):
    events = read_events(path=path, environ=environ, limit=limit)
    filtered = filter_events(events, days=days, date=date, until=until)
    report = ranking_from_events(filtered, top_n=top_n, include_backfill=include_backfill)
    report.update({
        'status': 'ok',
        'source': 'result_exposures',
        'days': days,
        'date': date or until,
    })
    return report




def _backfill_rows(fetishes, fetish_log, *, max_events=1000):
    try:
        limit = max(1, min(int(max_events or 1000), 5000))
    except (TypeError, ValueError):
        limit = 1000
    names = {fetish.get('id'): fetish.get('name', '') for fetish in fetishes if fetish.get('id') is not None}
    raw_rows = []
    for fetish_id, entry in (fetish_log or {}).items():
        clean_id = _clean_int(fetish_id)
        if clean_id is None or clean_id not in names:
            continue
        guessed = max(0, _clean_int((entry or {}).get('guessed')) or 0)
        if guessed <= 0:
            continue
        raw_rows.append({'fetish_id': clean_id, 'fetish_name': names[clean_id], 'raw_count': guessed})
    raw_total = sum(row['raw_count'] for row in raw_rows)
    if raw_total <= 0:
        return [], 0
    if raw_total <= limit:
        for row in raw_rows:
            row['backfill_count'] = row['raw_count']
        return sorted(raw_rows, key=lambda row: (-row['backfill_count'], row['fetish_id'])), raw_total

    allocated = []
    used = 0
    for row in raw_rows:
        quota = row['raw_count'] / raw_total * limit
        count = int(quota)
        used += count
        allocated.append({**row, 'backfill_count': count, '_remainder': quota - count})
    remaining = limit - used
    allocated.sort(key=lambda row: (-row['_remainder'], -row['raw_count'], row['fetish_id']))
    for row in allocated[:remaining]:
        row['backfill_count'] += 1
    for row in allocated:
        row.pop('_remainder', None)
    return sorted([row for row in allocated if row['backfill_count'] > 0], key=lambda row: (-row['backfill_count'], row['fetish_id'])), raw_total


def backfill_from_fetish_log(
    fetishes,
    fetish_log,
    *,
    path=None,
    environ=None,
    max_events=1000,
    apply=False,
    force=False,
    seed=20260528,
):
    existing = read_events(path=path, environ=environ, limit=50000)
    existing_backfill = sum(1 for event in existing if event.get('source') == BACKFILL_SOURCE)
    rows, raw_total = _backfill_rows(fetishes, fetish_log, max_events=max_events)
    planned_total = sum(row['backfill_count'] for row in rows)
    report = {
        'status': 'ok',
        'mode': 'applied' if apply else 'dry_run',
        'source': BACKFILL_SOURCE,
        'required_confirm_text': BACKFILL_CONFIRM_TEXT,
        'raw_total': raw_total,
        'planned_total': planned_total,
        'existing_backfill_count': existing_backfill,
        'inserted_count': 0,
        'skipped': False,
        'candidates': rows[:50],
    }
    if existing_backfill and not force:
        report['skipped'] = True
        report['skip_reason'] = 'already_backfilled'
        return report
    if not apply or not rows:
        return report

    events = []
    for row in rows:
        for _ in range(row['backfill_count']):
            events.append((row['fetish_id'], row['fetish_name']))
    random.Random(seed).shuffle(events)
    for fetish_id, name in events:
        record_result(fetish_id, name, None, rank=1, source=BACKFILL_SOURCE, path=path, environ=environ)
    report['inserted_count'] = len(events)
    report['skipped'] = False
    return report

def storage_status(*, path=None, environ=None):
    if path is None and event_store.enabled(environ):
        return event_store.storage_status('result_exposure')
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
    return len(read_events(path=path, environ=environ, limit=5000))


def _counts(events):
    counter = Counter()
    for event in events:
        if int(event.get('rank') or 1) != 1:
            continue
        fetish_id = _clean_int(event.get('fetish_id'))
        if fetish_id is not None:
            counter[fetish_id] += 1
    return counter


def exposure_factors(fetishes, *, events=None, path=None, environ=None):
    events = list(events) if events is not None else read_events(path=path, environ=environ, limit=MAIN_WINDOW)
    main_events = events[-MAIN_WINDOW:]
    main_total = len(main_events)
    ids = [fetish.get('id') for fetish in fetishes if fetish.get('id') is not None]
    if main_total < MIN_SAMPLES or not ids:
        return {fetish_id: 1.0 for fetish_id in ids}

    main_counts = _counts(main_events)
    expected = main_total / max(len(ids), 1) + SMOOTHING
    factors = {}
    for fetish in fetishes:
        fetish_id = fetish.get('id')
        actual = main_counts.get(fetish_id, 0) + SMOOTHING
        factor = math.sqrt(expected / actual)
        factor = max(MIN_FACTOR, min(MAX_FACTOR, factor))
        if fetish.get('name') in HEAVY_RESULT_NAMES:
            factor = min(factor, HEAVY_FACTOR_CAP)
        factors[fetish_id] = factor

    short_events = main_events[-SHORT_WINDOW:]
    short_total = len(short_events)
    if short_total >= MIN_SAMPLES:
        short_counts = _counts(short_events)
        for fetish in fetishes:
            fetish_id = fetish.get('id')
            rate = short_counts.get(fetish_id, 0) / short_total
            guard = 1.0
            if rate >= 0.40:
                guard = 0.45
            elif rate >= 0.25:
                guard = 0.60
            elif rate >= 0.15:
                guard = 0.75
            factors[fetish_id] = max(MIN_FACTOR, factors[fetish_id] * guard)
    return factors


def _adjustment_pool(engine, ranked, factors):
    primary = list(ranked[:CANDIDATE_POOL])
    pool = list(primary)
    seen = set(pool)
    for index in ranked[CANDIDATE_POOL:LOW_EXPOSURE_POOL]:
        fetish_id = engine.fetishes[index].get('id')
        if factors.get(fetish_id, 1.0) <= 1.0:
            continue
        if index not in seen:
            pool.append(index)
            seen.add(index)
    return pool


def adjust_ranked(engine, probs, ranked, *, events=None, path=None, environ=None):
    ranked = list(ranked)
    if len(ranked) < 2:
        return ranked
    factors = exposure_factors(engine.fetishes, events=events, path=path, environ=environ)
    pool = _adjustment_pool(engine, ranked, factors)
    pool_set = set(pool)
    rest = [index for index in ranked if index not in pool_set]
    original_top = ranked[0]
    top_score = probs[ranked[0]]
    second_score = max(probs[ranked[1]], 1e-12)
    adjusted = []
    for index in pool:
        fetish_id = engine.fetishes[index].get('id')
        factor = factors.get(fetish_id, 1.0)
        if (
            DOMINANT_RATIO is not None
            and DOMINANT_MIN_FACTOR is not None
            and index == original_top
            and top_score / second_score >= DOMINANT_RATIO
        ):
            factor = max(factor, DOMINANT_MIN_FACTOR)
        adjusted.append((probs[index] * factor, index))
    adjusted.sort(key=lambda item: item[0], reverse=True)
    return [index for _score, index in adjusted] + rest



def factor_report(fetishes, *, events=None, path=None, environ=None, limit=5000, top_n=30):
    try:
        row_limit = max(1, min(int(limit or 5000), 50000))
    except (TypeError, ValueError):
        row_limit = 5000
    try:
        display_limit = max(1, min(int(top_n or 30), 200))
    except (TypeError, ValueError):
        display_limit = 30
    events = list(events) if events is not None else read_events(path=path, environ=environ, limit=row_limit)
    main_events = events[-MAIN_WINDOW:]
    short_events = main_events[-SHORT_WINDOW:]
    main_counts = _counts(main_events)
    short_counts = _counts(short_events)
    factors = exposure_factors(fetishes, events=events)
    rows = []
    for fetish in fetishes:
        fetish_id = fetish.get('id')
        if fetish_id is None:
            continue
        main_count = main_counts.get(fetish_id, 0)
        short_count = short_counts.get(fetish_id, 0)
        rows.append({
            'fetish_id': fetish_id,
            'fetish_name': fetish.get('name', ''),
            'factor': round(float(factors.get(fetish_id, 1.0)), 4),
            'main_count': main_count,
            'main_share': round(main_count / len(main_events) * 100, 1) if main_events else 0.0,
            'short_count': short_count,
            'short_share': round(short_count / len(short_events) * 100, 1) if short_events else 0.0,
            'heavy_result': fetish.get('name') in HEAVY_RESULT_NAMES,
        })
    rows_by_factor = sorted(rows, key=lambda row: (row['factor'], -row['main_count'], row['fetish_id']))
    rows_by_boost = sorted(rows, key=lambda row: (-row['factor'], row['main_count'], row['fetish_id']))
    return {
        'status': 'ok',
        'source': 'result_exposures',
        'sample': {
            'events_loaded': len(events),
            'main_window': MAIN_WINDOW,
            'main_total': len(main_events),
            'short_window': SHORT_WINDOW,
            'short_total': len(short_events),
            'min_samples': MIN_SAMPLES,
            'active': len(main_events) >= MIN_SAMPLES,
        },
        'config': {
            'min_factor': MIN_FACTOR,
            'max_factor': MAX_FACTOR,
            'heavy_factor_cap': HEAVY_FACTOR_CAP,
            'candidate_pool': CANDIDATE_POOL,
            'low_exposure_pool': LOW_EXPOSURE_POOL,
            'smoothing': SMOOTHING,
        },
        'most_downweighted': rows_by_factor[:display_limit],
        'most_boosted': rows_by_boost[:display_limit],
        'heavy_results': [row for row in rows if row['heavy_result']],
    }

def make_rank_adjuster(engine):
    return lambda probs, ranked: adjust_ranked(engine, probs, ranked)
