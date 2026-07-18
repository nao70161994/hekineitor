import re
import urllib.parse
from collections import defaultdict

from work_utils import normalized_work_title, work_title_candidate_key

ASIN_RE = re.compile(r'/dp/([A-Z0-9]{10})', re.IGNORECASE)


def work_url_status(work):
    """Classify a work link for affiliate maintenance without mutating data."""
    url = (work.get('url') or '') if isinstance(work, dict) else ''
    url = str(url).strip()
    if not url:
        return 'missing_url', ''
    parsed = urllib.parse.urlparse(url)
    hostname = (parsed.hostname or '').lower().rstrip('.')
    is_amazon_jp = hostname == 'amazon.co.jp' or hostname.endswith('.amazon.co.jp')
    if is_amazon_jp and (parsed.path.startswith('/s') or parsed.query.startswith('k=')):
        return 'search_url', url
    if is_amazon_jp and not ASIN_RE.search(url):
        return 'missing_asin', url
    return 'ok', url


def _affiliate_search_url(title, associate_id):
    title = str(title or '').strip()
    associate_id = str(associate_id or '').strip()
    if not title or not associate_id:
        return ''
    return f'https://www.amazon.co.jp/s?k={urllib.parse.quote(title)}&tag={urllib.parse.quote(associate_id)}'


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
            buckets[bucket].append(
                {
                    'fetish_id': fetish.get('id'),
                    'fetish_name': fetish.get('name', ''),
                    'work_index': index,
                    'title': title,
                    'url': url,
                    'fallback_url': fallback_url,
                }
            )
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
            candidates.append(
                {
                    'fetish_id': fetish.get('id'),
                    'fetish_name': fetish.get('name', ''),
                    'work_index': index,
                    'title': title,
                    'current_status': status,
                    'current_url': current_url,
                    'asin': asin,
                    'direct_url': f'https://www.amazon.co.jp/dp/{asin}?tag={associate_id}',
                }
            )
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
            missing_work_fetishes.append(
                {
                    'fetish_id': fetish['id'],
                    'fetish_name': fetish['name'],
                }
            )
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
        duplicate_works.append(
            {
                'title': duplicate['title'],
                'count': len(items),
                'fetishes': items[:sample_limit],
            }
        )
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


def _catalog_work_row(*, source, owner_id, owner_name, index, work):
    title = work.get('title', '') if isinstance(work, dict) else str(work or '')
    url = work.get('url', '') if isinstance(work, dict) else ''
    asin_match = ASIN_RE.search(str(url))
    return {
        'source': source,
        'owner_id': owner_id,
        'owner_name': str(owner_name or ''),
        'work_index': index,
        'title': str(title or '').strip(),
        'url': str(url or '').strip(),
        'asin': asin_match.group(1).upper() if asin_match else '',
        'exact_key': normalized_work_title(title),
        'candidate_key': work_title_candidate_key(title),
    }


def _catalog_group_samples(groups, *, predicate, sample_limit):
    result = []
    for key, items in groups.items():
        if not key or not predicate(items):
            continue
        titles = sorted({item['title'] for item in items})
        asins = sorted({item['asin'] for item in items if item['asin']})
        result.append(
            {
                'key': key,
                'count': len(items),
                'titles': titles[:sample_limit],
                'asins': asins[:sample_limit],
                'items': [
                    {
                        field: item[field]
                        for field in ('source', 'owner_id', 'owner_name', 'work_index', 'title', 'asin')
                    }
                    for item in items[:sample_limit]
                ],
            }
        )
    result.sort(key=lambda row: (-row['count'], row['key']))
    return result


def build_work_catalog_report(fetishes, *, compound_rows=(), sample_limit=20):
    """Build a read-only duplicate/alias/conflict report without merging work identities."""
    rows = []
    for fetish in fetishes:
        for index, work in enumerate(fetish.get('works') or []):
            rows.append(
                _catalog_work_row(
                    source='fetish',
                    owner_id=fetish.get('id'),
                    owner_name=fetish.get('name', ''),
                    index=index,
                    work=work,
                )
            )
    for compound in compound_rows or []:
        owner_id = compound.get('key') or f'{compound.get("id_a")},{compound.get("id_b")}'
        for index, work in enumerate(compound.get('works') or []):
            rows.append(
                _catalog_work_row(
                    source='compound',
                    owner_id=owner_id,
                    owner_name=owner_id,
                    index=index,
                    work=work,
                )
            )

    by_owner_exact = defaultdict(list)
    by_exact = defaultdict(list)
    by_candidate = defaultdict(list)
    by_asin = defaultdict(list)
    for row in rows:
        by_owner_exact[(row['source'], str(row['owner_id']), row['exact_key'])].append(row)
        by_exact[row['exact_key']].append(row)
        by_candidate[row['candidate_key']].append(row)
        if row['asin']:
            by_asin[row['asin']].append(row)

    within_owner = _catalog_group_samples(
        by_owner_exact, predicate=lambda items: len(items) > 1, sample_limit=sample_limit
    )
    asin_aliases = _catalog_group_samples(
        by_asin,
        predicate=lambda items: len({item['exact_key'] for item in items}) > 1,
        sample_limit=sample_limit,
    )
    candidate_groups = _catalog_group_samples(
        by_candidate,
        predicate=lambda items: len({item['exact_key'] for item in items}) > 1,
        sample_limit=sample_limit,
    )
    candidate_conflicts = [row for row in candidate_groups if len(row['asins']) > 1]
    exact_conflicts = _catalog_group_samples(
        by_exact,
        predicate=lambda items: len({item['asin'] for item in items if item['asin']}) > 1,
        sample_limit=sample_limit,
    )
    safe_candidates = [row for row in candidate_groups if len(row['asins']) <= 1]

    return {
        'status': 'ok',
        'total_works': len(rows),
        'fetish_work_count': sum(row['source'] == 'fetish' for row in rows),
        'compound_work_count': sum(row['source'] == 'compound' for row in rows),
        'within_owner_exact_duplicate_count': len(within_owner),
        'same_asin_alias_count': len(asin_aliases),
        'normalization_candidate_count': len(safe_candidates),
        'normalization_conflict_count': len(candidate_conflicts),
        'exact_title_asin_conflict_count': len(exact_conflicts),
        'within_owner_exact_duplicates': within_owner[:sample_limit],
        'same_asin_aliases': asin_aliases[:sample_limit],
        'normalization_candidates': safe_candidates[:sample_limit],
        'normalization_conflicts': candidate_conflicts[:sample_limit],
        'exact_title_asin_conflicts': exact_conflicts[:sample_limit],
        'identity_policy': 'review_only_no_automatic_merge',
    }
