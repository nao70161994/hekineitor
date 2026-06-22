import json
import math
import os
import random
import threading
from collections import Counter, deque
from datetime import datetime, timedelta, timezone

from storage import data_path, get_conn, put_conn
from services import event_store


_LOCK = threading.Lock()
_MAX_LOG_BYTES = 5 * 1024 * 1024
HEAVY_RESULT_NAMES = {'共依存', '激重感情', '共生関係', '執着'}
BACKFILL_SOURCE = 'stats_history_backfill'
BACKFILL_CONFIRM_TEXT = 'BACKFILL_RESULT_EXPOSURES'
MAIN_WINDOW = 1000
SHORT_WINDOW = 300
MIN_SAMPLES = 50
CANDIDATE_POOL = 20
LOW_EXPOSURE_RESCUE_LIMIT = 30
SMOOTHING = 2.0
MIN_FACTOR = 0.08
MAX_FACTOR = 3.0
DIVERSITY_ALPHA = 1.2
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


def _reassigned_event(event, old_id, new_id, fetish_name=''):
    if not isinstance(event, dict) or event.get('event_name') != 'result_exposed':
        return None
    if _clean_int(event.get('fetish_id')) != old_id:
        return None
    updated = dict(event)
    updated['fetish_id'] = new_id
    clean_name = _clean_text(fetish_name, 80)
    if clean_name:
        updated['fetish_name'] = clean_name
    return updated


def _reassign_postgres_events(old_id, new_id, fetish_name=''):
    conn = get_conn()
    try:
        with conn:
            event_store.ensure_schema(conn)
            cur = conn.cursor()
            cur.execute(
                'SELECT id, payload FROM analytics_events WHERE event_type = %s ORDER BY id ASC',
                ('result_exposure',),
            )
            rows = cur.fetchall()
            updated_count = 0
            for row_id, payload in rows:
                try:
                    event = payload if isinstance(payload, dict) else json.loads(payload)
                except (TypeError, json.JSONDecodeError):
                    continue
                updated = _reassigned_event(event, old_id, new_id, fetish_name=fetish_name)
                if updated is None:
                    continue
                cur.execute(
                    'UPDATE analytics_events SET payload = %s WHERE id = %s',
                    (json.dumps(updated, ensure_ascii=False, separators=(',', ':')), row_id),
                )
                updated_count += 1
            return updated_count
    finally:
        put_conn(conn)


def _reassign_jsonl_events(path, old_id, new_id, fetish_name=''):
    try:
        with open(path, encoding='utf-8') as file_obj:
            lines = file_obj.readlines()
    except OSError:
        return 0
    changed = False
    updated_count = 0
    output = []
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            output.append(line)
            continue
        updated = _reassigned_event(event, old_id, new_id, fetish_name=fetish_name)
        if updated is None:
            output.append(line)
            continue
        output.append(json.dumps(updated, ensure_ascii=False, separators=(',', ':')) + '\n')
        changed = True
        updated_count += 1
    if not changed:
        return 0
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with _LOCK:
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as file_obj:
            file_obj.writelines(output)
        os.replace(tmp, path)
    return updated_count


def reassign_fetish_id(old_id, new_id, *, fetish_name='', path=None, environ=None):
    old_id = _clean_int(old_id)
    new_id = _clean_int(new_id)
    if old_id is None or new_id is None or old_id == new_id:
        return {'status': 'skipped', 'updated_count': 0, 'reason': 'invalid_mapping'}
    if path is None and event_store.enabled(environ):
        updated_count = _reassign_postgres_events(old_id, new_id, fetish_name=fetish_name)
        return {'status': 'ok', 'storage': 'postgres', 'updated_count': updated_count}
    target = path or event_log_path(environ)
    updated_count = _reassign_jsonl_events(target, old_id, new_id, fetish_name=fetish_name)
    return {'status': 'ok', 'storage': 'jsonl', 'updated_count': updated_count}


def safe_reassign_fetish_id(*args, **kwargs):
    try:
        return reassign_fetish_id(*args, **kwargs)
    except Exception as exc:
        return {'status': 'error', 'updated_count': 0, 'error': exc.__class__.__name__}


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


def _fetish_name_map(fetish_names):
    if not fetish_names:
        return {}
    return {
        _clean_int(key): _clean_text(value, 80)
        for key, value in dict(fetish_names).items()
        if _clean_int(key) is not None and _clean_text(value, 80)
    }


def _unique_name_to_id(current_names):
    by_name = {}
    duplicates = set()
    for fetish_id, name in current_names.items():
        if name in by_name and by_name[name] != fetish_id:
            duplicates.add(name)
            continue
        by_name[name] = fetish_id
    for name in duplicates:
        by_name.pop(name, None)
    return by_name


def canonical_event_identity(event, current_names):
    fetish_id = _clean_int(event.get('fetish_id'))
    event_name = _clean_text(event.get('fetish_name') or 'unknown', 80) or 'unknown'
    if fetish_id is not None and fetish_id in current_names:
        return fetish_id, current_names[fetish_id]
    current_id = _unique_name_to_id(current_names).get(event_name)
    if current_id is not None:
        return current_id, current_names[current_id]
    if fetish_id is not None:
        return fetish_id, event_name
    return event_name, event_name


def ranking_from_events(events, *, top_n=10, include_backfill=False, fetish_names=None, include_secondary=False):
    try:
        limit = max(1, min(int(top_n or 10), 100))
    except (TypeError, ValueError):
        limit = 10
    counts = Counter()
    names = {}
    current_names = _fetish_name_map(fetish_names)
    for event in events:
        if not include_secondary and int(event.get('rank') or 1) != 1:
            continue
        if not include_backfill and event.get('source') == BACKFILL_SOURCE:
            continue
        key, name = canonical_event_identity(event, current_names)
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


def _safe_recent_event(event):
    row = {
        'timestamp': _clean_text(event.get('timestamp'), 40),
        'event_name': _clean_text(event.get('event_name') or 'result_exposed', 40),
        'rank': max(1, _clean_int(event.get('rank')) or 1),
    }
    fetish_id = _clean_int(event.get('fetish_id'))
    if fetish_id is not None:
        row['fetish_id'] = fetish_id
    name = _clean_text(event.get('fetish_name'), 80)
    if name:
        row['fetish_name'] = name
    source = _clean_text(event.get('source'), 40)
    if source:
        row['source'] = source
    probability = _clean_float(event.get('probability'))
    if probability is not None:
        row['probability'] = round(probability, 4)
    return row



def _normalized_event_name(event, current_names):
    _key, name = canonical_event_identity(event, current_names)
    return name


def heavy_result_trend_from_events(events, *, days=14, date=None, until=None, include_backfill=False, fetish_names=None, top_n=5):
    filtered = filter_events(events, days=days, date=date, until=until)
    current_names = _fetish_name_map(fetish_names)
    try:
        result_limit = max(1, min(int(top_n or 5), 20))
    except (TypeError, ValueError):
        result_limit = 5
    daily = {}
    for event in filtered:
        if int(event.get('rank') or 1) != 1:
            continue
        if not include_backfill and event.get('source') == BACKFILL_SOURCE:
            continue
        day = _event_date(event) or 'unknown'
        row = daily.setdefault(day, {'date': day, 'total': 0, 'heavy_total': 0, '_counts': Counter()})
        name = _normalized_event_name(event, current_names)
        row['total'] += 1
        row['_counts'][name] += 1
        if name in HEAVY_RESULT_NAMES:
            row['heavy_total'] += 1
    rows = []
    for day in sorted(daily):
        row = daily[day]
        total = row['total']
        top_results = []
        for name, count in row['_counts'].most_common(result_limit):
            top_results.append({
                'fetish_name': name,
                'count': count,
                'percent': round(count / total * 100, 1) if total else 0.0,
            })
        rows.append({
            'date': row['date'],
            'total': total,
            'heavy_total': row['heavy_total'],
            'heavy_result_ratio': round(row['heavy_total'] / total * 100, 1) if total else 0.0,
            'top_results': top_results,
        })
    return rows


def heavy_result_trend_report(*, path=None, environ=None, limit=5000, days=14, date=None, until=None, include_backfill=False, fetish_names=None, top_n=5):
    events = read_events(path=path, environ=environ, limit=limit)
    rows = heavy_result_trend_from_events(
        events,
        days=days,
        date=date,
        until=until,
        include_backfill=include_backfill,
        fetish_names=fetish_names,
        top_n=top_n,
    )
    return {
        'status': 'ok',
        'source': 'result_exposures',
        'days': days,
        'date': date or until,
        'include_backfill': include_backfill,
        'rows': rows,
    }


def recent_events_report(*, path=None, environ=None, limit=20, include_backfill=False):
    try:
        row_limit = max(1, min(int(limit or 20), 100))
    except (TypeError, ValueError):
        row_limit = 20
    events = read_events(path=path, environ=environ, limit=max(row_limit * 5, row_limit))
    if not include_backfill:
        events = [event for event in events if event.get('source') != BACKFILL_SOURCE]
    rows = [_safe_recent_event(event) for event in reversed(events[-row_limit:])]
    return {
        'status': 'ok',
        'source': 'result_exposures',
        'include_backfill': include_backfill,
        'limit': row_limit,
        'events': rows,
    }


def ranking_report(*, path=None, environ=None, limit=5000, days=None, date=None, until=None, top_n=10, include_backfill=False, fetish_names=None, include_secondary=False):
    events = read_events(path=path, environ=environ, limit=limit)
    filtered = filter_events(events, days=days, date=date, until=until)
    report = ranking_from_events(filtered, top_n=top_n, include_backfill=include_backfill, fetish_names=fetish_names, include_secondary=include_secondary)
    report.update({
        'status': 'ok',
        'source': 'result_exposures',
        'days': days,
        'date': date or until,
        'include_secondary': bool(include_secondary),
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


def _counts(events, current_names=None, *, include_secondary=True):
    current_names = current_names or {}
    counter = Counter()
    for event in events:
        if not include_secondary and int(event.get('rank') or 1) != 1:
            continue
        key, _name = canonical_event_identity(event, current_names)
        if isinstance(key, int):
            counter[key] += 1
    return counter


def _factor_floor(fetish):
    return MIN_FACTOR


def exposure_factors(fetishes, *, events=None, path=None, environ=None):
    events = list(events) if events is not None else read_events(path=path, environ=environ, limit=MAIN_WINDOW)
    main_events = events[-MAIN_WINDOW:]
    main_total = len(main_events)
    ids = [fetish.get('id') for fetish in fetishes if fetish.get('id') is not None]
    if not ids:
        return {}

    current_names = {fetish.get('id'): fetish.get('name', '') for fetish in fetishes if fetish.get('id') is not None}
    counts = _counts(main_events, current_names)
    expected = main_total / max(len(ids), 1)
    factors = {}
    for fetish in fetishes:
        fetish_id = fetish.get('id')
        actual = counts.get(fetish_id, 0)
        ratio = (actual + SMOOTHING) / (expected + SMOOTHING) if expected else 1.0
        factor = ratio ** (-DIVERSITY_ALPHA)
        factors[fetish_id] = max(MIN_FACTOR, min(MAX_FACTOR, factor))
    return factors


def _adjustment_pool(engine, ranked, factors, *, probs=None):
    primary = list(ranked[:CANDIDATE_POOL])
    pool = list(primary)
    seen = set(pool)
    rescue_candidates = []
    for index in ranked[CANDIDATE_POOL:]:
        fetish_id = engine.fetishes[index].get('id')
        factor = factors.get(fetish_id, 1.0)
        if factor <= 1.0:
            continue
        score = factor * float(probs[index]) if probs is not None else factor
        rescue_candidates.append((score, factor, index))
    rank_position = {index: position for position, index in enumerate(ranked)}
    rescue_candidates.sort(key=lambda item: (-item[0], -item[1], rank_position[item[2]]))
    for _score, _factor, index in rescue_candidates[:LOW_EXPOSURE_RESCUE_LIMIT]:
        if index not in seen:
            pool.append(index)
            seen.add(index)
    return pool


def _is_heavy_fetish(fetish):
    return fetish.get('name') in HEAVY_RESULT_NAMES


def adjust_ranked(engine, probs, ranked, *, events=None, path=None, environ=None):
    ranked = list(ranked)
    if len(ranked) < 2:
        return ranked
    exposure_events = list(events) if events is not None else read_events(path=path, environ=environ, limit=MAIN_WINDOW)
    factors = exposure_factors(engine.fetishes, events=exposure_events)
    original_top = ranked[0]
    top_score = probs[ranked[0]]
    second_score = max(probs[ranked[1]], 1e-12)
    pool = _adjustment_pool(engine, ranked, factors, probs=probs)
    pool_set = set(pool)
    rest = [index for index in ranked if index not in pool_set]
    adjusted = []
    for index in pool:
        fetish = engine.fetishes[index]
        fetish_id = fetish.get('id')
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
    current_names = {fetish.get('id'): fetish.get('name', '') for fetish in fetishes if fetish.get('id') is not None}
    main_counts = _counts(main_events, current_names)
    short_counts = _counts(short_events, current_names)
    expected = len(main_events) / max(len(current_names), 1) if current_names else 0.0
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
            'expected_per_result': round(expected, 4),
            'min_samples': MIN_SAMPLES,
            'active': len(main_events) > 0,
        },
        'config': {
            'min_factor': MIN_FACTOR,
            'max_factor': MAX_FACTOR,
            'diversity_alpha': DIVERSITY_ALPHA,
            'candidate_pool': CANDIDATE_POOL,
            'low_exposure_rescue_limit': LOW_EXPOSURE_RESCUE_LIMIT,
            'smoothing': SMOOTHING,
        },
        'most_downweighted': rows_by_factor[:display_limit],
        'most_boosted': rows_by_boost[:display_limit],
        'heavy_results': [row for row in rows if row['heavy_result']],
    }

def make_rank_adjuster(engine):
    return lambda probs, ranked: adjust_ranked(engine, probs, ranked)
