import copy
import fcntl
import hashlib
import json
import os
import random
import sqlite3
import time
import threading
import uuid

from flask.sessions import SessionInterface, SessionMixin
from werkzeug.datastructures import CallbackDict

from engine import _get_conn, _put_conn, _use_db
from services.app_meta import is_production_env
from storage import data_path


SESSION_TTL = 86400
LOCAL_SESSIONS = {}
_LOCAL_SESSIONS_LOCK = threading.RLock()
_SESSION_REQUEST_LOCKS = {}
_SESSION_REQUEST_LOCKS_GUARD = threading.RLock()
_SESSION_LOCK_DIR = os.path.join(os.environ.get('TMPDIR', '/tmp'), 'hekineitor-session-locks')
_SESSION_LOCK_LOCAL = threading.local()
_SESSION_SQLITE_READY = set()


def _use_sqlite_sessions():
    return not _use_db() and os.environ.get('SESSION_STORAGE', '').lower() != 'memory' and os.environ.get('APP_ENV', '').lower() != 'testing'


def _sqlite_session_path():
    return os.environ.get('SESSION_SQLITE_PATH') or data_path('sessions.sqlite3')


def _sqlite_session_conn():
    path = os.path.abspath(_sqlite_session_path())
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with _LOCAL_SESSIONS_LOCK:
        if path not in _SESSION_SQLITE_READY:
            setup = sqlite3.connect(path, timeout=10)
            try:
                setup.execute('CREATE TABLE IF NOT EXISTS sessions (session_id TEXT PRIMARY KEY, data TEXT NOT NULL, updated_at REAL NOT NULL)')
                setup.execute('CREATE INDEX IF NOT EXISTS sessions_updated_at_idx ON sessions(updated_at)')
                setup.commit()
                _SESSION_SQLITE_READY.add(path)
            finally:
                setup.close()
    conn = sqlite3.connect(path, timeout=10)
    conn.execute('PRAGMA busy_timeout = 10000')
    return conn


def _session_lock_path(sid):
    digest = hashlib.sha256(str(sid).encode('utf-8')).digest()
    return os.path.join(_SESSION_LOCK_DIR, f'{digest[0]:02x}', f'{digest[1]:02x}.lock')


def _advisory_lock_key(sid):
    value = int.from_bytes(hashlib.sha256(str(sid).encode('utf-8')).digest()[:8], 'big')
    return value - (1 << 64) if value >= (1 << 63) else value


def _reserve_local_lock(sid):
    with _SESSION_REQUEST_LOCKS_GUARD:
        entry = _SESSION_REQUEST_LOCKS.get(sid)
        if entry is None:
            entry = {'lock': threading.RLock(), 'users': 0}
            _SESSION_REQUEST_LOCKS[sid] = entry
        entry['users'] += 1
    entry['lock'].acquire()
    return entry


def _release_local_lock(sid, entry):
    entry['lock'].release()
    with _SESSION_REQUEST_LOCKS_GUARD:
        entry['users'] -= 1
        if entry['users'] == 0 and _SESSION_REQUEST_LOCKS.get(sid) is entry:
            _SESSION_REQUEST_LOCKS.pop(sid, None)


def _acquire_request_lock(sid, distributed_db=False, reentrant=True, reuse_existing=False):
    held = getattr(_SESSION_LOCK_LOCAL, 'held', None)
    if held is None:
        held = {}
        _SESSION_LOCK_LOCAL.held = held
    existing = held.get(sid)
    if existing and not existing['released']:
        if reuse_existing:
            return existing
        if not reentrant:
            raise RuntimeError('session lock is already held by this thread')
        existing['depth'] += 1
        return existing

    entry = _reserve_local_lock(sid)
    lock_file = None
    db_conn = None
    try:
        lock_path = _session_lock_path(sid)
        lock_dir = os.path.dirname(lock_path)
        os.makedirs(lock_dir, mode=0o700, exist_ok=True)
        lock_file = open(lock_path, 'a', encoding='utf-8')
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        advisory_key = None
        if distributed_db:
            advisory_key = _advisory_lock_key(sid)
            db_conn = _get_conn()
            cur = db_conn.cursor()
            cur.execute('SELECT pg_advisory_lock(%s)', (advisory_key,))
            db_conn.commit()
        handle = {
            'sid': sid,
            'entry': entry,
            'lock_file': lock_file,
            'db_conn': db_conn,
            'advisory_key': advisory_key,
            'depth': 1,
            'released': False,
        }
        held[sid] = handle
        return handle
    except BaseException:
        try:
            if db_conn is not None:
                try:
                    db_conn.close()
                except BaseException:
                    pass
                try:
                    _put_conn(db_conn)
                except BaseException:
                    pass
            if lock_file is not None:
                try:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                except BaseException:
                    pass
                try:
                    lock_file.close()
                except BaseException:
                    pass
        finally:
            _release_local_lock(sid, entry)
        raise


def _release_request_lock(handle):
    if not handle or handle.get('released'):
        return
    handle['depth'] -= 1
    if handle['depth'] > 0:
        return
    handle['released'] = True
    error = None
    conn = handle.get('db_conn')
    if conn is not None:
        try:
            cur = conn.cursor()
            cur.execute('SELECT pg_advisory_unlock(%s)', (handle['advisory_key'],))
            conn.commit()
        except BaseException as exc:
            error = exc
            try:
                conn.close()
            except BaseException:
                pass
        finally:
            try:
                _put_conn(conn)
            except BaseException as exc:
                error = error or exc
    lock_file = handle['lock_file']
    try:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        finally:
            lock_file.close()
    except BaseException as exc:
        error = error or exc
    finally:
        held = getattr(_SESSION_LOCK_LOCAL, 'held', {})
        held.pop(handle['sid'], None)
        _release_local_lock(handle['sid'], handle['entry'])
    if error is not None:
        raise error


def session_load(sid, use_sqlite=None, conn=None):
    use_sqlite = _use_sqlite_sessions() if use_sqlite is None else use_sqlite
    if _use_db():
        owned_conn = conn is None
        conn = conn or _get_conn()
        try:
            cur = conn.cursor()
            cur.execute('SELECT data, updated_at FROM sessions WHERE session_id = %s', (sid,))
            row = cur.fetchone()
            conn.commit()
            if row and time.time() - row[1] < SESSION_TTL:
                return json.loads(row[0])
        finally:
            if owned_conn:
                _put_conn(conn)
    elif use_sqlite:
        conn = _sqlite_session_conn()
        try:
            row = conn.execute('SELECT data, updated_at FROM sessions WHERE session_id=?', (sid,)).fetchone()
            if row and time.time() - row[1] < SESSION_TTL:
                return json.loads(row[0])
        finally:
            conn.close()
    else:
        with _LOCAL_SESSIONS_LOCK:
            entry = LOCAL_SESSIONS.get(sid)
            if entry and time.time() - entry[1] < SESSION_TTL:
                return copy.deepcopy(entry[0])
    return None


def _merge_value(current, updated, original):
    if isinstance(updated, dict) and isinstance(original, dict):
        merged = copy.deepcopy(current) if isinstance(current, dict) else {}
        for key in set(original) - set(updated):
            merged.pop(key, None)
        for key, value in updated.items():
            if key not in original:
                merged[key] = copy.deepcopy(value)
            elif value != original[key]:
                merged[key] = _merge_value(merged.get(key), value, original[key])
        return merged
    return copy.deepcopy(updated)


def _merge_session_data(current, data, original):
    if original is None:
        return copy.deepcopy(dict(data))
    return _merge_value(current or {}, dict(data), original)


def session_save(sid, data, original=None, use_sqlite=None, conn=None):
    use_sqlite = _use_sqlite_sessions() if use_sqlite is None else use_sqlite
    now = time.time()
    if _use_db():
        owned_conn = conn is None
        conn = conn or _get_conn()
        try:
            with conn:
                cur = conn.cursor()
                cur.execute('SELECT data FROM sessions WHERE session_id = %s FOR UPDATE', (sid,))
                row = cur.fetchone()
                current = json.loads(row[0]) if row else {}
                stored = _merge_session_data(current, data, original)
                cur.execute('''
                    INSERT INTO sessions (session_id, data, updated_at) VALUES (%s, %s, %s)
                    ON CONFLICT (session_id) DO UPDATE
                    SET data = EXCLUDED.data, updated_at = EXCLUDED.updated_at
                ''', (sid, json.dumps(stored, ensure_ascii=False), now))
                if random.random() < 0.01:
                    cur.execute('DELETE FROM sessions WHERE updated_at < %s', (now - SESSION_TTL,))
        finally:
            if owned_conn:
                _put_conn(conn)
    elif use_sqlite:
        conn = _sqlite_session_conn()
        try:
            with conn:
                conn.execute('INSERT INTO sessions(session_id,data,updated_at) VALUES(?,?,?) ON CONFLICT(session_id) DO UPDATE SET data=excluded.data,updated_at=excluded.updated_at', (sid, json.dumps(data, ensure_ascii=False), now))
                if random.random() < 0.01:
                    conn.execute('DELETE FROM sessions WHERE updated_at < ?', (now - SESSION_TTL,))
        finally:
            conn.close()
    else:
        with _LOCAL_SESSIONS_LOCK:
            current = LOCAL_SESSIONS.get(sid, ({}, 0))[0]
            LOCAL_SESSIONS[sid] = (_merge_session_data(current, data, original), now)
            if len(LOCAL_SESSIONS) > 2000:
                cutoff = now - SESSION_TTL
                for key in [key for key, value in LOCAL_SESSIONS.items() if value[1] < cutoff]:
                    del LOCAL_SESSIONS[key]


def cleanup_sessions(use_sqlite=None):
    use_sqlite = _use_sqlite_sessions() if use_sqlite is None else use_sqlite
    cutoff = time.time() - SESSION_TTL
    if _use_db():
        conn = _get_conn()
        try:
            with conn:
                cur = conn.cursor()
                cur.execute('DELETE FROM sessions WHERE updated_at < %s', (cutoff,))
                return cur.rowcount
        finally:
            _put_conn(conn)
    if use_sqlite:
        conn = _sqlite_session_conn()
        try:
            with conn:
                cursor = conn.execute('DELETE FROM sessions WHERE updated_at < ?', (cutoff,))
                return cursor.rowcount
        finally:
            conn.close()
    with _LOCAL_SESSIONS_LOCK:
        old = [key for key, value in LOCAL_SESSIONS.items() if value[1] < cutoff]
        for key in old:
            del LOCAL_SESSIONS[key]
        return len(old)


def local_session_count(use_sqlite=None):
    use_sqlite = _use_sqlite_sessions() if use_sqlite is None else use_sqlite
    if _use_db():
        return None
    if use_sqlite:
        conn = _sqlite_session_conn()
        try:
            return int(conn.execute('SELECT COUNT(*) FROM sessions').fetchone()[0])
        finally:
            conn.close()
    with _LOCAL_SESSIONS_LOCK:
        return len(LOCAL_SESSIONS)


class ServerSession(CallbackDict, SessionMixin):
    def __init__(self, initial=None, sid=None, is_new=False, request_lock=None, use_sqlite=False):
        def on_update(self):
            self.modified = True
        super().__init__(initial or {}, on_update)
        self.sid = sid
        self.is_new = is_new
        self.modified = False
        self.original = copy.deepcopy(dict(initial or {}))
        self.request_lock = request_lock
        self.use_sqlite = use_sqlite


class ServerSessionInterface(SessionInterface):
    _cookie = 'heki_sid'

    def open_session(self, app, request):
        use_sqlite = not app.config.get('TESTING') and _use_sqlite_sessions()
        raw_sid = request.cookies.get(self._cookie)
        try:
            sid = str(uuid.UUID(raw_sid)) if raw_sid else None
        except (ValueError, TypeError, AttributeError):
            sid = None
        if sid:
            request_lock = _acquire_request_lock(
                sid, distributed_db=_use_db(), reuse_existing=bool(app.config.get('TESTING')),
            )
            try:
                data = session_load(sid, use_sqlite=use_sqlite, conn=request_lock.get('db_conn'))
                if data is not None:
                    return ServerSession(data, sid=sid, request_lock=request_lock, use_sqlite=use_sqlite)
            except Exception:
                _release_request_lock(request_lock)
                raise
            _release_request_lock(request_lock)
        sid = str(uuid.uuid4())
        request_lock = _acquire_request_lock(
            sid, distributed_db=_use_db(), reuse_existing=bool(app.config.get('TESTING')),
        )
        return ServerSession(sid=sid, is_new=True, request_lock=request_lock, use_sqlite=use_sqlite)

    def save_session(self, app, session, response):
        try:
            if not session.modified and not session.is_new:
                return
            # The SID lock spans open_session through this save, so the state can
            # be replaced atomically without attempting to merge incompatible flows.
            request_lock = getattr(session, 'request_lock', None) or {}
            session_save(
                session.sid, dict(session), original=session.original,
                use_sqlite=getattr(session, 'use_sqlite', False), conn=request_lock.get('db_conn'),
            )
            secure = (
                os.environ.get('COOKIE_SECURE') == '1'
                or bool(os.environ.get('DATABASE_URL'))
                or is_production_env(os.environ)
            )
            response.set_cookie(
                self._cookie, session.sid,
                httponly=True, secure=secure, samesite='Lax',
                max_age=SESSION_TTL,
            )
        finally:
            _release_request_lock(getattr(session, 'request_lock', None))
            session.request_lock = None
