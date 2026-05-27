import json
import math
import os
import threading
from collections import Counter, deque
from datetime import datetime, timezone

from storage import data_path
from services import event_store


_LOCK = threading.Lock()
_MAX_LOG_BYTES = 5 * 1024 * 1024
HEAVY_RESULT_NAMES = {'共依存', '激重感情', '共生関係', '執着'}
MAIN_WINDOW = 300
SHORT_WINDOW = 100
MIN_SAMPLES = 50
CANDIDATE_POOL = 12
SMOOTHING = 2.0
MIN_FACTOR = 0.7
MAX_FACTOR = 1.25
HEAVY_FACTOR_CAP = 0.75
DOMINANT_RATIO = 1.8
DOMINANT_MIN_FACTOR = 0.85


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


def build_event(fetish_id, fetish_name='', probability=None, *, rank=1, now_fn=None):
    event = {
        'timestamp': _now_iso(now_fn),
        'event_name': 'result_exposed',
        'rank': max(1, _clean_int(rank) or 1),
    }
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


def record_result(fetish_id, fetish_name='', probability=None, *, rank=1, path=None, environ=None, now_fn=None):
    event = build_event(fetish_id, fetish_name, probability, rank=rank, now_fn=now_fn)
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


def adjust_ranked(engine, probs, ranked, *, events=None, path=None, environ=None):
    ranked = list(ranked)
    if len(ranked) < 2:
        return ranked
    factors = exposure_factors(engine.fetishes, events=events, path=path, environ=environ)
    pool = ranked[:CANDIDATE_POOL]
    rest = ranked[CANDIDATE_POOL:]
    original_top = ranked[0]
    top_score = probs[ranked[0]]
    second_score = max(probs[ranked[1]], 1e-12)
    adjusted = []
    for index in pool:
        fetish_id = engine.fetishes[index].get('id')
        factor = factors.get(fetish_id, 1.0)
        if index == original_top and top_score / second_score >= DOMINANT_RATIO:
            factor = max(factor, DOMINANT_MIN_FACTOR)
        adjusted.append((probs[index] * factor, index))
    adjusted.sort(key=lambda item: item[0], reverse=True)
    return [index for _score, index in adjusted] + rest


def make_rank_adjuster(engine):
    return lambda probs, ranked: adjust_ranked(engine, probs, ranked)
