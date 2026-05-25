import json
import os
import random
import time
import uuid

from flask.sessions import SessionInterface, SessionMixin
from werkzeug.datastructures import CallbackDict

from engine import _get_conn, _put_conn, _use_db
from services.app_meta import is_production_env


SESSION_TTL = 86400
LOCAL_SESSIONS = {}


def session_load(sid):
    if _use_db():
        conn = _get_conn()
        try:
            cur = conn.cursor()
            cur.execute('SELECT data, updated_at FROM sessions WHERE session_id = %s', (sid,))
            row = cur.fetchone()
            if row and time.time() - row[1] < SESSION_TTL:
                return json.loads(row[0])
        finally:
            _put_conn(conn)
    else:
        entry = LOCAL_SESSIONS.get(sid)
        if entry and time.time() - entry[1] < SESSION_TTL:
            return dict(entry[0])
    return None


def session_save(sid, data):
    now = time.time()
    if _use_db():
        conn = _get_conn()
        try:
            with conn:
                cur = conn.cursor()
                cur.execute('\n                    INSERT INTO sessions (session_id, data, updated_at) VALUES (%s, %s, %s)\n                    ON CONFLICT (session_id) DO UPDATE\n                    SET data = EXCLUDED.data, updated_at = EXCLUDED.updated_at\n                ', (sid, json.dumps(data, ensure_ascii=False), now))
                if random.random() < 0.01:
                    cur.execute('DELETE FROM sessions WHERE updated_at < %s', (now - SESSION_TTL,))
        finally:
            _put_conn(conn)
    else:
        LOCAL_SESSIONS[sid] = (data, now)
        if len(LOCAL_SESSIONS) > 2000:
            cutoff = now - SESSION_TTL
            for key in [key for key, value in LOCAL_SESSIONS.items() if value[1] < cutoff]:
                del LOCAL_SESSIONS[key]


def cleanup_sessions():
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
    old = [key for key, value in LOCAL_SESSIONS.items() if value[1] < cutoff]
    for key in old:
        del LOCAL_SESSIONS[key]
    return len(old)


def local_session_count():
    if _use_db():
        return None
    return len(LOCAL_SESSIONS)


class ServerSession(CallbackDict, SessionMixin):
    def __init__(self, initial=None, sid=None, is_new=False):
        def on_update(self):
            self.modified = True
        super().__init__(initial or {}, on_update)
        self.sid = sid
        self.is_new = is_new
        self.modified = False


class ServerSessionInterface(SessionInterface):
    _cookie = 'heki_sid'

    def open_session(self, app, request):
        sid = request.cookies.get(self._cookie)
        if sid:
            data = session_load(sid)
            if data is not None:
                return ServerSession(data, sid=sid)
        return ServerSession(sid=str(uuid.uuid4()), is_new=True)

    def save_session(self, app, session, response):
        if not session.modified and not session.is_new:
            return
        session_save(session.sid, dict(session))
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
