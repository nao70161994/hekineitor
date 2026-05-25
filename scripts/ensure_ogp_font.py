#!/usr/bin/env python3
"""Ensure a CJK-capable font is available for PNG OGP rendering.

This script is intended for deploy/build environments. It never downloads unless
`DOWNLOAD_OGP_FONT=1` is set, so local tests stay offline and deterministic.
"""

import os
import shutil
import sys
import urllib.request

DEFAULT_FONT_URL = (
    'https://raw.githubusercontent.com/googlefonts/noto-cjk/main/'
    'Sans/OTF/Japanese/NotoSansCJKjp-Regular.otf'
)
DEFAULT_TARGET = os.path.join('data', 'fonts', 'NotoSansCJKjp-Regular.otf')
COMMON_CJK_FONTS = (
    '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
    '/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc',
    '/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc',
    '/usr/share/fonts/truetype/noto/NotoSansJP-Regular.otf',
    '/usr/share/fonts/opentype/ipafont-gothic/ipagp.ttf',
    '/usr/share/fonts/truetype/fonts-japanese-gothic.ttf',
    '/usr/share/fonts/truetype/vlgothic/VL-Gothic-Regular.ttf',
    '/system/fonts/NotoSansCJK-Regular.ttc',
)


def _exists(path):
    return bool(path) and os.path.exists(path) and os.path.getsize(path) > 0


def discover_font():
    env_path = os.environ.get('OGP_FONT_PATH')
    if _exists(env_path):
        return env_path
    for path in COMMON_CJK_FONTS:
        if _exists(path):
            return path
    for path in (DEFAULT_TARGET, os.path.join(os.getcwd(), DEFAULT_TARGET)):
        if _exists(path):
            return path
    return ''


def copy_font(source, target):
    os.makedirs(os.path.dirname(target), exist_ok=True)
    if os.path.abspath(source) != os.path.abspath(target):
        shutil.copyfile(source, target)
    return target


def download_font(target, url):
    os.makedirs(os.path.dirname(target), exist_ok=True)
    tmp = target + '.tmp'
    with urllib.request.urlopen(url, timeout=60) as response, open(tmp, 'wb') as file_obj:
        shutil.copyfileobj(response, file_obj)
    os.replace(tmp, target)
    return target


def main():
    target = os.environ.get('OGP_FONT_TARGET', DEFAULT_TARGET)
    existing = discover_font()
    if existing:
        if os.environ.get('COPY_OGP_FONT') == '1' and existing != target:
            copied = copy_font(existing, target)
            print(f'OGP font copied to {copied}')
            return 0
        print(f'OGP font available: {existing}')
        return 0
    if os.environ.get('DOWNLOAD_OGP_FONT') == '1':
        url = os.environ.get('OGP_FONT_DOWNLOAD_URL', DEFAULT_FONT_URL)
        downloaded = download_font(target, url)
        print(f'OGP font downloaded to {downloaded}')
        return 0
    print(
        'No CJK OGP font found. Set OGP_FONT_PATH or run with DOWNLOAD_OGP_FONT=1.',
        file=sys.stderr,
    )
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
