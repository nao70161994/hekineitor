"""Normalized recommended-work catalog with deterministic legacy migration."""

import copy
import hashlib
import json
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


def _effective_signature(raw_work):
    title = work_title(raw_work)
    raw_url = raw_work.get('url', '') if isinstance(raw_work, dict) else ''
    return [title, safe_work_url(raw_url)]


def catalog_parity_report(catalog, fetishes, *, compound_rows=(), sample_limit=20):
    """Compare effective ordered legacy projections with catalog materialization."""
    validate_catalog(catalog)
    catalog_fetishes = materialize_fetish_works(catalog)
    catalog_compounds = materialize_compound_works(catalog)
    legacy_fetishes = {
        int(row['id']): [_effective_signature(work) for work in row.get('works') or []] for row in fetishes
    }
    legacy_compounds = {}
    if isinstance(compound_rows, dict):
        compound_rows = [{'key': key, 'works': works} for key, works in compound_rows.items()]
    for row in compound_rows or []:
        if 'id_a' in row and 'id_b' in row:
            key = f'{min(int(row["id_a"]), int(row["id_b"]))},{max(int(row["id_a"]), int(row["id_b"]))}'
        else:
            key = str(row.get('key') or '')
        if key:
            legacy_compounds[key] = [_effective_signature(work) for work in row.get('works') or []]
    effective_fetishes = {
        owner: [_effective_signature(work) for work in works] for owner, works in catalog_fetishes.items()
    }
    effective_compounds = {
        owner: [_effective_signature(work) for work in works] for owner, works in catalog_compounds.items()
    }
    mismatches = []
    counts = {'fetish': 0, 'compound': 0}
    for source, legacy, effective in (
        ('fetish', legacy_fetishes, effective_fetishes),
        ('compound', legacy_compounds, effective_compounds),
    ):
        for owner in sorted(set(legacy) | set(effective), key=str):
            if legacy.get(owner, []) == effective.get(owner, []):
                continue
            counts[source] += 1
            if len(mismatches) < max(0, min(int(sample_limit), 100)):
                mismatches.append(
                    {
                        'source': source,
                        'owner_id': owner,
                        'legacy_count': len(legacy.get(owner, [])),
                        'catalog_count': len(effective.get(owner, [])),
                        'legacy': legacy.get(owner, []),
                        'catalog': effective.get(owner, []),
                    }
                )
    mismatch_count = counts['fetish'] + counts['compound']
    return {
        'status': 'ok',
        'fetish_owner_count': len(set(legacy_fetishes) | set(effective_fetishes)),
        'compound_owner_count': len(set(legacy_compounds) | set(effective_compounds)),
        'fetish_mismatch_count': counts['fetish'],
        'compound_mismatch_count': counts['compound'],
        'mismatch_count': mismatch_count,
        'mismatches': mismatches,
        'pending_review_count': sum(row.get('status', 'pending') == 'pending' for row in catalog['review_queue']),
        'automated_parity_ok': mismatch_count == 0,
    }


def _catalog_editor(catalog):
    updated = copy.deepcopy(catalog)
    validate_catalog(updated)
    works = {row['work_id']: row for row in updated['works_master']}
    editions = {row['edition_id']: row for row in updated['work_editions']}
    aliases = {row['alias_id']: row for row in updated['work_aliases']}
    editions_by_key = {
        _edition_key(row.get('canonical_url')): row
        for row in updated['work_editions']
        if _edition_key(row.get('canonical_url'))
    }
    works_by_title = defaultdict(set)
    works_by_candidate = defaultdict(set)
    for row in updated['works_master']:
        works_by_title[row.get('normalized_title', '')].add(row['work_id'])
        works_by_candidate[work_title_candidate_key(row.get('canonical_title', ''))].add(row['work_id'])
    for row in updated['work_aliases']:
        works_by_title[row.get('normalized_alias', '')].add(row['work_id'])
        works_by_candidate[work_title_candidate_key(row.get('alias', ''))].add(row['work_id'])
    return updated, works, editions, aliases, editions_by_key, works_by_title, works_by_candidate


def _register_catalog_work(editor, raw_work):
    updated, works, editions, aliases, editions_by_key, works_by_title, works_by_candidate = editor
    title = work_title(raw_work)
    raw_url = raw_work.get('url', '') if isinstance(raw_work, dict) else ''
    url = safe_work_url(raw_url)
    if not title:
        raise ValueError('work title is required')
    edition_key = _edition_key(url)
    edition = editions_by_key.get(edition_key) if edition_key else None
    normalized_title = normalized_work_title(title)

    if edition is not None:
        work = works[edition['work_id']]
    else:
        asin = extract_asin(url)
        candidate_ids = works_by_title.get(normalized_title, set())
        if not asin and len(candidate_ids) == 1:
            work = works[next(iter(candidate_ids))]
        else:
            identity = _identity_key(title, url)
            work_id = _stable_id('wrk', identity)
            work = works.get(work_id)
            if work is None:
                work = {
                    'work_id': work_id,
                    'canonical_title': title,
                    'normalized_title': normalized_title,
                    'media_type': '',
                    'status': 'active',
                }
                works[work_id] = work
                updated['works_master'].append(work)
                works_by_title[normalized_title].add(work_id)
                works_by_candidate[work_title_candidate_key(title)].add(work_id)

    alias = None
    if title != work['canonical_title']:
        alias = next(
            (
                row
                for row in updated['work_aliases']
                if row['work_id'] == work['work_id'] and row.get('normalized_alias') == normalized_title
            ),
            None,
        )
        alias_id = alias['alias_id'] if alias is not None else _stable_id('wal', work['work_id'], normalized_title)
        if alias is None:
            alias = {
                'alias_id': alias_id,
                'work_id': work['work_id'],
                'alias': title,
                'normalized_alias': normalized_title,
            }
            aliases[alias_id] = alias
            updated['work_aliases'].append(alias)
            works_by_title[normalized_title].add(work['work_id'])
            works_by_candidate[work_title_candidate_key(title)].add(work['work_id'])

    if edition is None and edition_key:
        edition_id = _stable_id('wed', edition_key)
        edition = {
            'edition_id': edition_id,
            'work_id': work['work_id'],
            'asin': extract_asin(url),
            'canonical_url': url,
            'format': '',
            'status': 'active',
        }
        editions[edition_id] = edition
        editions_by_key[edition_key] = edition
        updated['work_editions'].append(edition)

    candidate_key = work_title_candidate_key(title)
    candidate_ids = sorted(works_by_candidate.get(candidate_key, set()))
    if len(candidate_ids) > 1:
        review_id = _stable_id('wrv', candidate_key)
        candidate_editions = [row for row in updated['work_editions'] if row['work_id'] in candidate_ids]
        candidate_titles = {
            row['canonical_title'] for row in updated['works_master'] if row['work_id'] in candidate_ids
        }
        candidate_titles.update(row['alias'] for row in updated['work_aliases'] if row['work_id'] in candidate_ids)
        asins = sorted({row.get('asin') for row in candidate_editions if row.get('asin')})
        review = next((row for row in updated['review_queue'] if row['review_id'] == review_id), None)
        if candidate_key and review is None:
            review = {'review_id': review_id, 'version': 0}
            updated['review_queue'].append(review)
        if review is not None and sorted(review.get('work_ids', [])) != candidate_ids:
            review.update(
                {
                    'review_type': 'normalization_conflict' if len(asins) > 1 else 'normalization_candidate',
                    'candidate_key': candidate_key,
                    'work_ids': candidate_ids,
                    'titles': sorted(candidate_titles),
                    'asins': asins,
                    'status': 'pending',
                    'decision': '',
                    'target_work_id': None,
                    'version': int(review.get('version', 0)) + 1,
                }
            )
    return work['work_id'], edition['edition_id'] if edition else None, alias['alias_id'] if alias else None


def _sort_catalog_rows(catalog):
    for collection, id_field in (
        ('works_master', 'work_id'),
        ('work_editions', 'edition_id'),
        ('work_aliases', 'alias_id'),
        ('review_queue', 'review_id'),
    ):
        catalog[collection].sort(key=lambda row: row[id_field])
    catalog['fetish_work_links'].sort(key=lambda row: (int(row['fetish_id']), int(row['position']), row['link_id']))
    catalog['compound_work_links'].sort(
        key=lambda row: (int(row['id_a']), int(row['id_b']), int(row['position']), row['link_id'])
    )


def catalog_digest(catalog):
    """Return a stable optimistic-concurrency token for a snapshot."""
    validate_catalog(catalog)
    payload = json.dumps(catalog, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def _admin_text(value, field, limit, *, required=False):
    value = str(value or '').strip()
    if required and not value:
        raise ValueError(f'{field} is required')
    if len(value) > limit:
        raise ValueError(f'{field} must be at most {limit} characters')
    return value


def _row_by_id(rows, field, value, label):
    row = next((item for item in rows if item.get(field) == value), None)
    if row is None:
        raise ValueError(f'{label} not found')
    return row


def admin_create_master(catalog, values):
    updated = copy.deepcopy(catalog)
    validate_catalog(updated)
    title = _admin_text(values.get('canonical_title'), 'canonical_title', 200, required=True)
    media_type = _admin_text(values.get('media_type'), 'media_type', 40)
    normalized = normalized_work_title(title)
    if not normalized:
        raise ValueError('canonical_title cannot normalize to empty')
    work_id = _stable_id('wrk', 'admin', normalized, media_type)
    if any(row['work_id'] == work_id for row in updated['works_master']):
        raise ValueError('work master already exists')
    updated['works_master'].append(
        {
            'work_id': work_id,
            'canonical_title': title,
            'normalized_title': normalized,
            'media_type': media_type,
            'status': 'active',
        }
    )
    _sort_catalog_rows(updated)
    validate_catalog(updated)
    return updated, work_id


def admin_update_master(catalog, work_id, values):
    updated = copy.deepcopy(catalog)
    validate_catalog(updated)
    row = _row_by_id(updated['works_master'], 'work_id', str(work_id), 'work master')
    if 'canonical_title' in values:
        title = _admin_text(values['canonical_title'], 'canonical_title', 200, required=True)
        row.update(canonical_title=title, normalized_title=normalized_work_title(title))
    if 'media_type' in values:
        row['media_type'] = _admin_text(values['media_type'], 'media_type', 40)
    if 'status' in values:
        status = str(values['status'] or '')
        if status not in {'active', 'inactive', 'archived'}:
            raise ValueError('invalid work status')
        row['status'] = status
    validate_catalog(updated)
    return updated


def admin_delete_master(catalog, work_id):
    updated = copy.deepcopy(catalog)
    validate_catalog(updated)
    work_id = str(work_id)
    _row_by_id(updated['works_master'], 'work_id', work_id, 'work master')
    if any(
        row['work_id'] == work_id for table in ('fetish_work_links', 'compound_work_links') for row in updated[table]
    ):
        raise ValueError('work master is still referenced by recommendation links')
    if any(work_id in row.get('work_ids', []) for row in updated['review_queue']):
        raise ValueError('work master is still referenced by review queue')
    updated['works_master'] = [row for row in updated['works_master'] if row['work_id'] != work_id]
    updated['work_editions'] = [row for row in updated['work_editions'] if row['work_id'] != work_id]
    updated['work_aliases'] = [row for row in updated['work_aliases'] if row['work_id'] != work_id]
    validate_catalog(updated)
    return updated


def admin_upsert_edition(catalog, values, *, edition_id=None):
    updated = copy.deepcopy(catalog)
    validate_catalog(updated)
    work_id = str(values.get('work_id') or '')
    _row_by_id(updated['works_master'], 'work_id', work_id, 'work master')
    url = safe_work_url(_admin_text(values.get('canonical_url'), 'canonical_url', 1000, required=True))
    if not url:
        raise ValueError('canonical_url is unsafe')
    key = _edition_key(url)
    duplicate = next((row for row in updated['work_editions'] if _edition_key(row.get('canonical_url')) == key), None)
    if duplicate is not None and duplicate['edition_id'] != edition_id:
        raise ValueError('edition URL or ASIN already exists')
    if edition_id is None:
        edition_id = _stable_id('wed', key)
        row = {'edition_id': edition_id}
        updated['work_editions'].append(row)
    else:
        edition_id = str(edition_id)
        row = _row_by_id(updated['work_editions'], 'edition_id', edition_id, 'work edition')
        if row['work_id'] != work_id and any(
            link.get('edition_id') == edition_id
            for table in ('fetish_work_links', 'compound_work_links')
            for link in updated[table]
        ):
            raise ValueError('referenced edition cannot move to another work master')
    status = str(values.get('status', row.get('status', 'active')) or '')
    if status not in {'active', 'inactive', 'archived'}:
        raise ValueError('invalid edition status')
    row.update(
        work_id=work_id,
        asin=extract_asin(url),
        canonical_url=url,
        format=_admin_text(values.get('format', row.get('format', '')), 'format', 40),
        status=status,
    )
    _sort_catalog_rows(updated)
    validate_catalog(updated)
    return updated, edition_id


def admin_delete_edition(catalog, edition_id):
    updated = copy.deepcopy(catalog)
    validate_catalog(updated)
    edition_id = str(edition_id)
    _row_by_id(updated['work_editions'], 'edition_id', edition_id, 'work edition')
    if any(
        link.get('edition_id') == edition_id
        for table in ('fetish_work_links', 'compound_work_links')
        for link in updated[table]
    ):
        raise ValueError('work edition is still referenced by recommendation links')
    updated['work_editions'] = [row for row in updated['work_editions'] if row['edition_id'] != edition_id]
    validate_catalog(updated)
    return updated


def admin_upsert_alias(catalog, values, *, alias_id=None):
    updated = copy.deepcopy(catalog)
    validate_catalog(updated)
    work_id = str(values.get('work_id') or '')
    _row_by_id(updated['works_master'], 'work_id', work_id, 'work master')
    alias = _admin_text(values.get('alias'), 'alias', 200, required=True)
    normalized = normalized_work_title(alias)
    if not normalized:
        raise ValueError('alias cannot normalize to empty')
    duplicate = next(
        (row for row in updated['work_aliases'] if row['work_id'] == work_id and row['normalized_alias'] == normalized),
        None,
    )
    if duplicate is not None and duplicate['alias_id'] != alias_id:
        raise ValueError('alias already exists for work master')
    if alias_id is None:
        alias_id = _stable_id('wal', work_id, normalized)
        row = {'alias_id': alias_id}
        updated['work_aliases'].append(row)
    else:
        alias_id = str(alias_id)
        row = _row_by_id(updated['work_aliases'], 'alias_id', alias_id, 'work alias')
        if row['work_id'] != work_id and any(
            link.get('alias_id') == alias_id
            for table in ('fetish_work_links', 'compound_work_links')
            for link in updated[table]
        ):
            raise ValueError('referenced alias cannot move to another work master')
    row.update(work_id=work_id, alias=alias, normalized_alias=normalized)
    _sort_catalog_rows(updated)
    validate_catalog(updated)
    return updated, alias_id


def admin_delete_alias(catalog, alias_id):
    updated = copy.deepcopy(catalog)
    validate_catalog(updated)
    alias_id = str(alias_id)
    _row_by_id(updated['work_aliases'], 'alias_id', alias_id, 'work alias')
    if any(
        link.get('alias_id') == alias_id
        for table in ('fetish_work_links', 'compound_work_links')
        for link in updated[table]
    ):
        raise ValueError('work alias is still referenced by recommendation links')
    updated['work_aliases'] = [row for row in updated['work_aliases'] if row['alias_id'] != alias_id]
    validate_catalog(updated)
    return updated


def admin_update_link(catalog, link_id, values):
    updated = copy.deepcopy(catalog)
    validate_catalog(updated)
    link = next(
        (
            row
            for table in ('fetish_work_links', 'compound_work_links')
            for row in updated[table]
            if row['link_id'] == str(link_id)
        ),
        None,
    )
    if link is None:
        raise ValueError('recommendation link not found')
    if 'context_label' in values:
        link['context_label'] = _admin_text(values['context_label'], 'context_label', 100)
    if 'recommendation_reason' in values:
        link['recommendation_reason'] = _admin_text(values['recommendation_reason'], 'recommendation_reason', 500)
    validate_catalog(updated)
    return updated


def admin_decide_review(catalog, review_id, values):
    updated = copy.deepcopy(catalog)
    validate_catalog(updated)
    review = _row_by_id(updated['review_queue'], 'review_id', str(review_id), 'work review')
    try:
        expected_version = int(values.get('expected_version'))
    except (TypeError, ValueError):
        raise ValueError('expected_version is required')
    if expected_version != int(review.get('version', 0)):
        raise ValueError('review version conflict')
    decision = str(values.get('decision') or '')
    if decision not in {'keep_separate', 'merge'}:
        raise ValueError('decision must be keep_separate or merge')
    target_id = None
    if decision == 'merge':
        target_id = str(values.get('target_work_id') or '')
        source_ids = set(review.get('work_ids', [])) - {target_id}
        if not target_id or target_id not in review.get('work_ids', []):
            raise ValueError('target_work_id must be one of review work_ids')
        masters = {row['work_id']: row for row in updated['works_master']}
        target_aliases = {
            row['normalized_alias']: row for row in updated['work_aliases'] if row['work_id'] == target_id
        }
        canonical_aliases = {}
        alias_replacements = {}
        remove_alias_ids = set()
        for source_id in source_ids:
            source = masters[source_id]
            normalized = normalized_work_title(source['canonical_title'])
            if normalized == masters[target_id]['normalized_title']:
                continue
            alias = target_aliases.get(normalized)
            if alias is None:
                alias = {
                    'alias_id': _stable_id('wal', target_id, normalized),
                    'work_id': target_id,
                    'alias': source['canonical_title'],
                    'normalized_alias': normalized,
                }
                updated['work_aliases'].append(alias)
                target_aliases[normalized] = alias
            canonical_aliases[source_id] = alias['alias_id']
        for alias in updated['work_aliases']:
            if alias['work_id'] not in source_ids:
                continue
            existing = target_aliases.get(alias['normalized_alias'])
            if existing is not None:
                alias_replacements[alias['alias_id']] = existing['alias_id']
                remove_alias_ids.add(alias['alias_id'])
            else:
                alias['work_id'] = target_id
                target_aliases[alias['normalized_alias']] = alias
        updated['work_aliases'] = [row for row in updated['work_aliases'] if row['alias_id'] not in remove_alias_ids]
        for row in updated['work_editions']:
            if row['work_id'] in source_ids:
                row['work_id'] = target_id
        for table in ('fetish_work_links', 'compound_work_links'):
            for row in updated[table]:
                if row['work_id'] in source_ids:
                    if not row.get('alias_id'):
                        row['alias_id'] = canonical_aliases.get(row['work_id'])
                    row['work_id'] = target_id
                if row.get('alias_id') in alias_replacements:
                    row['alias_id'] = alias_replacements[row['alias_id']]
        for table in ('fetish_work_links', 'compound_work_links'):
            owner_fields = ('fetish_id',) if table == 'fetish_work_links' else ('id_a', 'id_b')
            seen, kept, positions = set(), [], defaultdict(int)
            for row in sorted(
                updated[table],
                key=lambda item: (
                    *[int(item[field]) for field in owner_fields],
                    int(item['position']),
                    item['link_id'],
                ),
            ):
                owner = tuple(int(row[field]) for field in owner_fields)
                identity = (*owner, row['work_id'], row.get('edition_id'), row.get('alias_id'))
                if identity in seen:
                    continue
                seen.add(identity)
                row['position'] = positions[owner]
                positions[owner] += 1
                kept.append(row)
            updated[table] = kept
        updated['works_master'] = [row for row in updated['works_master'] if row['work_id'] not in source_ids]
        for item in updated['review_queue']:
            item['work_ids'] = sorted(
                {target_id if work_id in source_ids else work_id for work_id in item.get('work_ids', [])}
            )
            if item.get('target_work_id') in source_ids:
                item['target_work_id'] = target_id
    review['status'] = 'resolved'
    review['decision'] = decision
    review['target_work_id'] = target_id
    review['version'] = expected_version + 1
    review['updated_at'] = _admin_text(values.get('updated_at'), 'updated_at', 64)
    _sort_catalog_rows(updated)
    validate_catalog(updated)
    return updated


def apply_review_decisions(catalog, decision_manifest):
    """Apply a complete, input-locked set of human identity decisions."""
    validate_catalog(catalog)
    if not isinstance(decision_manifest, dict):
        raise ValueError('unsupported work review decision schema_version')
    try:
        schema_version = int(decision_manifest.get('schema_version', 0))
    except (TypeError, ValueError):
        raise ValueError('unsupported work review decision schema_version')
    if schema_version != 1:
        raise ValueError('unsupported work review decision schema_version')
    decisions = decision_manifest.get('decisions')
    if not isinstance(decisions, list) or not all(isinstance(row, dict) for row in decisions):
        raise ValueError('work review decisions must be a list')

    decision_ids = [str(row.get('review_id') or '') for row in decisions]
    if not all(decision_ids) or len(decision_ids) != len(set(decision_ids)):
        raise ValueError('work review decisions contain missing or duplicate review ids')

    catalog = copy.deepcopy(catalog)
    original_reviews = {row['review_id']: row for row in catalog['review_queue']}
    masters = {row['work_id']: row for row in catalog['works_master']}
    editions_by_work = defaultdict(list)
    for edition in catalog['work_editions']:
        editions_by_work[edition['work_id']].append(edition)
    for decision in decisions:
        review_id = str(decision['review_id'])
        if review_id in original_reviews or decision.get('review_type') != 'identity_override':
            continue
        candidate_key = str(decision.get('candidate_key') or '')
        work_ids = sorted(str(value) for value in decision.get('work_ids') or [])
        if (
            not candidate_key.startswith('identity_override:')
            or review_id != _stable_id('wrv', candidate_key)
            or len(work_ids) < 2
            or len(work_ids) != len(set(work_ids))
            or not set(work_ids).issubset(masters)
        ):
            raise ValueError(f'invalid identity override: {review_id}')
        asins = sorted(
            {
                edition.get('asin')
                for work_id in work_ids
                for edition in editions_by_work[work_id]
                if edition.get('asin')
            }
        )
        review = {
            'review_id': review_id,
            'review_type': 'identity_override',
            'candidate_key': candidate_key,
            'work_ids': work_ids,
            'titles': sorted({masters[work_id]['canonical_title'] for work_id in work_ids}),
            'asins': asins,
            'status': 'pending',
        }
        catalog['review_queue'].append(review)
        original_reviews[review_id] = review
    _sort_catalog_rows(catalog)
    validate_catalog(catalog)
    if set(decision_ids) != set(original_reviews):
        raise ValueError('work review decisions must cover the complete review queue')
    reviewed_at = _admin_text(decision_manifest.get('reviewed_at'), 'reviewed_at', 64, required=True)

    expected_replacements = {}

    def expected_resolved_id(work_id):
        seen = set()
        while work_id in expected_replacements and work_id not in seen:
            seen.add(work_id)
            work_id = expected_replacements[work_id]
        return work_id

    for decision in decisions:
        review = original_reviews[decision['review_id']]
        if str(decision.get('candidate_key') or '') != str(review.get('candidate_key') or ''):
            raise ValueError(f'work review candidate changed: {decision["review_id"]}')
        if decision.get('review_type') and decision.get('review_type') != review.get('review_type'):
            raise ValueError(f'work review type changed: {decision["review_id"]}')
        expected_ids = sorted(str(value) for value in decision.get('work_ids') or [])
        if not expected_ids or len(expected_ids) != len(set(expected_ids)):
            raise ValueError(f'invalid work review candidates: {decision["review_id"]}')
        if decision.get('decision') not in {'merge', 'keep_separate'}:
            raise ValueError(f'invalid work review decision: {decision["review_id"]}')
        target_id = decision.get('target_work_id')
        if decision['decision'] == 'merge' and target_id not in expected_ids:
            raise ValueError(f'invalid work review target: {decision["review_id"]}')
        if decision['decision'] == 'keep_separate' and target_id:
            raise ValueError(f'keep_separate review cannot have a target: {decision["review_id"]}')
        if decision['decision'] == 'merge':
            resolved_target = expected_resolved_id(target_id)
            for work_id in expected_ids:
                resolved_source = expected_resolved_id(work_id)
                if resolved_source != resolved_target:
                    expected_replacements[resolved_source] = resolved_target

    already_applied = all(review.get('status') == 'resolved' for review in original_reviews.values())
    if already_applied:
        for decision in decisions:
            review = original_reviews[decision['review_id']]
            expected_ids = sorted({expected_resolved_id(str(value)) for value in decision.get('work_ids') or []})
            expected_target = (
                expected_resolved_id(decision['target_work_id']) if decision['decision'] == 'merge' else None
            )
            if (
                review.get('decision') != decision['decision']
                or sorted(review.get('work_ids') or []) != expected_ids
                or review.get('target_work_id') != expected_target
            ):
                already_applied = False
                break
        if already_applied:
            return copy.deepcopy(catalog)

    for decision in decisions:
        review = original_reviews[decision['review_id']]
        expected_ids = sorted(str(value) for value in decision.get('work_ids') or [])
        if expected_ids != sorted(review.get('work_ids') or []):
            raise ValueError(f'work review candidates changed: {decision["review_id"]}')

    updated = copy.deepcopy(catalog)
    replacements = {}

    def resolved_id(work_id):
        seen = set()
        while work_id in replacements and work_id not in seen:
            seen.add(work_id)
            work_id = replacements[work_id]
        return work_id

    for decision in decisions:
        review_id = decision['review_id']
        review = _row_by_id(updated['review_queue'], 'review_id', review_id, 'work review')
        values = {
            'decision': decision['decision'],
            'updated_at': reviewed_at,
            'expected_version': int(review.get('version', 0)),
        }
        if decision['decision'] == 'merge':
            target_id = resolved_id(decision['target_work_id'])
            if target_id not in review.get('work_ids', []):
                raise ValueError(f'work review target was removed by an inconsistent earlier decision: {review_id}')
            values['target_work_id'] = target_id
            source_ids = set(review.get('work_ids', [])) - {target_id}
            updated = admin_decide_review(updated, review_id, values)
            for source_id in source_ids:
                replacements[source_id] = target_id
        else:
            updated = admin_decide_review(updated, review_id, values)

    validate_catalog(updated)
    return updated


def replace_fetish_works(catalog, fetish_id, raw_works):
    """Return a catalog copy with one fetish's ordered links replaced."""
    editor = _catalog_editor(catalog)
    updated = editor[0]
    fetish_id = int(fetish_id)
    previous_links = {row['link_id']: row for row in updated['fetish_work_links'] if int(row['fetish_id']) == fetish_id}
    updated['fetish_work_links'] = [row for row in updated['fetish_work_links'] if int(row['fetish_id']) != fetish_id]
    identities = set()
    for position, raw_work in enumerate(raw_works or []):
        work_id, edition_id, alias_id = _register_catalog_work(editor, raw_work)
        identity = (work_id, edition_id)
        if identity in identities:
            raise ValueError('duplicate work identity in fetish recommendations')
        identities.add(identity)
        link_id = _stable_id('fwl', fetish_id, work_id, edition_id, alias_id)
        previous = previous_links.get(link_id, {})
        updated['fetish_work_links'].append(
            {
                'link_id': link_id,
                'fetish_id': fetish_id,
                'work_id': work_id,
                'edition_id': edition_id,
                'alias_id': alias_id,
                'position': position,
                'context_label': previous.get('context_label', ''),
                'recommendation_reason': previous.get('recommendation_reason', ''),
            }
        )
    _sort_catalog_rows(updated)
    validate_catalog(updated)
    return updated


def sanitize_restored_works(raw_works):
    """Drop malformed and duplicate legacy entries instead of blocking an old backup restore."""
    sanitized = []
    seen = set()
    for raw_work in raw_works or []:
        title = work_title(raw_work)
        raw_url = raw_work.get('url', '') if isinstance(raw_work, dict) else ''
        identity = _identity_key(title, safe_work_url(raw_url))
        if not title or not identity or identity in seen:
            continue
        seen.add(identity)
        sanitized.append(copy.deepcopy(raw_work))
    return sanitized


def merge_restored_fetish_works(catalog, restored_fetishes):
    """Add links for restored legacy owners without replacing curated catalog data."""
    updated = copy.deepcopy(catalog)
    validate_catalog(updated)
    owners = {int(row['fetish_id']) for row in updated['fetish_work_links']}
    preserved_reviews = {row['review_id']: copy.deepcopy(row) for row in updated['review_queue']}
    for fetish in restored_fetishes or []:
        fetish_id = int(fetish['id'])
        works = sanitize_restored_works(fetish.get('works') if isinstance(fetish.get('works'), list) else [])
        if fetish_id in owners or not works:
            continue
        updated = replace_fetish_works(updated, fetish_id, works)
        owners.add(fetish_id)
    updated['review_queue'] = [preserved_reviews.get(review['review_id'], review) for review in updated['review_queue']]
    _sort_catalog_rows(updated)
    validate_catalog(updated)
    return updated


def replace_compound_works(catalog, id_a, id_b, raw_works):
    """Return a catalog copy with one canonical compound pair replaced."""
    editor = _catalog_editor(catalog)
    updated = editor[0]
    id_a, id_b = sorted((int(id_a), int(id_b)))
    if id_a == id_b:
        raise ValueError('compound link must reference two different fetishes')
    previous_links = {
        row['link_id']: row
        for row in updated['compound_work_links']
        if (int(row['id_a']), int(row['id_b'])) == (id_a, id_b)
    }
    updated['compound_work_links'] = [
        row for row in updated['compound_work_links'] if (int(row['id_a']), int(row['id_b'])) != (id_a, id_b)
    ]
    identities = set()
    for position, raw_work in enumerate(raw_works or []):
        work_id, edition_id, alias_id = _register_catalog_work(editor, raw_work)
        identity = (work_id, edition_id)
        if identity in identities:
            raise ValueError('duplicate work identity in compound recommendations')
        identities.add(identity)
        link_id = _stable_id('cwl', id_a, id_b, work_id, edition_id, alias_id)
        previous = previous_links.get(link_id, {})
        updated['compound_work_links'].append(
            {
                'link_id': link_id,
                'id_a': id_a,
                'id_b': id_b,
                'work_id': work_id,
                'edition_id': edition_id,
                'alias_id': alias_id,
                'position': position,
                'context_label': previous.get('context_label', ''),
                'recommendation_reason': previous.get('recommendation_reason', ''),
            }
        )
    _sort_catalog_rows(updated)
    validate_catalog(updated)
    return updated


def _remap_compound_links(catalog, old_id, new_id):
    old_id = int(old_id)
    new_id = int(new_id)
    grouped = defaultdict(list)
    for link in catalog['compound_work_links']:
        source_pair = (int(link['id_a']), int(link['id_b']))
        mapped = tuple(new_id if value == old_id else value for value in source_pair)
        id_a, id_b = sorted(mapped)
        if id_a == id_b:
            continue
        priority = 1 if old_id in source_pair else 0
        grouped[(id_a, id_b)].append((priority, int(link['position']), link))
    remapped = []
    for (id_a, id_b), candidates in sorted(grouped.items()):
        seen = set()
        position = 0
        for _priority, _old_position, link in sorted(
            candidates, key=lambda item: (item[0], item[1], item[2]['link_id'])
        ):
            identity = (link['work_id'], link.get('edition_id'))
            if identity in seen:
                continue
            seen.add(identity)
            alias_id = link.get('alias_id')
            remapped.append(
                {
                    **link,
                    'link_id': _stable_id('cwl', id_a, id_b, link['work_id'], link.get('edition_id'), alias_id),
                    'id_a': id_a,
                    'id_b': id_b,
                    'position': position,
                }
            )
            position += 1
    catalog['compound_work_links'] = remapped


def delete_fetish_references(catalog, fetish_id, *, replacement_id=None):
    """Remove one fetish owner and optionally merge its compound pairs into another owner."""
    updated = copy.deepcopy(catalog)
    validate_catalog(updated)
    fetish_id = int(fetish_id)
    updated['fetish_work_links'] = [
        link for link in updated['fetish_work_links'] if int(link['fetish_id']) != fetish_id
    ]
    if replacement_id is None:
        updated['compound_work_links'] = [
            link for link in updated['compound_work_links'] if fetish_id not in (int(link['id_a']), int(link['id_b']))
        ]
    else:
        _remap_compound_links(updated, fetish_id, int(replacement_id))
    _sort_catalog_rows(updated)
    validate_catalog(updated)
    return updated


def promote_fetish_references(catalog, old_id, new_id):
    """Return a copy with every owner reference moved to a newly allocated fetish ID."""
    updated = copy.deepcopy(catalog)
    validate_catalog(updated)
    old_id = int(old_id)
    new_id = int(new_id)
    for link in updated['fetish_work_links']:
        if int(link['fetish_id']) != old_id:
            continue
        link['fetish_id'] = new_id
        link['link_id'] = _stable_id('fwl', new_id, link['work_id'], link.get('edition_id'), link.get('alias_id'))
    _remap_compound_links(updated, old_id, new_id)
    _sort_catalog_rows(updated)
    validate_catalog(updated)
    return updated


def legacy_compound_projection(catalog):
    """Project normalized compound links back to the transitional JSON shape."""
    projected = {}
    for key, works in materialize_compound_works(catalog).items():
        projected[key] = [
            {'title': work['title'], 'url': work['url']} if work.get('url') else work['title'] for work in works
        ]
    return projected
