import fcntl
import hashlib
import ipaddress
import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager

_LOCK = threading.RLock()
_LAST_CLEANUP = {}
_BUCKET_WINDOWS = {}
_SHARED_CLEANUP = {}
_SQLITE_SHARD_COUNT = 16
_SQLITE_ADMISSION_LOCKS = {}
_SQLITE_READY = set()


def _positive_int(value, default):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _trusted_networks(values):
    networks = []
    for value in values:
        try:
            networks.append(ipaddress.ip_network(value, strict=False))
        except ValueError:
            continue
    return networks


def client_ip(request, app_config, environ=os.environ):
    remote_addr = request.remote_addr or 'unknown'
    trusted = app_config.get('TRUSTED_PROXY_IPS')
    if trusted is None:
        trusted = environ.get('TRUSTED_PROXY_IPS', '')
    if isinstance(trusted, str):
        trusted = [item.strip() for item in trusted.split(',') if item.strip()]
    networks = _trusted_networks(trusted or [])
    try:
        remote_ip = ipaddress.ip_address(remote_addr)
    except ValueError:
        return remote_addr
    if not any(remote_ip in network for network in networks):
        return remote_addr
    forwarded = [item.strip() for item in request.headers.get('X-Forwarded-For', '').split(',') if item.strip()]
    for candidate in reversed(forwarded + [remote_addr]):
        try:
            address = ipaddress.ip_address(candidate)
        except ValueError:
            return remote_addr
        if any(address in network for network in networks):
            continue
        return str(address)
    return remote_addr


def _prune(timestamps, now, window_seconds):
    return [float(ts) for ts in timestamps if now - float(ts) < window_seconds]


def _should_cleanup(marker, now, interval=60):
    with _LOCK:
        if now - _SHARED_CLEANUP.get(marker, 0) < interval:
            return False
        _SHARED_CLEANUP[marker] = now
        return True


def _ensure_sqlite_schema(path):
    absolute = os.path.abspath(path)
    with _LOCK:
        if absolute in _SQLITE_READY:
            return
        os.makedirs(os.path.dirname(absolute), exist_ok=True)
        conn = sqlite3.connect(absolute, timeout=10)
        try:
            conn.execute(
                'CREATE TABLE IF NOT EXISTS rate_limits (scope TEXT NOT NULL, client_ip TEXT NOT NULL, timestamps TEXT NOT NULL, updated_at REAL NOT NULL, window_seconds INTEGER NOT NULL DEFAULT 60, PRIMARY KEY(scope, client_ip))'
            )
            columns = {row[1] for row in conn.execute('PRAGMA table_info(rate_limits)')}
            if 'window_seconds' not in columns:
                conn.execute('ALTER TABLE rate_limits ADD COLUMN window_seconds INTEGER NOT NULL DEFAULT 60')
            conn.execute('CREATE INDEX IF NOT EXISTS rate_limits_updated_at_idx ON rate_limits(updated_at)')
            conn.commit()
            _SQLITE_READY.add(absolute)
        finally:
            conn.close()


def _sqlite_shard_path(path, scope, ip, shard_count):
    if shard_count <= 1:
        return path
    digest = hashlib.sha256(f'{scope}\0{ip}'.encode('utf-8')).digest()
    shard = int.from_bytes(digest[:8], 'big') % shard_count
    return f'{path}.shard-{shard}'


@contextmanager
def _sqlite_admission_lock(base_path, scope):
    absolute = os.path.abspath(base_path)
    lock_key = (absolute, str(scope))
    with _LOCK:
        thread_lock = _SQLITE_ADMISSION_LOCKS.setdefault(lock_key, threading.RLock())
    with thread_lock:
        os.makedirs(os.path.dirname(absolute), exist_ok=True)
        suffix = hashlib.sha256(str(scope).encode('utf-8')).hexdigest()[:16]
        with open(f'{absolute}.admission-{suffix}.lock', 'a', encoding='utf-8') as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _sqlite_bucket(path, scope, ip, now, window_seconds, limit, max_buckets=None, *, allow_insert=True):
    _ensure_sqlite_schema(path)
    conn = sqlite3.connect(path, timeout=10)
    try:
        conn.execute('PRAGMA busy_timeout = 10000')
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT timestamps FROM rate_limits WHERE scope=? AND client_ip=?', (scope, ip)).fetchone()
        if row is None:
            if not allow_insert:
                conn.commit()
                return None
        try:
            timestamps = json.loads(row[0]) if row else []
        except (TypeError, json.JSONDecodeError):
            timestamps = []
        bucket = _prune(timestamps, now, window_seconds)
        limited = len(bucket) >= limit
        if not limited:
            bucket.append(now)
        last_accepted_at = max(bucket) if bucket else now
        conn.execute(
            'INSERT INTO rate_limits(scope,client_ip,timestamps,updated_at,window_seconds) VALUES(?,?,?,?,?) ON CONFLICT(scope,client_ip) DO UPDATE SET timestamps=excluded.timestamps,updated_at=excluded.updated_at,window_seconds=excluded.window_seconds',
            (scope, ip, json.dumps(bucket, separators=(',', ':')), last_accepted_at, window_seconds),
        )
        if _should_cleanup(('sqlite', os.path.abspath(path)), now):
            conn.execute('DELETE FROM rate_limits WHERE updated_at + window_seconds <= ?', (now,))
        conn.commit()
        return limited, bucket
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _sqlite_shared_bucket(base_path, scope, ip, now, window_seconds, limit, max_buckets):
    shard_count = _SQLITE_SHARD_COUNT
    home_path = _sqlite_shard_path(base_path, scope, ip, shard_count)
    existing = _sqlite_bucket(
        home_path,
        scope,
        ip,
        now,
        window_seconds,
        limit,
        allow_insert=False,
    )
    if existing is not None:
        return existing
    with _sqlite_admission_lock(base_path, scope):
        existing = _sqlite_bucket(
            home_path,
            scope,
            ip,
            now,
            window_seconds,
            limit,
            allow_insert=False,
        )
        if existing is not None:
            return existing
        total = 0
        for shard in range(shard_count):
            shard_path = f'{base_path}.shard-{shard}'
            _ensure_sqlite_schema(shard_path)
            conn = sqlite3.connect(shard_path, timeout=10)
            try:
                conn.execute('PRAGMA busy_timeout = 10000')
                conn.execute('BEGIN IMMEDIATE')
                conn.execute(
                    'DELETE FROM rate_limits WHERE scope=? AND updated_at + window_seconds <= ?',
                    (scope, now),
                )
                total += int(
                    conn.execute(
                        'SELECT COUNT(*) FROM rate_limits WHERE scope=?',
                        (scope,),
                    ).fetchone()[0]
                    or 0
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
        if total >= max_buckets:
            return True, [now]
        return _sqlite_bucket(
            home_path,
            scope,
            ip,
            now,
            window_seconds,
            limit,
            allow_insert=True,
        )


def _postgres_bucket(get_conn, put_conn, scope, ip, now, window_seconds, limit, max_buckets):
    conn = get_conn()
    try:
        with conn:
            cur = conn.cursor()
            lock_key = f'rate-limit:{scope}:{ip}'
            cur.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', (lock_key,))
            cur.execute('SELECT timestamps FROM rate_limits WHERE scope=%s AND client_ip=%s', (scope, ip))
            row = cur.fetchone()
            if row is None:
                cur.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', (f'rate-limit-capacity:{scope}',))
                cur.execute('SELECT timestamps FROM rate_limits WHERE scope=%s AND client_ip=%s', (scope, ip))
                row = cur.fetchone()
                if row is None:
                    cur.execute('SELECT COUNT(*) FROM rate_limits WHERE scope=%s', (scope,))
                    count = int(cur.fetchone()[0] or 0)
                    if count >= max_buckets:
                        cur.execute(
                            'DELETE FROM rate_limits WHERE scope=%s AND updated_at + window_seconds <= %s', (scope, now)
                        )
                        cur.execute('SELECT COUNT(*) FROM rate_limits WHERE scope=%s', (scope,))
                        count = int(cur.fetchone()[0] or 0)
                        if count >= max_buckets:
                            return True, [now]
            raw = row[0] if row else []
            if isinstance(raw, str):
                raw = json.loads(raw)
            bucket = _prune(raw or [], now, window_seconds)
            limited = len(bucket) >= limit
            if not limited:
                bucket.append(now)
            last_accepted_at = max(bucket) if bucket else now
            cur.execute(
                'INSERT INTO rate_limits(scope,client_ip,timestamps,updated_at,window_seconds) VALUES(%s,%s,%s::jsonb,%s,%s) ON CONFLICT(scope,client_ip) DO UPDATE SET timestamps=EXCLUDED.timestamps,updated_at=EXCLUDED.updated_at,window_seconds=EXCLUDED.window_seconds',
                (scope, ip, json.dumps(bucket, separators=(',', ':')), last_accepted_at, window_seconds),
            )
            if _should_cleanup(('postgres', id(get_conn)), now):
                cur.execute('DELETE FROM rate_limits WHERE updated_at + window_seconds <= %s', (now,))
            return limited, bucket
    finally:
        put_conn(conn)


def _memory_bucket(buckets, key, now, window_seconds, limit, cleanup_interval, max_buckets):
    with _LOCK:
        marker = id(buckets)
        cleanup_state = _LAST_CLEANUP.get(marker)
        last_cleanup = cleanup_state[1] if cleanup_state and cleanup_state[0] is buckets else 0
        if now - last_cleanup >= cleanup_interval:
            for existing_key, timestamps in list(buckets.items()):
                known_window = _BUCKET_WINDOWS.get((marker, existing_key))
                if known_window is None and existing_key[0] != key[0]:
                    continue
                fresh = _prune(timestamps, now, known_window or window_seconds)
                if fresh:
                    buckets[existing_key] = fresh
                else:
                    buckets.pop(existing_key, None)
                    _BUCKET_WINDOWS.pop((marker, existing_key), None)
            _LAST_CLEANUP[marker] = (buckets, now)
        bucket = _prune(buckets.get(key, []), now, window_seconds)
        if key not in buckets and sum(1 for existing_key in buckets if existing_key[0] == key[0]) >= max_buckets:
            return True, [now]
        limited = len(bucket) >= limit
        if not limited:
            bucket.append(now)
        buckets[key] = bucket
        _BUCKET_WINDOWS[(marker, key)] = window_seconds
        return limited, bucket


def rate_limit(
    scope,
    limit,
    request,
    app_config,
    buckets,
    jsonify,
    should_enforce_runtime_guard,
    *,
    window_seconds=60,
    environ=os.environ,
    time_fn=time.time,
    use_db=lambda: False,
    get_conn=None,
    put_conn=None,
    shared_path=None,
    logger=None,
):
    if not should_enforce_runtime_guard('rate_limit'):
        return None
    default_limit = _positive_int(limit, 1)
    default_window = _positive_int(window_seconds, 60)
    overrides = app_config.get('RATE_LIMIT_OVERRIDES') or {}
    if scope in overrides:
        try:
            configured_limit, configured_window = overrides[scope]
        except (TypeError, ValueError):
            configured_limit, configured_window = default_limit, default_window
    else:
        env_prefix = 'RATE_LIMIT_' + scope.upper()
        configured_limit = environ.get(env_prefix + '_LIMIT', default_limit)
        configured_window = environ.get(env_prefix + '_WINDOW', default_window)
    limit = _positive_int(configured_limit, default_limit)
    window_seconds = _positive_int(configured_window, default_window)
    cleanup_interval = _positive_int(environ.get('RATE_LIMIT_CLEANUP_INTERVAL', 60), 60)
    max_buckets = _positive_int(environ.get('RATE_LIMIT_MAX_BUCKETS', 10000), 10000)
    now = time_fn()
    ip = client_ip(request, app_config, environ)
    key = (scope, ip)
    if use_db() and get_conn and put_conn:
        limited, bucket = _postgres_bucket(get_conn, put_conn, scope, ip, now, window_seconds, limit, max_buckets)
    elif shared_path:
        try:
            limited, bucket = _sqlite_shared_bucket(shared_path, scope, ip, now, window_seconds, limit, max_buckets)
        except (sqlite3.Error, OSError):
            if logger is not None:
                logger.exception('Shared rate-limit storage failed')
            return (
                jsonify({'status': 'error', 'message': 'レート制限サービスを利用できません。'}),
                503,
                {'Retry-After': '5'},
            )
    else:
        limited, bucket = _memory_bucket(buckets, key, now, window_seconds, limit, cleanup_interval, max_buckets)
    if limited:
        retry_after = max(1, int(window_seconds - (now - bucket[0])))
        return (
            jsonify(
                {
                    'status': 'error',
                    'message': f'リクエストが多すぎます。{retry_after}秒後に再試行してください。',
                    'retry_after': retry_after,
                }
            ),
            429,
            {'Retry-After': str(retry_after)},
        )
    return None
