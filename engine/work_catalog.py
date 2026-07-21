"""Normalized recommended-work catalog with deterministic legacy migration."""

import hashlib
import re
from collections import defaultdict

from work_utils import normalized_work_title, safe_work_url, work_title, work_title_candidate_key

CATALOG_SCHEMA_VERSION = 1
_ASIN_RE = re.compile(r'/dp/([A-Z0-9]{10})', re.IGNORECASE)


def _stable_id(prefix, *parts):
    payload = '\x1f'.join(str(part or '') for part in parts)
    digest = hashlib.sha256(payload.encode('utf-8')).hexdigest()[:20]
    return f'{prefix}_{digest}'


def extract_asin(url):
    match = _ASIN_RE.search(str(url or ''))
    return match.group(1).upper() if match else ''


def _identity_key(title, url):
    asin = extract_asin(url)
    if asin:
        return f'asin:{asin}'
    title_key = normalized_work_title(title)
    if title_key:
        return f'title:{title_key}'
    url = safe_work_url(url)
    return f'url:{url}' if url else ''


def _edition_key(url):
    url = safe_work_url(url)
    if not url:
        return ''
    asin = extract_asin(url)
    return f'asin:{asin}' if asin else f'url:{url}'


def _empty_catalog():
    return {
        'schema_version': CATALOG_SCHEMA_VERSION,
        'works_master': [],
        'work_editions': [],
        'work_aliases': [],
        'fetish_work_links': [],
        'compound_work_links': [],
        'review_queue': [],
    }


def build_catalog_from_inline(fetishes, *, compound_rows=()):
    """Build a deterministic normalized catalog without guessing ambiguous identities."""
    catalog = _empty_catalog()
    works_by_identity = {}
    editions_by_key = {}
    aliases_by_key = {}
    observed_by_candidate = defaultdict(list)

    def register_work(raw_work):
        title = work_title(raw_work)
        raw_url = raw_work.get('url', '') if isinstance(raw_work, dict) else ''
        url = safe_work_url(raw_url)
        identity = _identity_key(title, url)
        if not identity or not title:
            return None

        work = works_by_identity.get(identity)
        if work is None:
            work_id = _stable_id('wrk', identity)
            work = {
                'work_id': work_id,
                'canonical_title': title,
                'normalized_title': normalized_work_title(title),
                'media_type': '',
                'status': 'active',
            }
            works_by_identity[identity] = work
            catalog['works_master'].append(work)
        work_id = work['work_id']

        alias_id = None
        if title != work['canonical_title']:
            alias_key = (work_id, normalized_work_title(title))
            alias = aliases_by_key.get(alias_key)
            if alias is None:
                alias = {
                    'alias_id': _stable_id('wal', work_id, alias_key[1]),
                    'work_id': work_id,
                    'alias': title,
                    'normalized_alias': alias_key[1],
                }
                aliases_by_key[alias_key] = alias
                catalog['work_aliases'].append(alias)
            alias_id = alias['alias_id']

        edition_id = None
        edition_key = _edition_key(url)
        if edition_key:
            edition = editions_by_key.get(edition_key)
            if edition is None:
                edition = {
                    'edition_id': _stable_id('wed', edition_key),
                    'work_id': work_id,
                    'asin': extract_asin(url),
                    'canonical_url': url,
                    'format': '',
                    'status': 'active',
                }
                editions_by_key[edition_key] = edition
                catalog['work_editions'].append(edition)
            elif edition['work_id'] != work_id:
                raise ValueError(f'edition identity collision: {edition_key}')
            edition_id = edition['edition_id']

        candidate_key = work_title_candidate_key(title)
        if candidate_key:
            observed_by_candidate[candidate_key].append(
                {
                    'work_id': work_id,
                    'edition_id': edition_id,
                    'title': title,
                    'asin': extract_asin(url),
                }
            )
        return work_id, edition_id, alias_id

    for fetish in sorted(fetishes, key=lambda row: int(row.get('id', 0))):
        fetish_id = int(fetish['id'])
        for position, raw_work in enumerate(fetish.get('works') or []):
            registered = register_work(raw_work)
            if registered is None:
                continue
            work_id, edition_id, alias_id = registered
            link = {
                'link_id': _stable_id('fwl', fetish_id, work_id, edition_id, alias_id),
                'fetish_id': fetish_id,
                'work_id': work_id,
                'edition_id': edition_id,
                'alias_id': alias_id,
                'position': position,
                'context_label': '',
                'recommendation_reason': '',
            }
            catalog['fetish_work_links'].append(link)

    known_fetish_ids = {int(fetish['id']) for fetish in fetishes}
    normalized_compounds = sorted(
        compound_rows or [],
        key=lambda row: (min(int(row['id_a']), int(row['id_b'])), max(int(row['id_a']), int(row['id_b']))),
    )
    for compound in normalized_compounds:
        id_a = min(int(compound['id_a']), int(compound['id_b']))
        id_b = max(int(compound['id_a']), int(compound['id_b']))
        if id_a == id_b:
            raise ValueError(f'compound link must reference two different fetishes: {id_a}')
        missing_ids = sorted({id_a, id_b} - known_fetish_ids)
        if missing_ids:
            raise ValueError(f'compound link references unknown fetish ids: {missing_ids}')
        for position, raw_work in enumerate(compound.get('works') or []):
            registered = register_work(raw_work)
            if registered is None:
                continue
            work_id, edition_id, alias_id = registered
            link = {
                'link_id': _stable_id('cwl', id_a, id_b, work_id, edition_id, alias_id),
                'id_a': id_a,
                'id_b': id_b,
                'work_id': work_id,
                'edition_id': edition_id,
                'alias_id': alias_id,
                'position': position,
                'context_label': '',
                'recommendation_reason': '',
            }
            catalog['compound_work_links'].append(link)

    for candidate_key, observations in sorted(observed_by_candidate.items()):
        work_ids = sorted({row['work_id'] for row in observations})
        if len(work_ids) <= 1:
            continue
        asins = sorted({row['asin'] for row in observations if row['asin']})
        catalog['review_queue'].append(
            {
                'review_id': _stable_id('wrv', candidate_key),
                'review_type': 'normalization_conflict' if len(asins) > 1 else 'normalization_candidate',
                'candidate_key': candidate_key,
                'work_ids': work_ids,
                'titles': sorted({row['title'] for row in observations}),
                'asins': asins,
                'status': 'pending',
            }
        )

    for key in ('works_master', 'work_editions', 'work_aliases', 'review_queue'):
        id_field = {
            'works_master': 'work_id',
            'work_editions': 'edition_id',
            'work_aliases': 'alias_id',
            'review_queue': 'review_id',
        }[key]
        catalog[key].sort(key=lambda row: row[id_field])
    catalog['fetish_work_links'].sort(key=lambda row: (row['fetish_id'], row['position'], row['link_id']))
    catalog['compound_work_links'].sort(key=lambda row: (row['id_a'], row['id_b'], row['position'], row['link_id']))
    validate_catalog(catalog)
    return catalog


def validate_catalog(catalog):
    if int(catalog.get('schema_version', 0)) != CATALOG_SCHEMA_VERSION:
        raise ValueError('unsupported work catalog schema_version')
    collections = {
        'works_master': 'work_id',
        'work_editions': 'edition_id',
        'work_aliases': 'alias_id',
        'fetish_work_links': 'link_id',
        'compound_work_links': 'link_id',
        'review_queue': 'review_id',
    }
    ids = {}
    for name, id_field in collections.items():
        rows = catalog.get(name)
        if not isinstance(rows, list):
            raise ValueError(f'{name} must be a list')
        values = [str(row.get(id_field) or '') for row in rows]
        if not all(values) or len(values) != len(set(values)):
            raise ValueError(f'{name} contains missing or duplicate ids')
        ids[name] = set(values)

    work_ids = ids['works_master']
    edition_work_ids = {}
    for edition in catalog['work_editions']:
        if edition.get('work_id') not in work_ids:
            raise ValueError('work edition references unknown work_id')
        edition_work_ids[edition['edition_id']] = edition['work_id']
        url = edition.get('canonical_url') or ''
        if url and not safe_work_url(url):
            raise ValueError('work edition contains unsafe canonical_url')
    alias_work_ids = {}
    for alias in catalog['work_aliases']:
        if alias.get('work_id') not in work_ids:
            raise ValueError('work alias references unknown work_id')
        alias_work_ids[alias['alias_id']] = alias['work_id']

    for review in catalog['review_queue']:
        review_work_ids = review.get('work_ids')
        if not isinstance(review_work_ids, list) or not set(review_work_ids).issubset(work_ids):
            raise ValueError('review queue references unknown work_id')
        target_work_id = review.get('target_work_id')
        if target_work_id and target_work_id not in work_ids:
            raise ValueError('review queue target references unknown work_id')

    for table in ('fetish_work_links', 'compound_work_links'):
        seen_positions = set()
        for link in catalog[table]:
            work_id = link.get('work_id')
            if work_id not in work_ids:
                raise ValueError(f'{table} references unknown work_id')
            edition_id = link.get('edition_id')
            if edition_id and edition_work_ids.get(edition_id) != work_id:
                raise ValueError(f'{table} edition does not belong to work')
            alias_id = link.get('alias_id')
            if alias_id and alias_work_ids.get(alias_id) != work_id:
                raise ValueError(f'{table} alias does not belong to work')
            owner = (link.get('fetish_id'),) if table == 'fetish_work_links' else (link.get('id_a'), link.get('id_b'))
            position = int(link.get('position', -1))
            if position < 0:
                raise ValueError(f'{table} contains a negative position')
            if table == 'compound_work_links' and int(link.get('id_a', -1)) >= int(link.get('id_b', -1)):
                raise ValueError('compound_work_links contains a non-canonical pair')
            position_key = (*owner, position)
            if position_key in seen_positions:
                raise ValueError(f'{table} contains duplicate owner position')
            seen_positions.add(position_key)
    return True


def validate_catalog_fetish_references(catalog, fetish_ids):
    validate_catalog(catalog)
    known_ids = {int(value) for value in fetish_ids}
    referenced_ids = {int(link['fetish_id']) for link in catalog['fetish_work_links']}
    referenced_ids.update(int(link[field]) for link in catalog['compound_work_links'] for field in ('id_a', 'id_b'))
    missing_ids = sorted(referenced_ids - known_ids)
    if missing_ids:
        raise ValueError(f'work catalog references unknown fetish ids: {missing_ids}')
    return True


def _catalog_indexes(catalog):
    validate_catalog(catalog)
    return (
        {row['work_id']: row for row in catalog['works_master']},
        {row['edition_id']: row for row in catalog['work_editions']},
        {row['alias_id']: row for row in catalog['work_aliases']},
    )


def materialize_link_work(link, *, works, editions, aliases):
    work = works[link['work_id']]
    alias = aliases.get(link.get('alias_id'))
    edition = editions.get(link.get('edition_id'))
    return {
        'title': alias['alias'] if alias else work['canonical_title'],
        'url': edition['canonical_url'] if edition else '',
        'work_id': work['work_id'],
        'edition_id': edition['edition_id'] if edition else None,
        'alias_id': alias['alias_id'] if alias else None,
        'context_label': str(link.get('context_label') or ''),
        'recommendation_reason': str(link.get('recommendation_reason') or ''),
    }


def materialize_fetish_works(catalog):
    works, editions, aliases = _catalog_indexes(catalog)
    result = defaultdict(list)
    for link in sorted(catalog['fetish_work_links'], key=lambda row: (row['fetish_id'], row['position'])):
        result[int(link['fetish_id'])].append(
            materialize_link_work(link, works=works, editions=editions, aliases=aliases)
        )
    return dict(result)


def materialize_compound_works(catalog):
    works, editions, aliases = _catalog_indexes(catalog)
    result = defaultdict(list)
    for link in sorted(catalog['compound_work_links'], key=lambda row: (row['id_a'], row['id_b'], row['position'])):
        key = f'{min(int(link["id_a"]), int(link["id_b"]))},{max(int(link["id_a"]), int(link["id_b"]))}'
        result[key].append(materialize_link_work(link, works=works, editions=editions, aliases=aliases))
    return dict(result)
