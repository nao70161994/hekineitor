import json
import os
import re
import secrets
from contextlib import contextmanager

import fcntl
from datetime import datetime, timezone

from storage import atomic_write_json, data_path, get_conn, put_conn, use_db


SHARE_LINKS_FILE = 'share_links.json'
ALPHABET = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz'
MIN_SHARE_ID_LENGTH = 4
GENERATED_SHARE_ID_LENGTH = 8
MAX_SHARE_ID_LENGTH = 12
SHARE_ID_RE = re.compile(rf'^[0-9A-Za-z]{{{MIN_SHARE_ID_LENGTH},{MAX_SHARE_ID_LENGTH}}}$')


@contextmanager
def _json_write_lock(path):
    """Serialize JSON read-modify-write cycles across worker processes."""
    lock_path = f'{path}.lock'
    os.makedirs(os.path.dirname(os.path.abspath(lock_path)), exist_ok=True)
    with open(lock_path, 'a', encoding='utf-8') as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def links_path(environ=None):
    if environ and environ.get('SHARE_LINKS_PATH'):
        return environ['SHARE_LINKS_PATH']
    return data_path(SHARE_LINKS_FILE)


def _use_db(environ=None, path=None):
    environ = environ or {}
    if path is not None or environ.get('SHARE_LINKS_PATH'):
        return False
    if environ.get('SHARE_LINKS_STORAGE') == 'json':
        return False
    return use_db()


def _ensure_schema(conn):
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS share_links (
            share_id TEXT PRIMARY KEY,
            payload TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    ''')


def _load_json(path):
    try:
        with open(path, encoding='utf-8') as file_obj:
            data = json.load(file_obj)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _load_db_links():
    conn = get_conn()
    try:
        with conn:
            _ensure_schema(conn)
            cur = conn.cursor()
            cur.execute('SELECT share_id, payload FROM share_links')
            rows = cur.fetchall()
    finally:
        put_conn(conn)
    result = {}
    for share_id, raw_payload in rows:
        if not valid_share_id(share_id):
            continue
        try:
            payload = json.loads(raw_payload)
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            cleaned = clean_payload(payload)
            if cleaned['name']:
                result[share_id] = cleaned
    return result


def load_links(path=None, environ=None):
    if _use_db(environ, path):
        try:
            return _load_db_links()
        except Exception:
            return {}
    raw = _load_json(path or links_path(environ))
    result = {}
    for share_id, payload in raw.items():
        if valid_share_id(share_id) and isinstance(payload, dict):
            cleaned = clean_payload(payload)
            if cleaned['name']:
                result[share_id] = cleaned
    return result


def count_links(path=None, environ=None):
    if _use_db(environ, path):
        conn = get_conn()
        try:
            with conn:
                _ensure_schema(conn)
                cur = conn.cursor()
                cur.execute('SELECT COUNT(*) FROM share_links')
                row = cur.fetchone()
                return int(row[0] or 0) if row else 0
        except Exception:
            return 0
        finally:
            put_conn(conn)
    return len(load_links(path=path, environ=environ))


def valid_share_id(value):
    return bool(SHARE_ID_RE.match(str(value or '')))


def clean_payload(payload):
    payload = payload or {}
    name = str(payload.get('name') or payload.get('fetish') or payload.get('result_name') or '').strip()[:60]
    probability = str(payload.get('probability') or payload.get('percent') or '').strip()[:5]
    desc = str(payload.get('desc') or payload.get('description') or '').strip()[:120]
    title = str(payload.get('title') or '').strip()[:80]
    rank = str(payload.get('rank') or payload.get('rarity') or '').strip()[:20]
    created_at = str(payload.get('created_at') or '')[:40]
    return {
        'name': name,
        'probability': probability,
        'percent': probability,
        'desc': desc,
        'title': title,
        'rank': rank,
        'created_at': created_at,
    }


def _new_share_id(existing, *, token_length=GENERATED_SHARE_ID_LENGTH, token_fn=None):
    token_fn = token_fn or (lambda length: ''.join(secrets.choice(ALPHABET) for _ in range(length)))
    for length in range(token_length, MAX_SHARE_ID_LENGTH + 1):
        for _ in range(20):
            share_id = token_fn(length)
            if len(str(share_id or '')) == length and valid_share_id(share_id) and share_id not in existing:
                return share_id
    raise RuntimeError('share_id generation failed')


def _create_db_link(payload, *, environ=None, now_fn=None, token_fn=None):
    cleaned = clean_payload(payload)
    if not cleaned['name']:
        raise ValueError('name is required')
    now = now_fn() if now_fn else datetime.now(timezone.utc)
    cleaned['created_at'] = now.astimezone(timezone.utc).isoformat(timespec='seconds')
    conn = get_conn()
    try:
        with conn:
            _ensure_schema(conn)
            cur = conn.cursor()
            cur.execute('SELECT share_id FROM share_links')
            existing = {row[0] for row in cur.fetchall()}
            share_id = _new_share_id(existing, token_fn=token_fn)
            cur.execute(
                'INSERT INTO share_links (share_id, payload, created_at) VALUES (%s, %s, %s)',
                (share_id, json.dumps(cleaned, ensure_ascii=False, separators=(',', ':')), cleaned['created_at']),
            )
    finally:
        put_conn(conn)
    return share_id, cleaned


def create_link(payload, *, path=None, environ=None, now_fn=None, token_fn=None):
    if _use_db(environ, path):
        return _create_db_link(payload, environ=environ, now_fn=now_fn, token_fn=token_fn)
    target = path or links_path(environ)
    cleaned = clean_payload(payload)
    if not cleaned['name']:
        raise ValueError('name is required')
    now = now_fn() if now_fn else datetime.now(timezone.utc)
    cleaned['created_at'] = now.astimezone(timezone.utc).isoformat(timespec='seconds')
    with _json_write_lock(target):
        links = load_links(path=target)
        share_id = _new_share_id(links, token_fn=token_fn)
        links[share_id] = cleaned
        atomic_write_json(target, links, ensure_ascii=False, indent=2, sort_keys=True)
    return share_id, cleaned


def resolve_link(share_id, *, path=None, environ=None):
    share_id = str(share_id or '').strip()
    if not valid_share_id(share_id):
        return None
    if _use_db(environ, path):
        conn = get_conn()
        try:
            with conn:
                _ensure_schema(conn)
                cur = conn.cursor()
                cur.execute('SELECT payload FROM share_links WHERE share_id = %s', (share_id,))
                row = cur.fetchone()
        except Exception:
            row = None
        finally:
            put_conn(conn)
        if not row:
            return None
        try:
            payload = json.loads(row[0])
        except (TypeError, json.JSONDecodeError):
            return None
        cleaned = clean_payload(payload)
        return cleaned if cleaned['name'] else None
    return load_links(path=path, environ=environ).get(share_id)
