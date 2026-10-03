import json
import threading
from datetime import datetime, timedelta, timezone

from storage import get_conn, put_conn, use_db

TABLE_NAME = 'analytics_events'
POSTGRES_RETENTION_DAYS = 90
_RETENTION_LOCK = threading.Lock()
_LAST_RETENTION_PRUNE = {}


def enabled(environ=None):
    environ = environ or {}
    if environ.get('ANALYTICS_EVENT_STORAGE') == 'jsonl':
        return False
    return use_db()


def ensure_schema(conn):
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS analytics_events (
            id BIGSERIAL PRIMARY KEY,
            event_type TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            payload TEXT NOT NULL
        )
    """)
    cur.execute('CREATE INDEX IF NOT EXISTS idx_analytics_events_type_id ON analytics_events (event_type, id)')
    cur.execute(
        'CREATE INDEX IF NOT EXISTS idx_analytics_events_type_timestamp ON analytics_events (event_type, timestamp)'
    )
    cur.execute('CREATE INDEX IF NOT EXISTS idx_analytics_events_timestamp ON analytics_events (timestamp)')


def record_event(
    event_type,
    event,
    *,
    retention_days=None,
    now_fn=None,
    get_conn_fn=get_conn,
    put_conn_fn=put_conn,
):
    conn = get_conn_fn()
    pruned_on = None
    try:
        with conn:
            ensure_schema(conn)
            cur = conn.cursor()
            if retention_days is not None:
                retention_days = max(1, int(retention_days))
                now = now_fn() if now_fn else datetime.now(timezone.utc)
                prune_day = now.date().isoformat()
                retention_key = f'analytics_events:{retention_days}'
                pending_marker = f'pending:{prune_day}'
                with _RETENTION_LOCK:
                    if _LAST_RETENTION_PRUNE.get(retention_key) not in {prune_day, pending_marker}:
                        _LAST_RETENTION_PRUNE[retention_key] = pending_marker
                        pruned_on = prune_day
                        cutoff = (
                            (now - timedelta(days=retention_days))
                            .astimezone(timezone.utc)
                            .isoformat(timespec='seconds')
                        )
                        cur.execute(
                            'DELETE FROM analytics_events WHERE timestamp < %s',
                            (cutoff,),
                        )
            cur.execute(
                'INSERT INTO analytics_events (event_type, timestamp, payload) VALUES (%s, %s, %s)',
                (
                    str(event_type),
                    str(event.get('timestamp') or ''),
                    json.dumps(event, ensure_ascii=False, separators=(',', ':')),
                ),
            )
        if pruned_on:
            with _RETENTION_LOCK:
                _LAST_RETENTION_PRUNE[f'analytics_events:{retention_days}'] = pruned_on
    except BaseException:
        if pruned_on:
            with _RETENTION_LOCK:
                retention_key = f'analytics_events:{retention_days}'
                if _LAST_RETENTION_PRUNE.get(retention_key) == f'pending:{pruned_on}':
                    _LAST_RETENTION_PRUNE.pop(retention_key, None)
        raise
    finally:
        put_conn_fn(conn)
    return event


def read_events(event_type, *, limit=5000, get_conn_fn=get_conn, put_conn_fn=put_conn):
    try:
        max_rows = min(max(1, int(limit or 5000)), 50000)
    except (TypeError, ValueError):
        max_rows = 5000
    conn = get_conn_fn()
    try:
        with conn:
            ensure_schema(conn)
            cur = conn.cursor()
            cur.execute(
                'SELECT payload FROM analytics_events WHERE event_type = %s ORDER BY id DESC LIMIT %s',
                (str(event_type), max_rows),
            )
            rows = cur.fetchall()
    finally:
        put_conn_fn(conn)
    events = []
    for row in reversed(rows):
        payload = row[0]
        if isinstance(payload, dict):
            events.append(payload)
            continue
        try:
            event = json.loads(payload)
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def event_count(event_type, *, get_conn_fn=get_conn, put_conn_fn=put_conn):
    conn = get_conn_fn()
    try:
        with conn:
            ensure_schema(conn)
            cur = conn.cursor()
            cur.execute('SELECT COUNT(*) FROM analytics_events WHERE event_type = %s', (str(event_type),))
            row = cur.fetchone()
            return int(row[0] or 0) if row else 0
    finally:
        put_conn_fn(conn)


def storage_status(event_type, *, get_conn_fn=get_conn, put_conn_fn=put_conn):
    try:
        count = event_count(event_type, get_conn_fn=get_conn_fn, put_conn_fn=put_conn_fn)
        ok = True
    except Exception:
        count = 0
        ok = False
    return {
        'path': f'postgres:{TABLE_NAME}:{event_type}',
        'parent': f'postgres:{TABLE_NAME}',
        'exists': ok,
        'parent_exists': ok,
        'parent_writable': ok,
        'file_writable': ok,
        'storage': 'postgres',
        'count': count,
        'retention': {'mode': 'age', 'days': POSTGRES_RETENTION_DAYS},
    }
