#!/usr/bin/env python3
"""Small ntfy helper for operational notifications.

The helper intentionally reads only NTFY_* environment variables and never
prints secrets. Missing NTFY_TOPIC is treated as a successful no-op so the same
scripts can run in local, CI, and production cron jobs.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Mapping, MutableMapping
from urllib.parse import quote
from urllib.request import Request, urlopen


DEFAULT_SERVER = 'https://ntfy.sh'


def _clean_header(value: str, limit: int = 200) -> str:
    return str(value or '').replace('\r', ' ').replace('\n', ' ').strip()[:limit]


def build_ntfy_url(environ: Mapping[str, str] | None = None) -> str | None:
    environ = os.environ if environ is None else environ
    topic = str(environ.get('NTFY_TOPIC') or '').strip()
    if not topic:
        return None
    server = str(environ.get('NTFY_SERVER') or DEFAULT_SERVER).strip().rstrip('/')
    if not server:
        server = DEFAULT_SERVER
    return f"{server}/{quote(topic, safe='')}"


def notify(
    title: str,
    message: str,
    *,
    priority: str = 'default',
    tags: str = '',
    environ: Mapping[str, str] | None = None,
    opener=urlopen,
    timeout: int = 10,
) -> dict:
    url = build_ntfy_url(environ)
    if not url:
        return {'sent': False, 'skipped': True, 'reason': 'NTFY_TOPIC is not set'}
    body = str(message or '').encode('utf-8')
    headers: MutableMapping[str, str] = {
        'Title': _clean_header(title, 120),
        'Priority': _clean_header(priority, 32) or 'default',
    }
    if tags:
        headers['Tags'] = _clean_header(tags, 80)
    request = Request(url, data=body, method='POST', headers=dict(headers))
    with opener(request, timeout=timeout) as response:
        status = getattr(response, 'status', None) or getattr(response, 'code', 0)
    return {'sent': True, 'skipped': False, 'status': status}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Send a ntfy notification if NTFY_TOPIC is configured.')
    parser.add_argument('--title', required=True)
    parser.add_argument('--message', required=True)
    parser.add_argument('--priority', default='default')
    parser.add_argument('--tags', default='')
    args = parser.parse_args(argv)
    try:
        result = notify(args.title, args.message, priority=args.priority, tags=args.tags)
    except Exception as exc:  # pragma: no cover - CLI safety path
        print(f'ntfy failed: {exc.__class__.__name__}', file=sys.stderr)
        return 1
    if result.get('skipped'):
        print('ntfy skipped: NTFY_TOPIC is not set')
    else:
        print('ntfy sent')
    return 0


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
