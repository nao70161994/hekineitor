#!/usr/bin/env python3
"""Read-only public production checks for share metadata and PWA resources."""

from __future__ import annotations

import argparse
import json
import re
import struct
import urllib.parse
import urllib.request
from pathlib import Path

PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'
RESULT_QUERY = urllib.parse.urlencode({'f': '眼鏡', 'p': '88', 'd': 'テスト'})
REQUIRED_META = (
    'og:title',
    'og:description',
    'og:url',
    'og:image',
    'og:image:secure_url',
    'og:image:width',
    'og:image:height',
    'twitter:card',
    'twitter:title',
    'twitter:description',
    'twitter:image',
    'twitter:image:alt',
)


def _validate_target(base_url: str, expected_host: str) -> str:
    parsed = urllib.parse.urlparse(base_url)
    if parsed.scheme != 'https' or parsed.hostname != expected_host or parsed.path not in ('', '/'):
        raise ValueError('target must be the HTTPS root of the exact expected host')
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.port not in (None, 443):
        raise ValueError('target contains forbidden URL components')
    return base_url.rstrip('/')


def _fetch(url: str, headers: dict[str, str]):
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.status, {key.lower(): value for key, value in response.headers.items()}, response.read()


def _meta(html: str) -> dict[str, str]:
    result = {}
    for tag in re.findall(r'<meta\s+[^>]*>', html, flags=re.IGNORECASE):
        key_match = re.search(r'(?:property|name)=["\']([^"\']+)["\']', tag, flags=re.IGNORECASE)
        value_match = re.search(r'content=["\']([^"\']*)["\']', tag, flags=re.IGNORECASE)
        if key_match and value_match:
            result[key_match.group(1).lower()] = value_match.group(1)
    return result


def _require_response(status, headers, body, *, content_type):
    if status != 200:
        raise RuntimeError(f'expected HTTP 200, received {status}')
    actual_type = headers.get('content-type', '').split(';', 1)[0].strip().lower()
    if actual_type != content_type:
        raise RuntimeError(f'expected {content_type}, received {actual_type or "missing content type"}')
    if not body:
        raise RuntimeError('response body is empty')


def build_report(base_url: str, expected_host: str, *, fetcher=_fetch) -> dict:
    base_url = _validate_target(base_url, expected_host)
    checks = []

    status, headers, body = fetcher(f'{base_url}/health', {'Accept': 'application/json'})
    _require_response(status, headers, body, content_type='application/json')
    health = json.loads(body)
    if health.get('status') != 'ok':
        raise RuntimeError('public health status is not ok')
    checks.append({'name': 'health', 'status': 'passed'})

    status, headers, body = fetcher(f'{base_url}/', {'User-Agent': 'Mozilla/5.0', 'Accept': 'text/html'})
    _require_response(status, headers, body, content_type='text/html')
    home = body.decode('utf-8')
    for marker in (
        'ひとつ、思い浮かべてください',
        '答えそのものを直接聞かず',
        'href="/privacy"',
        '/static/performance.js',
    ):
        if marker not in home:
            raise RuntimeError(f'public home is missing UI contract: {marker}')
    if 'question-answer-frame' in home or '約20問' in home:
        raise RuntimeError('public home contains a retired fixed-question UI contract')
    checks.append({'name': 'home_ui_contract', 'status': 'passed'})

    status, headers, body = fetcher(f'{base_url}/privacy', {'Accept': 'text/html'})
    _require_response(status, headers, body, content_type='text/html')
    privacy = body.decode('utf-8')
    if 'データの扱い' not in privacy or '最大7日間' not in privacy or '90日' not in privacy:
        raise RuntimeError('privacy page does not expose storage and retention contracts')
    checks.append({'name': 'privacy', 'status': 'passed'})

    result_url = f'{base_url}/r?{RESULT_QUERY}'
    crawler_meta = {}
    for name, user_agent in (
        ('browser', 'Mozilla/5.0'),
        ('twitter', 'Twitterbot/1.0'),
        ('discord', 'Discordbot/2.0'),
    ):
        status, headers, body = fetcher(result_url, {'User-Agent': user_agent, 'Accept': 'text/html'})
        _require_response(status, headers, body, content_type='text/html')
        metadata = _meta(body.decode('utf-8'))
        missing = sorted(set(REQUIRED_META) - set(metadata))
        if missing:
            raise RuntimeError(f'{name} metadata missing: {", ".join(missing)}')
        if metadata['twitter:card'] != 'summary_large_image':
            raise RuntimeError(f'{name} does not request a large Twitter card')
        if metadata['og:image:width'] != '1200' or metadata['og:image:height'] != '630':
            raise RuntimeError(f'{name} OGP dimensions are not 1200x630')
        image_url = metadata['og:image'].replace('&amp;', '&')
        if not image_url.startswith(f'{base_url}/ogp.png?') or metadata['og:image:secure_url'] != metadata['og:image']:
            raise RuntimeError(f'{name} OGP image is not the expected secure production PNG')
        crawler_meta[name] = metadata
    if any(crawler_meta[name] != crawler_meta['browser'] for name in ('twitter', 'discord')):
        raise RuntimeError('crawler metadata differs from browser metadata')
    checks.append({'name': 'crawler_metadata', 'status': 'passed', 'agents': list(crawler_meta)})

    image_url = crawler_meta['browser']['og:image'].replace('&amp;', '&')
    status, headers, body = fetcher(image_url, {'Accept': 'image/png'})
    _require_response(status, headers, body, content_type='image/png')
    if not body.startswith(PNG_SIGNATURE) or len(body) < 24:
        raise RuntimeError('OGP response is not a valid PNG header')
    width, height = struct.unpack('>II', body[16:24])
    if (width, height) != (1200, 630):
        raise RuntimeError(f'OGP PNG dimensions are {width}x{height}')
    checks.append({'name': 'ogp_png', 'status': 'passed', 'width': width, 'height': height, 'bytes': len(body)})

    status, headers, body = fetcher(f'{base_url}/manifest.json', {'Accept': 'application/manifest+json'})
    _require_response(status, headers, body, content_type='application/manifest+json')
    manifest = json.loads(body)
    if manifest.get('id') != '/' or manifest.get('start_url') != '/' or manifest.get('display') != 'standalone':
        raise RuntimeError('manifest install identity is incomplete')
    icon_sizes = {row.get('sizes') for row in manifest.get('icons', []) if isinstance(row, dict)}
    if not {'192x192', '512x512'}.issubset(icon_sizes):
        raise RuntimeError('manifest is missing install icons')
    checks.append({'name': 'manifest', 'status': 'passed'})

    status, headers, body = fetcher(f'{base_url}/sw.js', {'Accept': 'application/javascript'})
    _require_response(status, headers, body, content_type='application/javascript')
    source = body.decode('utf-8')
    if '/offline' not in source or 'fetch' not in source or 'install' not in source:
        raise RuntimeError('service worker does not expose install/fetch/offline contracts')
    checks.append({'name': 'service_worker', 'status': 'passed'})

    status, headers, body = fetcher(f'{base_url}/static/performance.js', {'Accept': 'application/javascript'})
    _require_response(status, headers, body, content_type='application/javascript')
    source = body.decode('utf-8')
    if "event_name: 'web_vitals'" not in source or 'PerformanceObserver' not in source:
        raise RuntimeError('public performance measurement contract is incomplete')
    checks.append({'name': 'web_vitals', 'status': 'passed'})

    status, headers, body = fetcher(f'{base_url}/offline', {'Accept': 'text/html'})
    _require_response(status, headers, body, content_type='text/html')
    checks.append({'name': 'offline', 'status': 'passed'})
    return {
        'schema_version': 1,
        'target_host': expected_host,
        'status': 'passed',
        'checks': checks,
        'manual_boundaries': [
            'external_preview_rendering',
            'native_share_sheet',
            'installed_pwa_lifecycle',
            'physical_screen_reader',
        ],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', default='https://hekineitor.onrender.com')
    parser.add_argument('--expected-host', default='hekineitor.onrender.com')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    report = build_report(args.base_url, args.expected_host)
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + '\n'
    if args.output:
        args.output.write_text(rendered, encoding='utf-8')
    print(rendered, end='')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
