import json
import os
import re
import secrets
from datetime import datetime, timezone

from storage import atomic_write_json, data_path


SHARE_LINKS_FILE = 'share_links.json'
ALPHABET = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz'
SHARE_ID_RE = re.compile(r'^[0-9A-Za-z]{4,12}$')


def links_path(environ=None):
    if environ and environ.get('SHARE_LINKS_PATH'):
        return environ['SHARE_LINKS_PATH']
    return data_path(SHARE_LINKS_FILE)


def _load_json(path):
    try:
        with open(path, encoding='utf-8') as file_obj:
            data = json.load(file_obj)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def load_links(path=None, environ=None):
    raw = _load_json(path or links_path(environ))
    result = {}
    for share_id, payload in raw.items():
        if valid_share_id(share_id) and isinstance(payload, dict):
            cleaned = clean_payload(payload)
            if cleaned['name']:
                result[share_id] = cleaned
    return result


def count_links(path=None, environ=None):
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


def _new_share_id(existing, *, token_length=4, token_fn=None):
    token_fn = token_fn or (lambda length: ''.join(secrets.choice(ALPHABET) for _ in range(length)))
    for length in range(token_length, 7):
        for _ in range(20):
            share_id = token_fn(length)
            if valid_share_id(share_id) and share_id not in existing:
                return share_id
    raise RuntimeError('share_id generation failed')


def create_link(payload, *, path=None, environ=None, now_fn=None, token_fn=None):
    target = path or links_path(environ)
    links = load_links(path=target)
    cleaned = clean_payload(payload)
    if not cleaned['name']:
        raise ValueError('name is required')
    now = now_fn() if now_fn else datetime.now(timezone.utc)
    cleaned['created_at'] = now.astimezone(timezone.utc).isoformat(timespec='seconds')
    share_id = _new_share_id(links, token_fn=token_fn)
    links[share_id] = cleaned
    atomic_write_json(target, links, ensure_ascii=False, indent=2, sort_keys=True)
    return share_id, cleaned


def resolve_link(share_id, *, path=None, environ=None):
    share_id = str(share_id or '').strip()
    if not valid_share_id(share_id):
        return None
    return load_links(path=path, environ=environ).get(share_id)
