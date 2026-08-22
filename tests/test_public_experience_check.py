import json
import struct

import pytest

from scripts import public_experience_check


def _response(content_type, body):
    return 200, {'content-type': content_type}, body


def _fake_fetcher(url, _headers):
    base = 'https://example.com'
    if url == f'{base}/health':
        return _response('application/json', b'{"status":"ok"}')
    if url == f'{base}/':
        return _response(
            'text/html',
            (
                '<h1>ひとつ、思い浮かべてください</h1>答えそのものを直接聞かず'
                '<a href="/privacy">data</a><script src="/static/performance.js"></script>'
            ).encode(),
        )
    if url == f'{base}/privacy':
        return _response('text/html', 'データの扱い 最大7日間 90日'.encode())
    if url.startswith(f'{base}/r?'):
        image = f'{base}/ogp.png?f=%E7%9C%BC%E9%8F%A1&amp;p=88'
        tags = {
            'og:title': 'result',
            'og:description': 'description',
            'og:url': url.replace('&', '&amp;'),
            'og:image': image,
            'og:image:secure_url': image,
            'og:image:width': '1200',
            'og:image:height': '630',
            'twitter:card': 'summary_large_image',
            'twitter:title': 'result',
            'twitter:description': 'description',
            'twitter:image': image,
            'twitter:image:alt': 'alt',
        }
        body = ''.join(
            f'<meta {"property" if key.startswith("og:") else "name"}="{key}" content="{value}">'
            for key, value in tags.items()
        ).encode()
        return _response('text/html; charset=utf-8', body)
    if url.startswith(f'{base}/ogp.png?'):
        body = public_experience_check.PNG_SIGNATURE + b'\0\0\0\rIHDR' + struct.pack('>II', 1200, 630) + b'png'
        return _response('image/png', body)
    if url == f'{base}/manifest.json':
        body = json.dumps(
            {
                'id': '/',
                'start_url': '/',
                'display': 'standalone',
                'icons': [{'sizes': '192x192'}, {'sizes': '512x512'}],
            }
        ).encode()
        return _response('application/manifest+json', body)
    if url == f'{base}/sw.js':
        return _response('application/javascript', b"install; fetch; '/offline'")
    if url == f'{base}/static/performance.js':
        return _response('text/javascript', b"PerformanceObserver; event_name: 'web_vitals'")
    if url == f'{base}/offline':
        return _response('text/html', b'<h1>offline</h1>')
    raise AssertionError(url)


def test_public_experience_report_covers_crawlers_ogp_and_pwa():
    report = public_experience_check.build_report(
        'https://example.com',
        'example.com',
        fetcher=_fake_fetcher,
    )

    assert report['status'] == 'passed'
    assert [row['name'] for row in report['checks']] == [
        'health',
        'home_ui_contract',
        'privacy',
        'crawler_metadata',
        'ogp_png',
        'manifest',
        'service_worker',
        'web_vitals',
        'offline',
    ]
    assert report['manual_boundaries'] == [
        'external_preview_rendering',
        'native_share_sheet',
        'installed_pwa_lifecycle',
        'physical_screen_reader',
    ]


@pytest.mark.parametrize(
    'url',
    ('http://example.com', 'https://other.example', 'https://example.com/path', 'https://user@example.com'),
)
def test_public_experience_rejects_non_exact_https_target(url):
    with pytest.raises(ValueError):
        public_experience_check.build_report(url, 'example.com', fetcher=_fake_fetcher)
