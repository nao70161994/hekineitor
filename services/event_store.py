import json

from storage import get_conn, put_conn, use_db

TABLE_NAME = 'analytics_events'


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


def record_event(event_type, event, *, get_conn_fn=get_conn, put_conn_fn=put_conn):
    conn = get_conn_fn()
    try:
        with conn:
            ensure_schema(conn)
            cur = conn.cursor()
            cur.execute(
                'INSERT INTO analytics_events (event_type, timestamp, payload) VALUES (%s, %s, %s)',
                (
                    str(event_type),
                    str(event.get('timestamp') or ''),
                    json.dumps(event, ensure_ascii=False, separators=(',', ':')),
                ),
            )
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
    }
