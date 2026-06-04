import re
import urllib.parse
from collections import Counter

ASIN_RE = re.compile(r'/dp/([A-Z0-9]{10})')


def work_url_status(work):
    """Classify a work link for affiliate maintenance without mutating data."""
    title = work.get('title', '') if isinstance(work, dict) else str(work)
    url = (work.get('url') or '') if isinstance(work, dict) else ''
    url = str(url).strip()
    if not url:
        return 'missing_url', ''
    parsed = urllib.parse.urlparse(url)
    if 'amazon.co.jp' in parsed.netloc and (parsed.path.startswith('/s') or parsed.query.startswith('k=')):
        return 'search_url', url
    if 'amazon.co.jp' in parsed.netloc and not ASIN_RE.search(url):
        return 'missing_asin', url
    return 'ok', url


def _affiliate_search_url(title, associate_id):
    title = str(title or '').strip()
    associate_id = str(associate_id or '').strip()
    if not title or not associate_id:
        return ''
    return f"https://www.amazon.co.jp/s?k={urllib.parse.quote(title)}&tag={urllib.parse.quote(associate_id)}"


def collect_work_link_queue(fetishes, *, sample_limit=20, associate_id=''):
    buckets = {'missing_url': [], 'fallback_search_url': [], 'search_url': [], 'missing_asin': []}
    for fetish in fetishes:
        for index, work in enumerate(fetish.get('works', [])):
            status, url = work_url_status(work)
            if status == 'ok':
                continue
            title = work.get('title', '') if isinstance(work, dict) else str(work)
            fallback_url = _affiliate_search_url(title, associate_id) if status == 'missing_url' else ''
            bucket = 'fallback_search_url' if fallback_url else status
            buckets[bucket].append({
                'fetish_id': fetish.get('id'),
                'fetish_name': fetish.get('name', ''),
                'work_index': index,
                'title': title,
                'url': url,
                'fallback_url': fallback_url,
            })
    counts = {key: len(value) for key, value in buckets.items()}
    total = sum(counts.values())
    samples = {key: value[:sample_limit] for key, value in buckets.items()}
    return {'status': 'ok', 'total': total, 'counts': counts, 'samples': samples}


def summarize_backfill_candidates(fetishes, progress, *, associate_id='hekinator-22', limit=30):
    """Report works that can be converted from missing/search URL to direct ASIN links."""
    candidates = []
    for fetish in fetishes:
        for index, work in enumerate(fetish.get('works', [])):
            status, current_url = work_url_status(work)
            if status == 'ok':
                continue
            title = work.get('title', '') if isinstance(work, dict) else str(work)
            asin = progress.get(title)
            if not asin or asin in ('CAPTCHA', 'ERROR', 'NOT_FOUND'):
                continue
            candidates.append({
                'fetish_id': fetish.get('id'),
                'fetish_name': fetish.get('name', ''),
                'work_index': index,
                'title': title,
                'current_status': status,
                'current_url': current_url,
                'asin': asin,
                'direct_url': f'https://www.amazon.co.jp/dp/{asin}?tag={associate_id}',
            })
    return {'count': len(candidates), 'samples': candidates[:limit]}



def build_work_maintenance_summary(fetishes, *, work_title_fn, safe_work_url_fn, sample_limit=8):
    missing_work_fetishes = []
    missing_url_works = []
    unsafe_url_works = []
    duplicate_index = {}
    total_works = 0
    direct_url_work_count = 0
    search_url_work_count = 0
    missing_asin_work_count = 0
    for fetish in fetishes:
        works = fetish.get('works') or []
        if not works:
            missing_work_fetishes.append({
                'fetish_id': fetish['id'],
                'fetish_name': fetish['name'],
            })
            continue
        for work in works:
            total_works += 1
            title = work_title_fn(work)
            url = work.get('url', '') if isinstance(work, dict) else ''
            row = {
                'fetish_id': fetish['id'],
                'fetish_name': fetish['name'],
                'title': title,
            }
            normalized_title = str(title or '').strip().casefold()
            if normalized_title:
                duplicate_index.setdefault(normalized_title, {'title': title, 'items': []})['items'].append(row)
            status, _status_url = work_url_status(work)
            if status == 'ok' and url:
                direct_url_work_count += 1
            elif status == 'search_url':
                search_url_work_count += 1
            elif status == 'missing_asin':
                missing_asin_work_count += 1
            if not url:
                missing_url_works.append(row)
            elif not safe_work_url_fn(url):
                unsafe_url_works.append({**row, 'url': str(url)})
    duplicate_works = []
    for duplicate in duplicate_index.values():
        items = duplicate['items']
        if len(items) <= 1:
            continue
        duplicate_works.append({
            'title': duplicate['title'],
            'count': len(items),
            'fetishes': items[:sample_limit],
        })
    duplicate_works.sort(key=lambda row: (-row['count'], row['title']))
    return {
        'total_works': total_works,
        'direct_url_work_count': direct_url_work_count,
        'search_url_work_count': search_url_work_count,
        'missing_asin_work_count': missing_asin_work_count,
        'duplicate_work_title_count': len(duplicate_works),
        'missing_work_fetish_count': len(missing_work_fetishes),
        'missing_url_work_count': len(missing_url_works),
        'unsafe_url_work_count': len(unsafe_url_works),
        'missing_work_fetishes': missing_work_fetishes[:sample_limit],
        'missing_url_works': missing_url_works[:sample_limit],
        'unsafe_url_works': unsafe_url_works[:sample_limit],
        'duplicate_works': duplicate_works[:sample_limit],
        'works_review_url': '/api/admin/works_review',
    }
