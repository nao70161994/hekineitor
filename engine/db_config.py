"""Database and JSON-backed runtime configuration persistence."""

from contextlib import nullcontext


def load_config(defaults, *, use_db, get_conn, put_conn, config_path, read_json):
    values = dict(defaults)
    if use_db():
        conn = get_conn()
        try:
            cur = conn.cursor()
            cur.execute('SELECT key, value FROM config')
            for key, value in cur.fetchall():
                if key in values:
                    values[key] = float(value)
        except Exception:
            pass
        finally:
            put_conn(conn)
    else:
        stored = read_json(config_path, {})
        for key, value in stored.items():
            if key in values:
                values[key] = float(value)
    return values


def save_config_value(
    key,
    value,
    *,
    use_db,
    get_conn,
    put_conn,
    config_path,
    read_json,
    atomic_write,
    file_lock=None,
):
    if use_db():
        conn = get_conn()
        try:
            with conn:
                cur = conn.cursor()
                cur.execute(
                    'INSERT INTO config (key, value) VALUES (%s, %s) '
                    'ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value',
                    (key, str(value)),
                )
        finally:
            put_conn(conn)
    else:
        with file_lock(config_path) if file_lock else nullcontext():
            stored = read_json(config_path, {})
            stored[key] = value
            atomic_write(config_path, stored)
