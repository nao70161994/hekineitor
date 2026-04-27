#!/usr/bin/env python3
"""
fetishes.json の works からURLなし作品のKindle ASINを検索して直接リンクを付与するスクリプト。

使い方:
  python fetch_kindle_asins.py                # 全作品をチェック・fetishes.json を更新
  python fetch_kindle_asins.py --dry-run      # 検索だけしてfetishes.jsonは変更しない

途中で中断しても kindle_asin_progress.json に進捗を保存して再開できる。
"""

import json
import re
import time
import random
import sys
import os
import urllib.request
import urllib.parse
import http.cookiejar
from pathlib import Path

DATA_DIR     = Path(__file__).parent / 'data'
FETISHES     = DATA_DIR / 'fetishes.json'
PROGRESS     = Path(__file__).parent / 'kindle_asin_progress.json'
DRY_RUN      = '--dry-run' in sys.argv

ASSOCIATE_ID = os.environ.get('AMAZON_ASSOCIATE_ID', 'hekinator-22')

INTERVAL_MIN   = 8
INTERVAL_MAX   = 14
CAPTCHA_ABORT  = 8

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
]

BASE_HEADERS = {
    "Accept-Language": "ja-JP,ja;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
}

# セッションCookieを維持するopenerを共有
_opener = None

def _get_opener():
    global _opener
    if _opener is None:
        jar = http.cookiejar.CookieJar()
        _opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        # トップページを取得してCookieを初期化
        try:
            ua = random.choice(USER_AGENTS)
            _opener.open(
                urllib.request.Request('https://www.amazon.co.jp/', headers={**BASE_HEADERS, 'User-Agent': ua}),
                timeout=15
            )
            time.sleep(random.uniform(3, 5))
        except Exception:
            pass
    return _opener


def load_progress():
    if PROGRESS.exists():
        with open(PROGRESS) as f:
            return json.load(f)
    return {}


def save_progress(p):
    with open(PROGRESS, 'w') as f:
        json.dump(p, f, ensure_ascii=False, indent=2)


def search_kindle_asin(title: str) -> str | None:
    """タイトルでKindleストアを検索して最初のASINを返す。"""
    keyword = re.sub(r'[（(][^）)]*[）)]', '', title).strip()
    params  = urllib.parse.urlencode({'k': keyword, 'i': 'digital-text'})
    url     = f'https://www.amazon.co.jp/s?{params}'
    ua      = random.choice(USER_AGENTS)
    opener  = _get_opener()
    try:
        resp = opener.open(
            urllib.request.Request(url, headers={**BASE_HEADERS, 'User-Agent': ua}),
            timeout=15
        )
        html = resp.read().decode('utf-8', errors='replace')
    except Exception as e:
        print(f'  [ERROR] {e}')
        return 'ERROR'

    if 'api-services-support@amazon.com' in html or 'Type the characters' in html:
        print(f'  [CAPTCHA]')
        return 'CAPTCHA'

    # スポンサー商品を除いた最初のASINを優先
    # 検索結果ブロック: data-component-type="s-search-result" に data-asin がある
    blocks = re.findall(
        r'data-component-type="s-search-result"[^>]*?data-asin="([A-Z0-9]{10})"'
        r'|data-asin="([A-Z0-9]{10})"[^>]*?data-component-type="s-search-result"',
        html
    )
    for m in blocks:
        asin = m[0] or m[1]
        if asin:
            return asin

    # フォールバック: /dp/ASIN パターン
    m = re.search(r'/dp/([A-Z0-9]{10})/', html)
    return m.group(1) if m else None


def kindle_url(asin: str) -> str:
    return f'https://www.amazon.co.jp/dp/{asin}?tag={ASSOCIATE_ID}'


def main():
    with open(FETISHES) as f:
        fetishes = json.load(f)

    # URLなし作品を収集
    targets = []   # (fetish_idx, work_idx, title)
    for fi, fe in enumerate(fetishes):
        for wi, w in enumerate(fe.get('works', [])):
            if isinstance(w, dict):
                if not w.get('url'):
                    targets.append((fi, wi, w['title']))
            else:
                targets.append((fi, wi, w))

    print(f'URLなし作品: {len(targets)} 件')

    progress = load_progress()
    done = sum(1 for v in progress.values() if v and v not in ('CAPTCHA', 'ERROR', 'NOT_FOUND'))
    print(f'進捗: {done}/{len(targets)} 件完了\n')

    captcha_streak = 0
    updated = 0

    for fi, wi, title in targets:
        if title in progress and progress[title] not in ('CAPTCHA', 'ERROR'):
            continue

        idx = done + updated + 1
        print(f'[{idx}/{len(targets)}] {title}', end=' ... ', flush=True)

        asin = search_kindle_asin(title)

        if asin == 'CAPTCHA':
            captcha_streak += 1
            progress[title] = 'CAPTCHA'
            save_progress(progress)
            print(f'CAPTCHA ({captcha_streak}連続)')
            if captcha_streak >= CAPTCHA_ABORT:
                print(f'\nCAPTCHA {CAPTCHA_ABORT}連続。中断します。しばらく待ってから再実行してください。')
                break
            time.sleep(60)
            continue
        elif asin == 'ERROR':
            progress[title] = 'ERROR'
            save_progress(progress)
            captcha_streak = 0
            print('通信エラー')
        elif asin is None:
            progress[title] = 'NOT_FOUND'
            save_progress(progress)
            captcha_streak = 0
            print('見つからず')
        else:
            progress[title] = asin
            save_progress(progress)
            captcha_streak = 0
            updated += 1
            print(f'ASIN={asin} → {kindle_url(asin)}')

        time.sleep(random.uniform(INTERVAL_MIN, INTERVAL_MAX))

    # fetishes.json に反映
    if DRY_RUN:
        print('\n--dry-run のため fetishes.json は変更しません')
    else:
        apply_count = 0
        for fi, fe in enumerate(fetishes):
            for wi, w in enumerate(fe.get('works', [])):
                title = w['title'] if isinstance(w, dict) else w
                asin  = progress.get(title)
                if not asin or asin in ('CAPTCHA', 'ERROR', 'NOT_FOUND'):
                    continue
                url = kindle_url(asin)
                if isinstance(w, dict):
                    if not w.get('url'):
                        fetishes[fi]['works'][wi]['url'] = url
                        apply_count += 1
                else:
                    fetishes[fi]['works'][wi] = {'title': title, 'url': url}
                    apply_count += 1

        with open(FETISHES, 'w') as f:
            json.dump(fetishes, f, ensure_ascii=False, indent=2)
        print(f'\nfetishes.json を更新しました（{apply_count} 件）')

    # サマリー
    total     = len(targets)
    found     = sum(1 for v in progress.values() if v and v not in ('CAPTCHA', 'ERROR', 'NOT_FOUND'))
    not_found = sum(1 for v in progress.values() if v == 'NOT_FOUND')
    errors    = sum(1 for v in progress.values() if v in ('CAPTCHA', 'ERROR'))
    print(f'\n--- サマリー ---')
    print(f'合計: {total} / 取得成功: {found} / 未発見: {not_found} / エラー: {errors}')
    if errors:
        print('エラー分は再実行すると続きから再開します')


if __name__ == '__main__':
    main()
