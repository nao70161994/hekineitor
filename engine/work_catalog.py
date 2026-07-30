"""Normalized recommended-work catalog with deterministic legacy migration."""

import copy
import hashlib
import json
import re
from collections import defaultdict
from datetime import datetime, timezone

from work_utils import normalized_work_title, safe_work_url, work_title, work_title_candidate_key

CATALOG_SCHEMA_VERSION = 2
SUPPORTED_CATALOG_SCHEMA_VERSIONS = frozenset({1, CATALOG_SCHEMA_VERSION})
_ASIN_RE = re.compile(r'/dp/([A-Z0-9]{10})', re.IGNORECASE)
_IDENTIFIER_SCHEME_RE = re.compile(r'^[a-z][a-z0-9._-]{0,31}$')
_IDENTIFIER_AUTHORITY_RE = re.compile(r'^[a-z0-9][a-z0-9._:-]{0,99}$')
_ISBN_CLEAN_RE = re.compile(r'[^0-9Xx]')


def _stable_id(prefix, *parts):
    payload = '\x1f'.join(str(part or '') for part in parts)
    digest = hashlib.sha256(payload.encode('utf-8')).hexdigest()[:20]
    return f'{prefix}_{digest}'


def extract_asin(url):
    match = _ASIN_RE.search(str(url or ''))
    return match.group(1).upper() if match else ''


def normalize_isbn(value):
    """Validate ISBN-10/13 and return the canonical ISBN-13 digits."""
    cleaned = _ISBN_CLEAN_RE.sub('', str(value or ''))
    if len(cleaned) == 10:
        if not cleaned[:9].isdigit() or (not cleaned[-1].isdigit() and cleaned[-1].upper() != 'X'):
            raise ValueError('invalid ISBN-10')
        digits = [int(char) for char in cleaned[:9]]
        check = 10 if cleaned[-1].upper() == 'X' else int(cleaned[-1])
        if (sum((10 - index) * digit for index, digit in enumerate(digits)) + check) % 11:
            raise ValueError('invalid ISBN-10 checksum')
        prefix = f'978{cleaned[:9]}'
        total = sum((1 if index % 2 == 0 else 3) * int(char) for index, char in enumerate(prefix))
        return f'{prefix}{(10 - total % 10) % 10}'
    if len(cleaned) == 13 and cleaned.isdigit():
        total = sum((1 if index % 2 == 0 else 3) * int(char) for index, char in enumerate(cleaned[:12]))
        if (10 - total % 10) % 10 != int(cleaned[-1]):
            raise ValueError('invalid ISBN-13 checksum')
        return cleaned
    raise ValueError('ISBN must contain 10 or 13 digits')


def normalize_edition_identifier(*, scheme, authority, value):
    """Return one canonical non-ASIN edition identifier tuple."""
    normalized_scheme = str(scheme or '').strip().lower()
    normalized_authority = str(authority or '').strip().lower()
    normalized_value = str(value or '').strip()
    if not _IDENTIFIER_SCHEME_RE.fullmatch(normalized_scheme):
        raise ValueError('invalid edition identifier scheme')
    if normalized_scheme == 'asin':
        raise ValueError('ASIN must remain in work_editions.asin')
    if normalized_scheme == 'isbn':
        normalized_authority = 'isbn'
        normalized_value = normalize_isbn(normalized_value)
    else:
        if not _IDENTIFIER_AUTHORITY_RE.fullmatch(normalized_authority):
            raise ValueError('invalid edition identifier authority')
        if not normalized_value or len(normalized_value) > 200 or any(ord(char) < 32 for char in normalized_value):
            raise ValueError('invalid edition identifier value')
    return normalized_scheme, normalized_authority, normalized_value


def build_edition_identifier(edition_id, *, scheme, authority='', value):
    """Build a deterministic canonical identifier row."""
    edition_id = str(edition_id or '').strip()
    if not edition_id:
        raise ValueError('edition_id is required')
    scheme, authority, value = normalize_edition_identifier(
        scheme=scheme,
        authority=authority,
        value=value,
    )
    return {
        'identifier_id': _stable_id('wei', scheme, authority, value),
        'edition_id': edition_id,
        'scheme': scheme,
        'authority': authority,
        'value': value,
    }


def upgrade_catalog_schema(catalog):
    """Upgrade a v1 snapshot to v2 without inferring any identifiers."""
    if not isinstance(catalog, dict):
        raise ValueError('work catalog must be an object')
    try:
        schema_version = int(catalog.get('schema_version', 0))
    except (TypeError, ValueError):
        raise ValueError('unsupported work catalog schema_version')
    if schema_version not in SUPPORTED_CATALOG_SCHEMA_VERSIONS:
        raise ValueError('unsupported work catalog schema_version')
    upgraded = copy.deepcopy(catalog)
    if schema_version == 1:
        for edition in upgraded.get('work_editions', []):
            edition.setdefault('edition_title', '')
            edition.setdefault('publisher', '')
        upgraded['schema_version'] = CATALOG_SCHEMA_VERSION
        upgraded['work_edition_identifiers'] = []
    elif 'work_edition_identifiers' not in upgraded:
        raise ValueError('work_edition_identifiers must be a list')
    validate_catalog(upgraded)
    return upgraded


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
        'work_edition_identifiers': [],
        'fetish_work_links': [],
        'compound_work_links': [],
        'review_queue': [],
    }


def _seed_title_normalizations(seed_overrides):
    if seed_overrides is None:
        return {}
    if not isinstance(seed_overrides, dict):
        raise ValueError('unsupported work catalog seed overrides schema_version')
    try:
        schema_version = int(seed_overrides.get('schema_version', 0))
    except (TypeError, ValueError):
        raise ValueError('unsupported work catalog seed overrides schema_version')
    if schema_version != 1:
        raise ValueError('unsupported work catalog seed overrides schema_version')
    rows = seed_overrides.get('title_normalizations')
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError('work catalog title_normalizations must be a list')
    result = {}
    for row in rows:
        display_title = str(row.get('display_title') or '').strip()
        canonical_title = str(row.get('canonical_title') or '').strip()
        context_label = str(row.get('context_label') or '').strip()
        if not display_title or not canonical_title:
            raise ValueError('work catalog title normalization requires display and canonical titles')
        if display_title in result:
            raise ValueError(f'duplicate work catalog title normalization: {display_title}')
        result[display_title] = {
            'canonical_title': canonical_title,
            'context_label': context_label,
        }
    return result


def _seed_removal_titles(seed_overrides):
    rows = seed_overrides.get('remove_display_titles', []) if isinstance(seed_overrides, dict) else []
    if not isinstance(rows, list):
        raise ValueError('work catalog remove_display_titles must be a list')
    titles = [str(value or '').strip() for value in rows]
    if not all(titles) or len(titles) != len(set(titles)):
        raise ValueError('work catalog remove_display_titles contains blank or duplicate titles')
    return titles


def build_catalog_from_inline(fetishes, *, compound_rows=(), seed_overrides=None):
    """Build a deterministic normalized catalog without guessing ambiguous identities."""
    catalog = _empty_catalog()
    title_normalizations = _seed_title_normalizations(seed_overrides)
    removal_titles = set(_seed_removal_titles(seed_overrides))
    works_by_identity = {}
    editions_by_key = {}
    aliases_by_key = {}
    observed_by_candidate = defaultdict(list)

    def register_work(raw_work):
        title = work_title(raw_work)
        if title in removal_titles:
            return None
        normalization = title_normalizations.get(title, {})
        canonical_title = normalization.get('canonical_title', title)
        raw_url = raw_work.get('url', '') if isinstance(raw_work, dict) else ''
        url = safe_work_url(raw_url)
        # Keep the legacy display title in the stable identity input. Seed
        # normalizations improve catalog responsibility without changing
        # published work IDs or reviewed identity decisions.
        identity = _identity_key(title, url)
        if not identity or not title:
            return None

        work = works_by_identity.get(identity)
        if work is None:
            work_id = _stable_id('wrk', identity)
            work = {
                'work_id': work_id,
                'canonical_title': canonical_title,
                'normalized_title': normalized_work_title(canonical_title),
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
                    'edition_title': '',
                    'publisher': '',
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
        return work_id, edition_id, alias_id, normalization.get('context_label', '')

    for fetish in sorted(fetishes, key=lambda row: int(row.get('id', 0))):
        fetish_id = int(fetish['id'])
        for position, raw_work in enumerate(fetish.get('works') or []):
            registered = register_work(raw_work)
            if registered is None:
                continue
            work_id, edition_id, alias_id, context_label = registered
            link = {
                'link_id': _stable_id('fwl', fetish_id, work_id, edition_id, alias_id),
                'fetish_id': fetish_id,
                'work_id': work_id,
                'edition_id': edition_id,
                'alias_id': alias_id,
                'position': position,
                'context_label': context_label,
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
            work_id, edition_id, alias_id, context_label = registered
            link = {
                'link_id': _stable_id('cwl', id_a, id_b, work_id, edition_id, alias_id),
                'id_a': id_a,
                'id_b': id_b,
                'work_id': work_id,
                'edition_id': edition_id,
                'alias_id': alias_id,
                'position': position,
                'context_label': context_label,
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

    for key in ('works_master', 'work_editions', 'work_edition_identifiers', 'work_aliases', 'review_queue'):
        id_field = {
            'works_master': 'work_id',
            'work_editions': 'edition_id',
            'work_edition_identifiers': 'identifier_id',
            'work_aliases': 'alias_id',
            'review_queue': 'review_id',
        }[key]
        catalog[key].sort(key=lambda row: row[id_field])
    catalog['fetish_work_links'].sort(key=lambda row: (row['fetish_id'], row['position'], row['link_id']))
    catalog['compound_work_links'].sort(key=lambda row: (row['id_a'], row['id_b'], row['position'], row['link_id']))
    validate_catalog(catalog)
    return catalog


def validate_catalog(catalog):
    if not isinstance(catalog, dict):
        raise ValueError('work catalog must be an object')
    try:
        schema_version = int(catalog.get('schema_version', 0))
    except (TypeError, ValueError):
        raise ValueError('unsupported work catalog schema_version')
    if schema_version not in SUPPORTED_CATALOG_SCHEMA_VERSIONS:
        raise ValueError('unsupported work catalog schema_version')
    collections = {
        'works_master': 'work_id',
        'work_editions': 'edition_id',
        'work_aliases': 'alias_id',
        'fetish_work_links': 'link_id',
        'compound_work_links': 'link_id',
        'review_queue': 'review_id',
    }
    if schema_version >= 2:
        collections['work_edition_identifiers'] = 'identifier_id'
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

        if schema_version >= 2:
            for field in ('edition_title', 'publisher'):
                value = edition.get(field)
                if not isinstance(value, str) or len(value) > 200:
                    raise ValueError(f'work edition contains invalid {field}')
    identifier_keys = set()
    for identifier in catalog.get('work_edition_identifiers', []):
        edition_id = str(identifier.get('edition_id') or '')
        if edition_id not in edition_work_ids:
            raise ValueError('work edition identifier references unknown edition_id')
        canonical = build_edition_identifier(
            edition_id,
            scheme=identifier.get('scheme'),
            authority=identifier.get('authority'),
            value=identifier.get('value'),
        )
        if identifier != canonical:
            raise ValueError('work edition identifier is not canonical')
        key = (canonical['scheme'], canonical['authority'], canonical['value'])
        if key in identifier_keys:
            raise ValueError('duplicate work edition identifier')
        identifier_keys.add(key)

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


_CORRECTION_ALLOWED_FIELDS = frozenset(
    {
        'correction_id',
        'type',
        'expected_work',
        'target_work',
        'edition_updates',
        'edition_additions',
        'edition_removals',
        'alias_additions',
        'alias_references',
        'alias_removals',
        'link_updates',
        'link_removals',
        'review_updates',
    }
)
_CORRECTION_EXACT_WRAPPER_FIELDS = {
    'edition_updates': frozenset({'expected'}),
    'edition_additions': frozenset({'target', 'identifiers'}),
    'edition_removals': frozenset({'expected', 'expected_identifiers'}),
    'alias_additions': frozenset({'target'}),
    'alias_references': frozenset({'expected'}),
    'review_updates': frozenset({'expected', 'target', 'accepted_source_updated_at'}),
}
_CORRECTION_OPTIONAL_WRAPPER_FIELDS = {
    'alias_removals': (
        frozenset({'expected', 'allow_missing'}),
        frozenset({'expected'}),
    ),
    'link_updates': (
        frozenset(
            {
                'table',
                'expected',
                'edition_id',
                'alias_id',
                'context_label',
                'source_url',
                'source_title',
                'allow_missing',
            }
        ),
        frozenset({'table', 'expected'}),
    ),
    'link_removals': (
        frozenset({'table', 'expected', 'source_url', 'source_title', 'allow_missing'}),
        frozenset({'table', 'expected'}),
    ),
}
_CORRECTION_V2_FIELDS = frozenset({'edition_additions', 'edition_removals', 'alias_additions'})
_CORRECTION_V3_FIELDS = frozenset({'alias_references', 'link_removals'})


def _validate_correction_manifest_fields(corrections, schema_version):
    """Reject misspelled manifest fields before projection or catalog mutation."""
    for correction in corrections:
        correction_id = str(correction.get('correction_id') or '')
        if set(correction) - _CORRECTION_ALLOWED_FIELDS:
            raise ValueError(f'work catalog correction contains unknown fields: {correction_id}')
        if schema_version == 1 and set(correction) & _CORRECTION_V2_FIELDS:
            raise ValueError(f'work catalog correction schema_version 1 contains version 2 fields: {correction_id}')
        if schema_version < 3 and set(correction) & _CORRECTION_V3_FIELDS:
            raise ValueError(
                f'work catalog correction schema_version {schema_version} contains version 3 fields: {correction_id}'
            )
        wrapper_fields = set(_CORRECTION_EXACT_WRAPPER_FIELDS) | set(_CORRECTION_OPTIONAL_WRAPPER_FIELDS)
        for field in wrapper_fields:
            wrappers = correction.get(field, [])
            if not isinstance(wrappers, list) or not all(isinstance(wrapper, dict) for wrapper in wrappers):
                raise ValueError(f'work catalog correction has invalid {field}: {correction_id}')
        for field, allowed in _CORRECTION_EXACT_WRAPPER_FIELDS.items():
            for wrapper in correction.get(field, []):
                if set(wrapper) != allowed:
                    raise ValueError(f'work catalog correction has invalid {field}: {correction_id}')
        for field, (allowed, required) in _CORRECTION_OPTIONAL_WRAPPER_FIELDS.items():
            for wrapper in correction.get(field, []):
                if not required <= set(wrapper) <= allowed:
                    raise ValueError(f'work catalog correction has invalid {field}: {correction_id}')
        if any({'source_url', 'source_title'} & set(wrapper) for wrapper in correction.get('link_updates', [])) and (
            schema_version != 3 or correction.get('type') != 'link_rebind'
        ):
            raise ValueError(f'work catalog correction has invalid link_updates: {correction_id}')
        if any('source_title' in wrapper for wrapper in correction.get('link_removals', [])) and (
            schema_version != 3 or correction.get('type') != 'quarantine_recommendation'
        ):
            raise ValueError(f'work catalog correction has invalid link_removals: {correction_id}')


def _correction_final_link_position(corrections, table, expected):
    """Return the only final position implied by manifest link removals."""
    owner_fields = ('fetish_id',) if table == 'fetish_work_links' else ('id_a', 'id_b')
    owner = tuple(expected.get(field) for field in owner_fields)
    position = int(expected.get('position', -1))
    removed_before = 0
    for correction in corrections:
        for removal in correction.get('link_removals') or []:
            removal_expected = removal.get('expected') or {}
            if (
                removal.get('table') == table
                and tuple(removal_expected.get(field) for field in owner_fields) == owner
                and int(removal_expected.get('position', -1)) < position
            ):
                removed_before += 1
    return position - removed_before


def project_approved_inline_corrections(
    fetishes,
    *,
    compound_rows=(),
    corrections,
    direction='forward',
    tables=None,
    strict=True,
    sample_limit=20,
):
    """Project exact correction-manifest display deltas onto legacy inline rows."""
    if direction not in {'forward', 'reverse'}:
        raise ValueError('unsupported approved inline projection direction')
    selected_tables = {'fetish_work_links', 'compound_work_links'} if tables is None else set(tables)
    if not selected_tables <= {'fetish_work_links', 'compound_work_links'}:
        raise ValueError('unsupported approved inline projection table')
    if not isinstance(corrections, dict):
        raise ValueError('unsupported work catalog corrections schema_version')
    try:
        schema_version = int(corrections.get('schema_version', 0))
        catalog_schema_version = int(corrections.get('catalog_schema_version', 0))
    except (TypeError, ValueError):
        raise ValueError('unsupported work catalog corrections schema_version')
    if schema_version not in {1, 2, 3} or catalog_schema_version not in SUPPORTED_CATALOG_SCHEMA_VERSIONS:
        raise ValueError('unsupported work catalog corrections schema_version')
    correction_rows = corrections.get('corrections')
    if not isinstance(correction_rows, list) or not all(isinstance(row, dict) for row in correction_rows):
        raise ValueError('work catalog corrections must be a list')
    correction_ids = [str(row.get('correction_id') or '') for row in correction_rows]
    if not all(correction_ids) or len(correction_ids) != len(set(correction_ids)):
        raise ValueError('work catalog corrections contain missing or duplicate correction ids')
    _validate_correction_manifest_fields(correction_rows, schema_version)
    for correction in correction_rows:
        if correction.get('type') != 'quarantine_recommendation':
            continue
        expected_work = correction.get('expected_work')
        target_work = correction.get('target_work')
        forbidden_rows = (
            'edition_updates',
            'edition_additions',
            'edition_removals',
            'alias_additions',
            'alias_removals',
            'link_updates',
            'review_updates',
        )
        if (
            schema_version != 3
            or not isinstance(expected_work, dict)
            or not isinstance(target_work, dict)
            or not expected_work.get('work_id')
            or target_work.get('work_id') != expected_work.get('work_id')
            or target_work.get('status') != 'archived'
            or not correction.get('link_removals')
            or any(correction.get(field) for field in forbidden_rows)
        ):
            raise ValueError(
                f'work catalog correction has invalid quarantine projection: {correction.get("correction_id", "")}'
            )
    for correction in correction_rows:
        if correction.get('type') != 'link_rebind':
            continue
        expected_work = correction.get('expected_work')
        alias_reference_rows = correction.get('alias_references') or []

        def valid_alias_reference(reference):
            if not isinstance(reference, dict) or not isinstance(reference.get('expected'), dict):
                return False
            expected = reference['expected']
            alias = str(expected.get('alias') or '').strip()
            normalized_alias = normalized_work_title(alias)
            return bool(alias) and expected == {
                'alias_id': _stable_id('wal', expected_work.get('work_id'), normalized_alias),
                'work_id': expected_work.get('work_id'),
                'alias': alias,
                'normalized_alias': normalized_alias,
            }

        valid_alias_references = (
            all(valid_alias_reference(reference) for reference in alias_reference_rows)
            if isinstance(expected_work, dict)
            else False
        )
        forbidden_rows = (
            'edition_updates',
            'edition_additions',
            'edition_removals',
            'alias_additions',
            'alias_removals',
            'link_removals',
            'review_updates',
        )
        if (
            schema_version != 3
            or not isinstance(expected_work, dict)
            or correction.get('target_work') != expected_work
            or not alias_reference_rows
            or not valid_alias_references
            or not correction.get('link_updates')
            or any(correction.get(field) for field in forbidden_rows)
        ):
            raise ValueError(
                f'work catalog correction has invalid link rebind projection: {correction.get("correction_id", "")}'
            )

    projected_fetishes = copy.deepcopy(fetishes)
    fetish_by_id = {int(row['id']): row for row in projected_fetishes}
    compounds_were_dict = isinstance(compound_rows, dict)
    if compounds_were_dict:
        projected_compounds = [
            {
                'key': key,
                'id_a': int(key.split(',', 1)[0]),
                'id_b': int(key.split(',', 1)[1]),
                'works': copy.deepcopy(works),
            }
            for key, works in compound_rows.items()
        ]
    else:
        projected_compounds = copy.deepcopy(list(compound_rows or []))
    compound_by_key = {}
    for row in projected_compounds:
        if 'id_a' in row and 'id_b' in row:
            key = f'{min(int(row["id_a"]), int(row["id_b"]))},{max(int(row["id_a"]), int(row["id_b"]))}'
        else:
            key = str(row.get('key') or '')
        if key:
            compound_by_key[key] = row

    projection_errors = []
    applied_count = 0
    missing_count = 0
    changed_fetish_owners = set()
    changed_compound_owners = set()
    seen_targets = set()

    def source_locations(signature):
        locations = []
        if 'fetish_work_links' in selected_tables:
            for row in projected_fetishes:
                locations.extend(
                    ('fetish', int(row['id']), index)
                    for index, work in enumerate(row.get('works') or [])
                    if _effective_signature(work) == signature
                )
        if 'compound_work_links' in selected_tables:
            for key, row in compound_by_key.items():
                locations.extend(
                    ('compound', key, index)
                    for index, work in enumerate(row.get('works') or [])
                    if _effective_signature(work) == signature
                )
        return locations

    def missing_is_approved(correction_id, owner_key, owner_id, position, expected_signature):
        moved = [
            location
            for location in source_locations(expected_signature)
            if location != (owner_key[0], owner_id, position)
        ]
        if moved:
            projection_errors.append(
                {
                    'correction_id': correction_id,
                    'source': owner_key[0],
                    'owner_id': owner_id,
                    'position': position,
                    'actual_locations': moved,
                    'reason': 'source_owner_drift',
                }
            )
            return False
        return True

    def source_aliases(correction):
        aliases = {
            row.get('expected', {}).get('alias_id'): row.get('expected', {})
            for row in correction.get('alias_removals') or []
            if isinstance(row, dict) and isinstance(row.get('expected'), dict)
        }
        aliases.update(
            {
                row.get('expected', {}).get('alias_id'): row.get('expected', {})
                for row in correction.get('alias_references') or []
                if isinstance(row, dict) and isinstance(row.get('expected'), dict)
            }
        )
        return aliases

    def target_aliases(correction):
        aliases = source_aliases(correction)
        aliases.update(
            {
                row.get('target', {}).get('alias_id'): row.get('target', {})
                for row in correction.get('alias_additions') or []
                if isinstance(row, dict) and isinstance(row.get('target'), dict)
            }
        )
        aliases.update(
            {
                row.get('expected', {}).get('alias_id'): row.get('expected', {})
                for row in correction.get('alias_references') or []
                if isinstance(row, dict) and isinstance(row.get('expected'), dict)
            }
        )
        return aliases

    def source_editions(correction):
        editions = {
            row.get('expected', {}).get('edition_id'): row.get('expected', {})
            for row in correction.get('edition_updates') or []
            if isinstance(row, dict) and isinstance(row.get('expected'), dict)
        }
        editions.update(
            {
                row.get('expected', {}).get('edition_id'): row.get('expected', {})
                for row in correction.get('edition_removals') or []
                if isinstance(row, dict) and isinstance(row.get('expected'), dict)
            }
        )
        return editions

    def target_editions(correction):
        editions = {
            row.get('expected', {}).get('edition_id'): row.get('expected', {})
            for row in correction.get('edition_updates') or []
            if isinstance(row, dict) and isinstance(row.get('expected'), dict)
        }
        editions.update(
            {
                row.get('target', {}).get('edition_id'): row.get('target', {})
                for row in correction.get('edition_additions') or []
                if isinstance(row, dict) and isinstance(row.get('target'), dict)
            }
        )
        return editions

    def signature(correction, link, *, target, source_url=None, source_title=None):
        work = correction.get('target_work') if target else correction.get('expected_work')
        if not isinstance(work, dict) or not str(work.get('canonical_title') or '').strip():
            raise ValueError('missing work title')
        alias_id = link.get('alias_id') if target else link.get('expected', {}).get('alias_id')
        if not target and source_title is not None:
            title = source_title
        elif alias_id:
            aliases = target_aliases(correction) if target else source_aliases(correction)
            alias = aliases.get(alias_id)
            if not alias or not str(alias.get('alias') or '').strip():
                raise ValueError(f'unknown alias_id {alias_id}')
            title = str(alias['alias']).strip()
        else:
            title = str(work['canonical_title']).strip()
        edition_id = link.get('edition_id') if target else link.get('expected', {}).get('edition_id')
        if edition_id:
            if source_url is not None:
                url = source_url
            else:
                editions = target_editions(correction) if target else source_editions(correction)
                edition = editions.get(edition_id)
                if not edition:
                    raise ValueError(f'unknown edition_id {edition_id}')
                url = safe_work_url(edition.get('canonical_url'))
        else:
            url = ''
        return [title, url]

    update_projections = []
    for correction in correction_rows:
        correction_id = str(correction['correction_id'])
        link_updates = correction.get('link_updates') or []
        if not isinstance(link_updates, list) or not all(isinstance(row, dict) for row in link_updates):
            projection_errors.append({'correction_id': correction_id, 'reason': 'invalid_link_updates'})
            continue
        for update in link_updates:
            expected = update.get('expected')
            table = str(update.get('table') or '')
            if table not in {'fetish_work_links', 'compound_work_links'}:
                projection_errors.append({'correction_id': correction_id, 'reason': 'invalid_link_update'})
                continue
            if table not in selected_tables:
                continue
            allow_missing_value = update.get('allow_missing', False)
            if not isinstance(allow_missing_value, bool):
                projection_errors.append({'correction_id': correction_id, 'reason': 'invalid_allow_missing'})
                continue
            allow_missing = allow_missing_value
            source_url_present = 'source_url' in update
            source_url = safe_work_url(update.get('source_url')) if source_url_present else None
            source_title_present = 'source_title' in update
            source_title = str(update.get('source_title') or '').strip() if source_title_present else None
            if (
                not isinstance(expected, dict)
                or (source_url_present and (not expected.get('edition_id') or source_url != update.get('source_url')))
                or (source_title_present and (not source_title or len(source_title) > 200))
            ):
                projection_errors.append({'correction_id': correction_id, 'reason': 'invalid_link_update'})
                continue
            try:
                position = int(expected['position'])
                if position < 0:
                    raise ValueError
                if table == 'fetish_work_links':
                    owner_id = int(expected['fetish_id'])
                    owner_key = ('fetish', owner_id, position)
                    owner = fetish_by_id.get(owner_id)
                else:
                    id_a, id_b = sorted((int(expected['id_a']), int(expected['id_b'])))
                    owner_id = f'{id_a},{id_b}'
                    owner_key = ('compound', owner_id, position)
                    owner = compound_by_key.get(owner_id)
                if owner_key in seen_targets:
                    raise ValueError('duplicate owner position')
                seen_targets.add(owner_key)
                source_signature = signature(
                    correction,
                    update,
                    target=False,
                    source_url=source_url,
                    source_title=source_title,
                )
                target_signature = signature(
                    correction,
                    update,
                    target=True,
                    source_url=source_url,
                )
                if correction.get('type') == 'link_rebind' and source_signature != target_signature:
                    raise ValueError('link rebind changes inline signature')
                expected_signature, replacement_signature = (
                    (source_signature, target_signature)
                    if direction == 'forward'
                    else (target_signature, source_signature)
                )
                final_position = _correction_final_link_position(correction_rows, table, expected)
            except (KeyError, TypeError, ValueError) as exc:
                projection_errors.append(
                    {'correction_id': correction_id, 'reason': 'invalid_link_projection', 'detail': str(exc)}
                )
                continue

            update_projections.append(
                (
                    correction_id,
                    table,
                    owner_id,
                    owner_key,
                    owner,
                    position,
                    final_position,
                    expected_signature,
                    replacement_signature,
                    allow_missing,
                    (source_title, source_url) if correction.get('type') == 'link_rebind' else None,
                )
            )

    def apply_update_projections():
        nonlocal applied_count, missing_count
        for update_projection in update_projections:
            (
                correction_id,
                table,
                owner_id,
                owner_key,
                owner,
                position,
                final_position,
                expected_signature,
                replacement_signature,
                allow_missing,
                strict_source_components,
            ) = update_projection
            works = owner.get('works') if isinstance(owner, dict) else None
            replacement_positions = (
                [index for index, work in enumerate(works) if _effective_signature(work) == replacement_signature]
                if isinstance(works, list)
                else []
            )
            if direction == 'forward' and final_position != position and replacement_positions == [final_position]:
                continue
            if replacement_positions and any(
                index not in {position, final_position} for index in replacement_positions
            ):
                projection_errors.append(
                    {
                        'correction_id': correction_id,
                        'source': owner_key[0],
                        'owner_id': owner_id,
                        'position': position,
                        'actual_positions': replacement_positions,
                        'reason': 'target_position_drift',
                    }
                )
                continue
            if not isinstance(works, list) or position >= len(works):
                if allow_missing:
                    if missing_is_approved(correction_id, owner_key, owner_id, position, expected_signature):
                        missing_count += 1
                    continue
                projection_errors.append(
                    {
                        'correction_id': correction_id,
                        'source': owner_key[0],
                        'owner_id': owner_id,
                        'position': position,
                        'reason': 'source_absent',
                    }
                )
                continue
            expected_positions = [
                index for index, work in enumerate(works) if _effective_signature(work) == expected_signature
            ]
            if any(index != position for index in expected_positions):
                projection_errors.append(
                    {
                        'correction_id': correction_id,
                        'source': owner_key[0],
                        'owner_id': owner_id,
                        'position': position,
                        'actual_positions': expected_positions,
                        'reason': 'source_position_drift',
                    }
                )
                continue
            actual_signature = _effective_signature(works[position])
            if actual_signature == expected_signature:
                works[position] = (
                    {'title': replacement_signature[0], 'url': replacement_signature[1]}
                    if replacement_signature[1]
                    else replacement_signature[0]
                )
                applied_count += 1
                (changed_fetish_owners if table == 'fetish_work_links' else changed_compound_owners).add(owner_id)
            elif actual_signature == replacement_signature:
                continue
            elif allow_missing:
                if strict_source_components and (
                    actual_signature[0] == strict_source_components[0]
                    or actual_signature[1] == strict_source_components[1]
                ):
                    projection_errors.append(
                        {
                            'correction_id': correction_id,
                            'source': owner_key[0],
                            'owner_id': owner_id,
                            'position': position,
                            'reason': 'source_signature_drift',
                            'expected': expected_signature,
                            'actual': actual_signature,
                        }
                    )
                elif missing_is_approved(correction_id, owner_key, owner_id, position, expected_signature):
                    missing_count += 1
            else:
                projection_errors.append(
                    {
                        'correction_id': correction_id,
                        'source': owner_key[0],
                        'owner_id': owner_id,
                        'position': position,
                        'reason': 'source_signature_drift',
                        'expected': expected_signature,
                        'actual': actual_signature,
                    }
                )

    removal_projections = []
    for correction in correction_rows:
        correction_id = str(correction['correction_id'])
        for removal in correction.get('link_removals') or []:
            table = str(removal.get('table') or '')
            expected = removal.get('expected')
            allow_missing = removal.get('allow_missing', False)
            if table not in {'fetish_work_links', 'compound_work_links'} or table not in selected_tables:
                if table not in {'fetish_work_links', 'compound_work_links'}:
                    projection_errors.append({'correction_id': correction_id, 'reason': 'invalid_link_removal'})
                continue
            source_url_present = 'source_url' in removal
            source_url = safe_work_url(removal.get('source_url')) if source_url_present else None
            source_title_present = 'source_title' in removal
            source_title = str(removal.get('source_title') or '').strip() if source_title_present else None
            if (
                not isinstance(expected, dict)
                or type(allow_missing) is not bool
                or bool(expected.get('edition_id')) != source_url_present
                or (source_url_present and source_url != removal.get('source_url'))
                or (source_title_present and (not source_title or len(source_title) > 200))
            ):
                projection_errors.append({'correction_id': correction_id, 'reason': 'invalid_link_removal'})
                continue
            try:
                position = int(expected['position'])
                if position < 0:
                    raise ValueError
                if table == 'fetish_work_links':
                    owner_id = int(expected['fetish_id'])
                    owner_key = ('fetish', owner_id, position)
                    owner = fetish_by_id.get(owner_id)
                else:
                    id_a, id_b = sorted((int(expected['id_a']), int(expected['id_b'])))
                    owner_id = f'{id_a},{id_b}'
                    owner_key = ('compound', owner_id, position)
                    owner = compound_by_key.get(owner_id)
                if owner_key in seen_targets:
                    raise ValueError('duplicate owner position')
                seen_targets.add(owner_key)
                expected_signature = signature(
                    correction,
                    removal,
                    target=False,
                    source_url=source_url,
                    source_title=source_title,
                )
                removal_projections.append(
                    (correction_id, table, owner_id, owner_key, owner, position, expected_signature, allow_missing)
                )
            except (KeyError, TypeError, ValueError) as exc:
                projection_errors.append(
                    {'correction_id': correction_id, 'reason': 'invalid_link_projection', 'detail': str(exc)}
                )

    # Removing from the end and restoring from the beginning preserves the
    # manifest's original owner positions when one correction removes several
    # recommendations from the same owner.
    removal_projections.sort(key=lambda row: (row[3][0], str(row[2]), (-row[5] if direction == 'forward' else row[5])))
    if direction == 'forward':
        apply_update_projections()

    for removal_projection in removal_projections:
        (
            correction_id,
            table,
            owner_id,
            owner_key,
            owner,
            position,
            expected_signature,
            allow_missing,
        ) = removal_projection
        works = owner.get('works') if isinstance(owner, dict) else None
        locations = source_locations(expected_signature)
        expected_location = (owner_key[0], owner_id, position)
        if len(locations) > 1:
            projection_errors.append(
                {
                    'correction_id': correction_id,
                    'source': owner_key[0],
                    'owner_id': owner_id,
                    'position': position,
                    'actual_locations': locations,
                    'reason': 'duplicate_source_signature',
                }
            )
            continue
        if direction == 'forward':
            if not locations:
                if allow_missing and missing_is_approved(
                    correction_id, owner_key, owner_id, position, expected_signature
                ):
                    missing_count += 1
                else:
                    projection_errors.append(
                        {
                            'correction_id': correction_id,
                            'source': owner_key[0],
                            'owner_id': owner_id,
                            'position': position,
                            'reason': 'source_absent',
                        }
                    )
                continue
            if locations[0] != expected_location:
                projection_errors.append(
                    {
                        'correction_id': correction_id,
                        'source': owner_key[0],
                        'owner_id': owner_id,
                        'position': position,
                        'actual_locations': locations,
                        'reason': (
                            'source_owner_drift'
                            if locations[0][:2] != expected_location[:2]
                            else 'source_position_drift'
                        ),
                    }
                )
                continue
            if not isinstance(works, list) or position >= len(works):
                projection_errors.append(
                    {
                        'correction_id': correction_id,
                        'source': owner_key[0],
                        'owner_id': owner_id,
                        'position': position,
                        'reason': 'source_absent',
                    }
                )
                continue
            works.pop(position)
            applied_count += 1
        else:
            if locations:
                if locations[0] != expected_location:
                    projection_errors.append(
                        {
                            'correction_id': correction_id,
                            'source': owner_key[0],
                            'owner_id': owner_id,
                            'position': position,
                            'actual_locations': locations,
                            'reason': (
                                'source_owner_drift'
                                if locations[0][:2] != expected_location[:2]
                                else 'source_position_drift'
                            ),
                        }
                    )
                continue
            if not isinstance(works, list) or position > len(works):
                projection_errors.append(
                    {
                        'correction_id': correction_id,
                        'source': owner_key[0],
                        'owner_id': owner_id,
                        'position': position,
                        'reason': 'restore_position_absent',
                    }
                )
                continue
            works.insert(
                position,
                (
                    {'title': expected_signature[0], 'url': expected_signature[1]}
                    if expected_signature[1]
                    else expected_signature[0]
                ),
            )
            applied_count += 1
        (changed_fetish_owners if table == 'fetish_work_links' else changed_compound_owners).add(owner_id)

    if direction == 'reverse':
        apply_update_projections()

    if strict and projection_errors:
        first = projection_errors[0]
        raise ValueError(
            f'approved inline projection failed: {first.get("correction_id", "unknown")} '
            f'{first.get("reason", "unknown")}'
        )

    def projected_compound_key(row):
        if row.get('key'):
            return str(row['key'])
        id_a, id_b = sorted((int(row['id_a']), int(row['id_b'])))
        return f'{id_a},{id_b}'

    projected_compound_output = (
        {projected_compound_key(row): copy.deepcopy(row.get('works') or []) for row in projected_compounds}
        if compounds_were_dict
        else projected_compounds
    )
    return {
        'fetishes': projected_fetishes,
        'compound_rows': projected_compound_output,
        'applied_link_count': applied_count,
        'fetish_owner_count': len(changed_fetish_owners),
        'compound_owner_count': len(changed_compound_owners),
        'missing_count': missing_count,
        'error_count': len(projection_errors),
        'errors': projection_errors[: max(0, min(int(sample_limit), 100))],
    }


def project_approved_inline_correction_manifests(
    fetishes,
    *,
    compound_rows=(),
    correction_manifests,
    direction='forward',
    tables=None,
    strict=True,
    sample_limit=20,
):
    """Project an ordered correction pipeline, reversing manifest order on rollback."""
    if direction not in {'forward', 'reverse'}:
        raise ValueError('unsupported approved inline projection direction')
    manifests = tuple(correction_manifests)
    ordered = manifests if direction == 'forward' else tuple(reversed(manifests))
    original_fetishes = copy.deepcopy(fetishes)
    original_compounds = copy.deepcopy(compound_rows)
    projection = {'fetishes': fetishes, 'compound_rows': compound_rows}
    totals = {'applied_link_count': 0, 'missing_count': 0, 'error_count': 0}
    errors = []
    for manifest in ordered:
        projection = project_approved_inline_corrections(
            projection['fetishes'],
            compound_rows=projection['compound_rows'],
            corrections=manifest,
            direction=direction,
            tables=tables,
            strict=strict,
            sample_limit=sample_limit,
        )
        for field in totals:
            totals[field] += projection[field]
        errors.extend(projection['errors'])

    def fetish_works(rows):
        return {int(row['id']): row.get('works') or [] for row in rows}

    def compound_works(rows):
        if isinstance(rows, dict):
            return {str(key): works for key, works in rows.items()}
        return {
            str(
                row.get('key') or f'{min(int(row["id_a"]), int(row["id_b"]))},{max(int(row["id_a"]), int(row["id_b"]))}'
            ): row.get('works') or []
            for row in rows
        }

    before_fetishes = fetish_works(original_fetishes)
    after_fetishes = fetish_works(projection['fetishes'])
    before_compounds = compound_works(original_compounds)
    after_compounds = compound_works(projection['compound_rows'])
    projection.update(totals)
    projection['errors'] = errors[: max(0, min(int(sample_limit), 100))]
    projection['fetish_owner_count'] = sum(
        before_fetishes.get(owner_id) != after_fetishes.get(owner_id)
        for owner_id in set(before_fetishes) | set(after_fetishes)
    )
    projection['compound_owner_count'] = sum(
        before_compounds.get(owner_id) != after_compounds.get(owner_id)
        for owner_id in set(before_compounds) | set(after_compounds)
    )
    return projection


def approved_projection_parity_report_many(
    catalog,
    fetishes,
    *,
    compound_rows=(),
    correction_manifests,
    sample_limit=20,
):
    """Compare catalog output after an ordered sequence of approved corrections."""
    raw_parity = catalog_parity_report(
        catalog,
        fetishes,
        compound_rows=compound_rows,
        sample_limit=sample_limit,
    )
    if raw_parity['mismatch_count'] == 0:
        return {
            'approved_projection_ok': True,
            'approved_mismatch_count': 0,
            'approved_fetish_mismatch_count': 0,
            'approved_compound_mismatch_count': 0,
            'approved_mismatches': [],
            'approved_projection_error_count': 0,
            'approved_projection_errors': [],
            'approved_projection_applied_count': 0,
            'approved_projection_missing_count': 0,
        }
    projection = project_approved_inline_correction_manifests(
        fetishes,
        compound_rows=compound_rows,
        correction_manifests=correction_manifests,
        strict=False,
        sample_limit=sample_limit,
    )
    parity = catalog_parity_report(
        catalog,
        projection['fetishes'],
        compound_rows=projection['compound_rows'],
        sample_limit=sample_limit,
    )
    mismatch_count = int(parity['mismatch_count']) + projection['error_count']
    return {
        'approved_projection_ok': mismatch_count == 0,
        'approved_mismatch_count': mismatch_count,
        'approved_fetish_mismatch_count': parity['fetish_mismatch_count'],
        'approved_compound_mismatch_count': parity['compound_mismatch_count'],
        'approved_mismatches': parity['mismatches'],
        'approved_projection_error_count': projection['error_count'],
        'approved_projection_errors': projection['errors'],
        'approved_projection_applied_count': projection['applied_link_count'],
        'approved_projection_missing_count': projection['missing_count'],
    }


def approved_projection_parity_report(catalog, fetishes, *, compound_rows=(), corrections, sample_limit=20):
    """Compare catalog output with legacy output after exact approved corrections."""
    return approved_projection_parity_report_many(
        catalog,
        fetishes,
        compound_rows=compound_rows,
        correction_manifests=(corrections,),
        sample_limit=sample_limit,
    )


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
            'edition_title': '',
            'publisher': '',
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
        ('work_edition_identifiers', 'identifier_id'),
        ('work_aliases', 'alias_id'),
        ('review_queue', 'review_id'),
    ):
        if collection in catalog:
            catalog[collection].sort(key=lambda row: row[id_field])
    catalog['fetish_work_links'].sort(key=lambda row: (int(row['fetish_id']), int(row['position']), row['link_id']))
    catalog['compound_work_links'].sort(
        key=lambda row: (int(row['id_a']), int(row['id_b']), int(row['position']), row['link_id'])
    )


def _canonicalize_alias_and_link_ids(catalog, *, reindex_positions=False):
    alias_replacements = {}
    for alias in catalog['work_aliases']:
        old_id = alias['alias_id']
        alias['alias_id'] = _stable_id('wal', alias['work_id'], alias['normalized_alias'])
        alias_replacements[old_id] = alias['alias_id']
    for table in ('fetish_work_links', 'compound_work_links'):
        owner_fields = ('fetish_id',) if table == 'fetish_work_links' else ('id_a', 'id_b')
        positions = defaultdict(int)
        for link in sorted(
            catalog[table],
            key=lambda row: (*[int(row[field]) for field in owner_fields], int(row['position']), row['link_id']),
        ):
            if link.get('alias_id'):
                link['alias_id'] = alias_replacements.get(link['alias_id'], link['alias_id'])
            owner = tuple(int(link[field]) for field in owner_fields)
            if reindex_positions:
                link['position'] = positions[owner]
            positions[owner] += 1
            prefix = 'fwl' if table == 'fetish_work_links' else 'cwl'
            link['link_id'] = _stable_id(
                prefix,
                *owner,
                link['work_id'],
                link.get('edition_id'),
                link.get('alias_id'),
            )
    _sort_catalog_rows(catalog)


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
    if any(
        row.get('normalized_title') == normalized and row.get('media_type', '') == media_type
        for row in updated['works_master']
    ):
        raise ValueError('work master identity already exists')
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
    if any(
        other['work_id'] != row['work_id']
        and other.get('normalized_title') == row.get('normalized_title')
        and other.get('media_type', '') == row.get('media_type', '')
        for other in updated['works_master']
    ):
        raise ValueError('work master identity already exists')
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
    removed_edition_ids = {row['edition_id'] for row in updated['work_editions'] if row['work_id'] == work_id}
    updated['works_master'] = [row for row in updated['works_master'] if row['work_id'] != work_id]
    updated['work_editions'] = [row for row in updated['work_editions'] if row['work_id'] != work_id]
    if 'work_edition_identifiers' in updated:
        updated['work_edition_identifiers'] = [
            row for row in updated['work_edition_identifiers'] if row['edition_id'] not in removed_edition_ids
        ]
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
        edition_title=_admin_text(values.get('edition_title', row.get('edition_title', '')), 'edition_title', 200),
        publisher=_admin_text(values.get('publisher', row.get('publisher', '')), 'publisher', 200),
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
    if 'work_edition_identifiers' in updated:
        updated['work_edition_identifiers'] = [
            row for row in updated['work_edition_identifiers'] if row['edition_id'] != edition_id
        ]
    validate_catalog(updated)
    return updated


def admin_upsert_edition_identifier(catalog, values, *, identifier_id=None):
    updated = upgrade_catalog_schema(catalog)
    edition_id = str(values.get('edition_id') or '')
    _row_by_id(updated['work_editions'], 'edition_id', edition_id, 'work edition')
    row = build_edition_identifier(
        edition_id,
        scheme=values.get('scheme'),
        authority=values.get('authority'),
        value=values.get('value'),
    )
    existing_id = str(identifier_id or '')
    if existing_id:
        _row_by_id(
            updated['work_edition_identifiers'],
            'identifier_id',
            existing_id,
            'work edition identifier',
        )
        updated['work_edition_identifiers'] = [
            item for item in updated['work_edition_identifiers'] if item['identifier_id'] != existing_id
        ]
    if any(item['identifier_id'] == row['identifier_id'] for item in updated['work_edition_identifiers']):
        raise ValueError('edition identifier already exists')
    updated['work_edition_identifiers'].append(row)
    _sort_catalog_rows(updated)
    validate_catalog(updated)
    return updated, row['identifier_id']


def admin_delete_edition_identifier(catalog, identifier_id):
    updated = upgrade_catalog_schema(catalog)
    identifier_id = str(identifier_id or '')
    _row_by_id(
        updated['work_edition_identifiers'],
        'identifier_id',
        identifier_id,
        'work edition identifier',
    )
    updated['work_edition_identifiers'] = [
        row for row in updated['work_edition_identifiers'] if row['identifier_id'] != identifier_id
    ]
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


def apply_bibliography_manifest(catalog, manifest):
    """Apply primary-source edition identifiers and media metadata atomically."""
    updated = upgrade_catalog_schema(catalog)
    if not isinstance(manifest, dict):
        raise ValueError('unsupported work bibliography schema_version')
    try:
        schema_version = int(manifest.get('schema_version', 0))
        catalog_schema_version = int(manifest.get('catalog_schema_version', 0))
    except (TypeError, ValueError):
        raise ValueError('unsupported work bibliography schema_version')
    if schema_version != 1 or catalog_schema_version != CATALOG_SCHEMA_VERSION:
        raise ValueError('unsupported work bibliography schema_version')
    entries = manifest.get('entries')
    if not isinstance(entries, list) or not all(isinstance(row, dict) for row in entries):
        raise ValueError('work bibliography entries must be a list')
    entry_ids = [str(row.get('entry_id') or '') for row in entries]
    if not all(entry_ids) or len(entry_ids) != len(set(entry_ids)):
        raise ValueError('work bibliography contains missing or duplicate entry ids')

    counts = {'entry_count': len(entries), 'work_update_count': 0, 'edition_count': 0, 'identifier_count': 0}
    for entry in entries:
        entry_id = str(entry['entry_id'])
        expected = entry.get('expected_work')
        target = entry.get('target_work')
        if not isinstance(expected, dict) or not isinstance(target, dict):
            raise ValueError(f'work bibliography requires expected and target work: {entry_id}')
        work_id = str(expected.get('work_id') or '')
        if not work_id or target.get('work_id') != work_id:
            raise ValueError(f'work bibliography work id mismatch: {entry_id}')
        canonical_title = _admin_text(target.get('canonical_title'), 'canonical_title', 200, required=True)
        target_work = {
            'work_id': work_id,
            'canonical_title': canonical_title,
            'normalized_title': normalized_work_title(canonical_title),
            'media_type': _admin_text(target.get('media_type'), 'media_type', 40),
            'status': str(target.get('status') or ''),
        }
        if target_work['status'] not in {'active', 'inactive', 'archived'} or target != target_work:
            raise ValueError(f'work bibliography target work is not canonical: {entry_id}')
        current_work = _row_by_id(updated['works_master'], 'work_id', work_id, 'work master')

        edition_spec = entry.get('edition')
        evidence_url = safe_work_url(str(entry.get('evidence_url') or ''))
        if edition_spec is None and not evidence_url:
            raise ValueError(f'work bibliography evidence URL is required: {entry_id}')
        if entry.get('evidence_url') and not evidence_url:
            raise ValueError(f'work bibliography evidence URL is unsafe: {entry_id}')
        target_edition = None
        target_identifier = None
        if edition_spec is not None:
            if not isinstance(edition_spec, dict):
                raise ValueError(f'work bibliography edition is invalid: {entry_id}')
            url = safe_work_url(_admin_text(edition_spec.get('canonical_url'), 'canonical_url', 1000, required=True))
            if not url:
                raise ValueError(f'work bibliography edition URL is unsafe: {entry_id}')
            edition_id = _stable_id('wed', _edition_key(url))
            target_edition = {
                'edition_id': edition_id,
                'work_id': work_id,
                'asin': extract_asin(url),
                'canonical_url': url,
                'edition_title': _admin_text(edition_spec.get('edition_title'), 'edition_title', 200, required=True),
                'publisher': _admin_text(edition_spec.get('publisher'), 'publisher', 200, required=True),
                'format': _admin_text(edition_spec.get('format'), 'format', 40, required=True),
                'status': str(edition_spec.get('status') or 'active'),
            }
            if target_edition['status'] not in {'active', 'inactive', 'archived'}:
                raise ValueError(f'work bibliography edition status is invalid: {entry_id}')
            has_isbn = 'isbn' in edition_spec
            has_identifier = 'identifier' in edition_spec
            if has_isbn and has_identifier:
                raise ValueError(f'work bibliography edition identifier is ambiguous: {entry_id}')
            if has_isbn:
                isbn = edition_spec.get('isbn')
                if not isbn:
                    raise ValueError(f'work bibliography edition ISBN is required: {entry_id}')
                target_identifier = build_edition_identifier(edition_id, scheme='isbn', authority='isbn', value=isbn)
            elif has_identifier:
                identifier_spec = edition_spec.get('identifier')
                if not isinstance(identifier_spec, dict) or set(identifier_spec) != {
                    'scheme',
                    'authority',
                    'value',
                }:
                    raise ValueError(f'work bibliography edition identifier is invalid: {entry_id}')
                try:
                    target_identifier = build_edition_identifier(edition_id, **identifier_spec)
                except (TypeError, ValueError) as exc:
                    raise ValueError(f'work bibliography edition identifier is invalid: {entry_id}') from exc

        title_changed = expected.get('canonical_title') != target_work['canonical_title']
        old_alias_id = _stable_id('wal', work_id, normalized_work_title(expected.get('canonical_title')))
        old_alias = {
            'alias_id': old_alias_id,
            'work_id': work_id,
            'alias': expected['canonical_title'],
            'normalized_alias': normalized_work_title(expected['canonical_title']),
        }
        existing_alias = next((row for row in updated['work_aliases'] if row['alias_id'] == old_alias_id), None)
        if title_changed and existing_alias not in (None, old_alias):
            raise ValueError(f'work bibliography alias source drift: {entry_id}')

        existing_edition = None
        existing_identifier = None
        if target_edition is not None:
            existing_edition = next(
                (row for row in updated['work_editions'] if row['edition_id'] == target_edition['edition_id']),
                None,
            )
            if existing_edition not in (None, target_edition):
                raise ValueError(f'work bibliography edition source drift: {entry_id}')
            if target_identifier is not None:
                edition_identifiers = [
                    row
                    for row in updated['work_edition_identifiers']
                    if row['edition_id'] == target_edition['edition_id']
                ]
                existing_identifier = next(
                    (
                        row
                        for row in updated['work_edition_identifiers']
                        if row['identifier_id'] == target_identifier['identifier_id']
                    ),
                    None,
                )
                if existing_identifier not in (None, target_identifier) or (
                    existing_identifier is None and edition_identifiers
                ):
                    raise ValueError(f'work bibliography identifier source drift: {entry_id}')

        current_is_expected = current_work == expected
        current_is_target = current_work == target_work
        alias_present = not title_changed or existing_alias == old_alias
        edition_present = target_edition is None or existing_edition == target_edition
        identifier_present = target_identifier is None or existing_identifier == target_identifier
        if current_is_target and alias_present and edition_present and identifier_present:
            continue
        if not current_is_expected and not current_is_target:
            raise ValueError(f'work bibliography source drift: {entry_id} {work_id}')
        if current_is_target and not alias_present:
            raise ValueError(f'work bibliography alias source drift: {entry_id}')
        if any(
            row['work_id'] != work_id and row['normalized_title'] == target_work['normalized_title']
            for row in updated['works_master']
        ):
            raise ValueError(f'work bibliography canonical title collision: {entry_id}')

        if title_changed:
            if existing_alias is None:
                updated['work_aliases'].append(old_alias)
            for table in ('fetish_work_links', 'compound_work_links'):
                for link in updated[table]:
                    if link['work_id'] == work_id and not link.get('alias_id'):
                        link['alias_id'] = old_alias_id
        if not current_is_target:
            current_work.clear()
            current_work.update(target_work)
            counts['work_update_count'] += 1
        if target_edition is not None and existing_edition is None:
            updated['work_editions'].append(target_edition)
            counts['edition_count'] += 1
        if target_identifier is not None and existing_identifier is None:
            updated['work_edition_identifiers'].append(target_identifier)
            counts['identifier_count'] += 1

    _canonicalize_alias_and_link_ids(updated)
    validate_catalog(updated)
    return updated, counts


def apply_seed_overrides(catalog, seed_overrides):
    """Apply reviewed seed cleanup to an existing catalog, failing closed on drift."""
    validate_catalog(catalog)
    normalizations = _seed_title_normalizations(seed_overrides)
    removal_titles = _seed_removal_titles(seed_overrides)
    updated = copy.deepcopy(catalog)
    masters = {row['work_id']: row for row in updated['works_master']}
    aliases = {row['alias_id']: row for row in updated['work_aliases']}
    links = updated['fetish_work_links'] + updated['compound_work_links']
    original_display = {
        row['link_id']: (
            aliases[row['alias_id']]['alias'] if row.get('alias_id') else masters[row['work_id']]['canonical_title']
        )
        for row in links
    }
    represented = defaultdict(set)
    for work in masters.values():
        represented[work['canonical_title']].add(work['work_id'])
    for alias in aliases.values():
        represented[alias['alias']].add(alias['work_id'])

    aliases_by_work_title = {(row['work_id'], row['normalized_alias']): row for row in updated['work_aliases']}
    for display_title, values in normalizations.items():
        work_ids = represented.get(display_title, set())
        if len(work_ids) != 1:
            raise ValueError(f'work catalog seed override display drift: {display_title}')
        work_id = next(iter(work_ids))
        canonical_title = values['canonical_title']
        normalized_title = normalized_work_title(canonical_title)
        collisions = {
            row['work_id']
            for row in updated['works_master']
            if row['normalized_title'] == normalized_title and row['work_id'] != work_id
        }
        if collisions:
            raise ValueError(f'work catalog seed override canonical collision: {display_title}')
        alias_key = (work_id, normalized_work_title(display_title))
        alias = aliases_by_work_title.get(alias_key)
        if alias is None:
            alias = {
                'alias_id': _stable_id('wal', work_id, alias_key[1]),
                'work_id': work_id,
                'alias': display_title,
                'normalized_alias': alias_key[1],
            }
            updated['work_aliases'].append(alias)
            aliases[alias['alias_id']] = alias
            aliases_by_work_title[alias_key] = alias
        matching_links = [
            row for row in links if row['work_id'] == work_id and original_display[row['link_id']] == display_title
        ]
        if not matching_links:
            raise ValueError(f'work catalog seed override link drift: {display_title}')
        masters[work_id]['canonical_title'] = canonical_title
        masters[work_id]['normalized_title'] = normalized_title
        for link in matching_links:
            link['alias_id'] = alias['alias_id']
            link['context_label'] = values['context_label']

    for display_title in removal_titles:
        work_ids = represented.get(display_title, set())
        if not work_ids:
            continue
        matching_links = {row['link_id'] for row in links if original_display[row['link_id']] == display_title}
        if not matching_links:
            raise ValueError(f'work catalog seed removal link drift: {display_title}')
        updated['fetish_work_links'] = [
            row for row in updated['fetish_work_links'] if row['link_id'] not in matching_links
        ]
        updated['compound_work_links'] = [
            row for row in updated['compound_work_links'] if row['link_id'] not in matching_links
        ]
        remaining_work_ids = {row['work_id'] for row in updated['fetish_work_links'] + updated['compound_work_links']}
        blocked = work_ids & remaining_work_ids
        if blocked:
            raise ValueError(f'work catalog seed removal still referenced: {display_title}')
        if any(set(row.get('work_ids') or []) & work_ids for row in updated['review_queue']):
            raise ValueError(f'work catalog seed removal is review referenced: {display_title}')
        removed_edition_ids = {row['edition_id'] for row in updated['work_editions'] if row['work_id'] in work_ids}
        updated['work_editions'] = [row for row in updated['work_editions'] if row['work_id'] not in work_ids]
        if 'work_edition_identifiers' in updated:
            updated['work_edition_identifiers'] = [
                row for row in updated['work_edition_identifiers'] if row['edition_id'] not in removed_edition_ids
            ]
        updated['work_aliases'] = [row for row in updated['work_aliases'] if row['work_id'] not in work_ids]
        updated['works_master'] = [row for row in updated['works_master'] if row['work_id'] not in work_ids]

    master_normalized_titles = {row['work_id']: row['normalized_title'] for row in updated['works_master']}
    canonical_alias_ids = {
        row['alias_id']
        for row in updated['work_aliases']
        if row['normalized_alias'] == master_normalized_titles[row['work_id']]
    }
    if canonical_alias_ids:
        for link in updated['fetish_work_links'] + updated['compound_work_links']:
            if link.get('alias_id') in canonical_alias_ids:
                link['alias_id'] = None
        updated['work_aliases'] = [row for row in updated['work_aliases'] if row['alias_id'] not in canonical_alias_ids]

    for review in updated['review_queue']:
        if review.get('review_type') == 'identity_override':
            review['titles'] = sorted(
                {normalizations.get(title, {}).get('canonical_title', title) for title in review.get('titles', [])}
            )
    _canonicalize_alias_and_link_ids(updated, reindex_positions=True)
    validate_catalog(updated)
    return updated


def apply_catalog_corrections(catalog, manifest):
    """Apply declarative, input-locked identity corrections atomically."""
    validate_catalog(catalog)
    if not isinstance(manifest, dict):
        raise ValueError('unsupported work catalog corrections schema_version')
    try:
        schema_version = int(manifest.get('schema_version', 0))
        catalog_schema_version = int(manifest.get('catalog_schema_version', 0))
    except (TypeError, ValueError):
        raise ValueError('unsupported work catalog corrections schema_version')
    if schema_version not in {1, 2, 3} or catalog_schema_version not in SUPPORTED_CATALOG_SCHEMA_VERSIONS:
        raise ValueError('unsupported work catalog corrections schema_version')
    corrections = manifest.get('corrections')
    if not isinstance(corrections, list) or not all(isinstance(row, dict) for row in corrections):
        raise ValueError('work catalog corrections must be a list')
    correction_ids = [str(row.get('correction_id') or '') for row in corrections]
    if not all(correction_ids) or len(correction_ids) != len(set(correction_ids)):
        raise ValueError('work catalog corrections contain missing or duplicate correction ids')

    _validate_correction_manifest_fields(corrections, schema_version)
    if schema_version >= 2 and (catalog_schema_version != 2 or int(catalog.get('schema_version', 0)) != 2):
        raise ValueError(f'work catalog corrections schema_version {schema_version} requires catalog schema_version 2')
    updated = copy.deepcopy(catalog)

    def find_row(collection, id_field, row_id):
        matches = [row for row in updated[collection] if row.get(id_field) == row_id]
        if len(matches) > 1:
            raise ValueError(f'work catalog correction duplicate {id_field}: {row_id}')
        return matches[0] if matches else None

    def utc_instant(value):
        value = str(value or '').strip()
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
            value += 'T00:00:00+00:00'
        elif value.endswith('Z'):
            value = value[:-1] + '+00:00'
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(timezone.utc)

    def rows_equal(collection, actual, expected, accepted_updated_at=()):
        if actual == expected:
            return True
        if collection == 'work_editions' and isinstance(actual, dict) and isinstance(expected, dict):
            # v1 manifests predate the descriptive v2 edition fields. Empty
            # values are the exact, non-inferred upgrade of those source rows.
            compatible_expected = copy.deepcopy(expected)
            compatible_expected.setdefault('edition_title', '')
            compatible_expected.setdefault('publisher', '')
            if actual == compatible_expected:
                return True
        if collection != 'review_queue' or not isinstance(actual, dict) or not isinstance(expected, dict):
            return False
        actual_without_time = copy.deepcopy(actual)
        expected_without_time = copy.deepcopy(expected)
        actual_updated_at = actual_without_time.pop('updated_at', None)
        expected_updated_at = expected_without_time.pop('updated_at', None)
        if actual_without_time != expected_without_time:
            return False
        accepted_instants = [utc_instant(expected_updated_at)]
        accepted_instants.extend(utc_instant(value) for value in accepted_updated_at)
        actual_instant = utc_instant(actual_updated_at)
        return (
            actual_instant is not None
            and all(value is not None for value in accepted_instants)
            and actual_instant in accepted_instants
        )

    def require_exact(collection, id_field, expected, correction_id, accepted_updated_at=()):
        if not isinstance(expected, dict) or not expected.get(id_field):
            raise ValueError(f'work catalog correction {correction_id} has invalid expected {collection} row')
        actual = find_row(collection, id_field, expected[id_field])
        if not rows_equal(collection, actual, expected, accepted_updated_at):
            raise ValueError(f'work catalog correction source drift: {correction_id} {expected[id_field]}')
        return actual

    def target_link(expected, table, work_id, edition_id, alias_id, context_label):
        owner_fields = ('fetish_id',) if table == 'fetish_work_links' else ('id_a', 'id_b')
        prefix = 'fwl' if table == 'fetish_work_links' else 'cwl'
        target = copy.deepcopy(expected)
        target.update(
            {
                'work_id': work_id,
                'edition_id': edition_id,
                'alias_id': alias_id,
                'context_label': context_label,
                'link_id': _stable_id(
                    prefix,
                    *[int(expected[field]) for field in owner_fields],
                    work_id,
                    edition_id,
                    alias_id,
                ),
            }
        )
        return target

    initial_links = {
        table: {row['link_id']: copy.deepcopy(row) for row in updated[table]}
        for table in ('fetish_work_links', 'compound_work_links')
    }
    initial_works = {row['work_id']: copy.deepcopy(row) for row in updated['works_master']}
    initial_editions = {row['edition_id']: copy.deepcopy(row) for row in updated['work_editions']}
    deferred_link_removals = []
    deferred_removed_link_ids = set()
    deferred_removed_owner_positions = set()
    quarantined_work_ids = set()

    def partial_removal_position(table, expected):
        owner_fields = ('fetish_id',) if table == 'fetish_work_links' else ('id_a', 'id_b')
        owner = tuple(expected.get(field) for field in owner_fields)
        position = int(expected['position'])
        absent_before = 0
        for correction in corrections:
            for removal in correction.get('link_removals') or []:
                other = removal.get('expected') or {}
                if (
                    removal.get('table') == table
                    and tuple(other.get(field) for field in owner_fields) == owner
                    and int(other.get('position', -1)) < position
                    and other.get('link_id') not in initial_links[table]
                ):
                    absent_before += 1
        return position - absent_before

    for correction in corrections:
        correction_id = str(correction['correction_id'])
        correction_type = str(correction.get('type') or '')
        if correction_type not in {
            'split_misassigned_edition',
            'retitle_identity',
            'quarantine_recommendation',
            'link_rebind',
        }:
            raise ValueError(f'work catalog correction has unsupported type: {correction_id}')
        expected_work = correction.get('expected_work')
        target_work = correction.get('target_work')
        if not isinstance(expected_work, dict) or not isinstance(target_work, dict):
            raise ValueError(f'work catalog correction requires expected_work and target_work: {correction_id}')
        source_work_id = str(expected_work.get('work_id') or '')
        target_work_id = str(target_work.get('work_id') or '')
        canonical_title = _admin_text(target_work.get('canonical_title'), 'canonical_title', 200, required=True)
        canonical_target_work = {
            'work_id': target_work_id,
            'canonical_title': canonical_title,
            'normalized_title': normalized_work_title(canonical_title),
            'media_type': _admin_text(target_work.get('media_type'), 'media_type', 40),
            'status': str(target_work.get('status') or ''),
        }
        if (
            not source_work_id
            or not target_work_id
            or canonical_target_work['status'] not in {'active', 'inactive', 'archived'}
            or target_work != canonical_target_work
        ):
            raise ValueError(f'work catalog correction has invalid target work: {correction_id}')
        if correction_type == 'retitle_identity' and target_work_id != source_work_id:
            raise ValueError(f'work catalog correction retitle must preserve work_id: {correction_id}')
        if correction_type == 'quarantine_recommendation' and (
            schema_version != 3 or target_work_id != source_work_id or canonical_target_work['status'] != 'archived'
        ):
            raise ValueError(f'work catalog correction has invalid quarantine target: {correction_id}')
        if correction_type == 'quarantine_recommendation':
            quarantined_work_ids.add(target_work_id)

        edition_updates = correction.get('edition_updates', [])
        edition_additions = correction.get('edition_additions', [])
        edition_removals = correction.get('edition_removals', [])
        alias_additions = correction.get('alias_additions', [])
        alias_references = correction.get('alias_references', [])
        alias_removals = correction.get('alias_removals', [])
        link_updates = correction.get('link_updates', [])
        link_removals = correction.get('link_removals', [])
        review_updates = correction.get('review_updates', [])
        extended_rows = (edition_additions, edition_removals, alias_additions)
        if not all(
            isinstance(rows, list) and all(isinstance(row, dict) for row in rows)
            for rows in (
                edition_updates,
                *extended_rows,
                alias_references,
                alias_removals,
                link_updates,
                link_removals,
                review_updates,
            )
        ):
            raise ValueError(f'work catalog correction row collections must be lists: {correction_id}')

        if correction_type == 'quarantine_recommendation' and (
            not link_removals
            or any(
                (
                    edition_updates,
                    edition_additions,
                    edition_removals,
                    alias_additions,
                    alias_references,
                    alias_removals,
                    link_updates,
                    review_updates,
                )
            )
        ):
            raise ValueError(f'work catalog correction quarantine must only remove links: {correction_id}')
        if correction_type == 'link_rebind' and (
            schema_version != 3
            or expected_work != target_work
            or not alias_references
            or not link_updates
            or any(
                (
                    edition_updates,
                    edition_additions,
                    edition_removals,
                    alias_additions,
                    alias_removals,
                    link_removals,
                    review_updates,
                )
            )
        ):
            raise ValueError(f'work catalog correction has invalid link rebind: {correction_id}')

        if correction_type == 'split_misassigned_edition':
            if len(edition_updates) != 1:
                raise ValueError(f'work catalog correction split requires one edition: {correction_id}')
            expected_edition = edition_updates[0].get('expected')
            if not isinstance(expected_edition, dict):
                raise ValueError(f'work catalog correction split has invalid edition: {correction_id}')
            expected_target_id = _stable_id(
                'wrk', _identity_key(canonical_title, expected_edition.get('canonical_url'))
            )
            if target_work_id != expected_target_id or target_work_id == source_work_id:
                raise ValueError(f'work catalog correction split has non-deterministic work_id: {correction_id}')

        target_editions = []
        for edition_update in edition_updates:
            expected = edition_update.get('expected')
            if not isinstance(expected, dict) or expected.get('work_id') != source_work_id:
                raise ValueError(f'work catalog correction has invalid edition update: {correction_id}')
            target = copy.deepcopy(expected)
            target['work_id'] = target_work_id
            target.setdefault('edition_title', '')
            target.setdefault('publisher', '')
            target_editions.append((expected, target))

        added_editions = []
        for addition in edition_additions:
            target = addition.get('target')
            identifiers = addition.get('identifiers')
            if (
                not isinstance(target, dict)
                or target.get('work_id') != target_work_id
                or not isinstance(identifiers, list)
                or not all(isinstance(row, dict) for row in identifiers)
            ):
                raise ValueError(f'work catalog correction has invalid edition addition: {correction_id}')
            canonical_url = safe_work_url(target.get('canonical_url'))
            edition_key = _edition_key(canonical_url)
            expected_id = _stable_id('wed', edition_key) if edition_key else ''
            if (
                not canonical_url
                or target.get('canonical_url') != canonical_url
                or target.get('edition_id') != expected_id
                or str(target.get('asin') or '') != extract_asin(canonical_url)
            ):
                raise ValueError(f'work catalog correction has non-deterministic edition addition: {correction_id}')
            canonical_target = {
                'edition_id': expected_id,
                'work_id': target_work_id,
                'asin': extract_asin(canonical_url),
                'canonical_url': canonical_url,
                'format': _admin_text(target.get('format'), 'format', 40),
                'status': str(target.get('status') or ''),
                'edition_title': _admin_text(target.get('edition_title'), 'edition_title', 200),
                'publisher': _admin_text(target.get('publisher'), 'publisher', 200),
            }
            if canonical_target['status'] not in {'active', 'inactive', 'archived'} or target != canonical_target:
                raise ValueError(f'work catalog correction has invalid edition addition: {correction_id}')
            canonical_identifiers = []
            for identifier in identifiers:
                canonical = build_edition_identifier(
                    target['edition_id'],
                    scheme=identifier.get('scheme'),
                    authority=identifier.get('authority'),
                    value=identifier.get('value'),
                )
                if identifier != canonical:
                    raise ValueError(
                        f'work catalog correction has non-deterministic identifier addition: {correction_id}'
                    )
                canonical_identifiers.append(copy.deepcopy(identifier))
            added_editions.append((copy.deepcopy(target), canonical_identifiers))

        added_aliases = []
        for addition in alias_additions:
            target = addition.get('target')
            if not isinstance(target, dict) or target.get('work_id') != target_work_id:
                raise ValueError(f'work catalog correction has invalid alias addition: {correction_id}')
            alias = str(target.get('alias') or '').strip()
            normalized_alias = normalized_work_title(alias)
            expected_id = _stable_id('wal', target_work_id, normalized_alias)
            canonical_target = {
                'alias_id': expected_id,
                'work_id': target_work_id,
                'alias': alias,
                'normalized_alias': normalized_alias,
            }
            if not alias or target != canonical_target:
                raise ValueError(f'work catalog correction has non-deterministic alias addition: {correction_id}')
            added_aliases.append(copy.deepcopy(target))

        referenced_aliases = []
        for reference in alias_references:
            expected = reference.get('expected')
            if not isinstance(expected, dict) or expected.get('work_id') != source_work_id:
                raise ValueError(f'work catalog correction has invalid alias reference: {correction_id}')
            alias = str(expected.get('alias') or '').strip()
            normalized_alias = normalized_work_title(alias)
            canonical_expected = {
                'alias_id': _stable_id('wal', source_work_id, normalized_alias),
                'work_id': source_work_id,
                'alias': alias,
                'normalized_alias': normalized_alias,
            }
            if not alias or expected != canonical_expected:
                raise ValueError(f'work catalog correction has invalid alias reference: {correction_id}')
            referenced_aliases.append(copy.deepcopy(expected))
        referenced_alias_ids = [row['alias_id'] for row in referenced_aliases]
        if len(referenced_alias_ids) != len(set(referenced_alias_ids)):
            raise ValueError(f'work catalog correction has duplicate alias references: {correction_id}')

        removed_editions = []
        for removal in edition_removals:
            expected = removal.get('expected')
            expected_identifiers = removal.get('expected_identifiers')
            if (
                not isinstance(expected, dict)
                or expected.get('work_id') != source_work_id
                or not isinstance(expected_identifiers, list)
                or not all(isinstance(row, dict) for row in expected_identifiers)
            ):
                raise ValueError(f'work catalog correction has invalid edition removal: {correction_id}')
            identifier_ids = []
            for identifier in expected_identifiers:
                canonical = build_edition_identifier(
                    expected.get('edition_id'),
                    scheme=identifier.get('scheme'),
                    authority=identifier.get('authority'),
                    value=identifier.get('value'),
                )
                if identifier != canonical:
                    raise ValueError(f'work catalog correction has invalid edition removal identifier: {correction_id}')
                identifier_ids.append(identifier['identifier_id'])
            if len(identifier_ids) != len(set(identifier_ids)):
                raise ValueError(f'work catalog correction has duplicate edition removal identifiers: {correction_id}')
            removed_editions.append((expected, expected_identifiers))

        target_links = []
        referenced_aliases_by_id = {row['alias_id']: row for row in referenced_aliases}
        for link_update in link_updates:
            table = str(link_update.get('table') or '')
            expected = link_update.get('expected')
            allow_missing = link_update.get('allow_missing', False)
            source_url_present = 'source_url' in link_update
            source_url = safe_work_url(link_update.get('source_url')) if source_url_present else None
            source_title_present = 'source_title' in link_update
            source_title = str(link_update.get('source_title') or '').strip() if source_title_present else None
            if (
                table not in {'fetish_work_links', 'compound_work_links'}
                or not isinstance(expected, dict)
                or type(allow_missing) is not bool
                or (
                    source_url_present
                    and (not expected.get('edition_id') or source_url != link_update.get('source_url'))
                )
                or (source_title_present and (not source_title or len(source_title) > 200))
            ):
                raise ValueError(f'work catalog correction has invalid link update: {correction_id}')
            if expected.get('work_id') != source_work_id:
                raise ValueError(f'work catalog correction link source mismatch: {correction_id}')
            target = target_link(
                expected,
                table,
                target_work_id,
                link_update.get('edition_id'),
                link_update.get('alias_id'),
                str(link_update.get('context_label') or ''),
            )
            if correction_type == 'link_rebind':
                owner_fields = ('fetish_id',) if table == 'fetish_work_links' else ('id_a', 'id_b')
                expected_fields = {
                    'link_id',
                    *owner_fields,
                    'work_id',
                    'edition_id',
                    'alias_id',
                    'position',
                    'context_label',
                    'recommendation_reason',
                }
                prefix = 'fwl' if table == 'fetish_work_links' else 'cwl'
                deterministic_source_id = _stable_id(
                    prefix,
                    *[int(expected.get(field, -1)) for field in owner_fields],
                    expected.get('work_id'),
                    expected.get('edition_id'),
                    expected.get('alias_id'),
                )
                target_alias = referenced_aliases_by_id.get(target.get('alias_id'))
                if (
                    set(expected) != expected_fields
                    or not isinstance(expected.get('position'), int)
                    or isinstance(expected.get('position'), bool)
                    or expected.get('position', -1) < 0
                    or expected.get('link_id') != deterministic_source_id
                    or expected.get('alias_id') is not None
                    or target.get('work_id') != expected.get('work_id')
                    or target.get('edition_id') != expected.get('edition_id')
                    or target.get('context_label') != expected.get('context_label')
                    or target.get('recommendation_reason') != expected.get('recommendation_reason')
                    or not source_title_present
                    or target_alias is None
                    or source_title != target_alias['alias']
                    or bool(expected.get('edition_id')) != source_url_present
                ):
                    raise ValueError(f'work catalog correction has invalid link rebind update: {correction_id}')
                source_row = initial_links[table].get(expected['link_id'])
                target_row = initial_links[table].get(target['link_id'])
                if source_row is not None and target_row is not None:
                    raise ValueError(f'work catalog correction link rebind source remains: {correction_id}')
                if source_row is None and target_row is None:
                    signature_fields = (
                        'work_id',
                        'edition_id',
                        'context_label',
                        'recommendation_reason',
                    )
                    moved = [
                        row
                        for candidate_table in ('fetish_work_links', 'compound_work_links')
                        for row in initial_links[candidate_table].values()
                        if all(row.get(field) == expected.get(field) for field in signature_fields)
                        and row.get('alias_id') in {expected.get('alias_id'), target.get('alias_id')}
                    ]
                    if moved:
                        raise ValueError(f'work catalog correction link rebind source moved: {correction_id}')
                if source_row is not None or target_row is not None:
                    edition = initial_editions.get(expected.get('edition_id'))
                    if (
                        edition is None
                        or edition.get('work_id') != source_work_id
                        or edition.get('canonical_url') != source_url
                    ):
                        raise ValueError(f'work catalog correction link rebind edition source drift: {correction_id}')
            target_links.append((table, expected, target, allow_missing))

        removed_links = []
        for link_removal in link_removals:
            table = str(link_removal.get('table') or '')
            expected = link_removal.get('expected')
            allow_missing = link_removal.get('allow_missing', False)
            source_url_present = 'source_url' in link_removal
            source_url = safe_work_url(link_removal.get('source_url')) if source_url_present else None
            source_title_present = 'source_title' in link_removal
            source_title = str(link_removal.get('source_title') or '').strip() if source_title_present else None
            owner_fields = ('fetish_id',) if table == 'fetish_work_links' else ('id_a', 'id_b')
            expected_fields = {
                'link_id',
                *owner_fields,
                'work_id',
                'edition_id',
                'alias_id',
                'position',
                'context_label',
                'recommendation_reason',
            }
            if (
                table not in {'fetish_work_links', 'compound_work_links'}
                or not isinstance(expected, dict)
                or set(expected) != expected_fields
                or expected.get('work_id') != source_work_id
                or type(allow_missing) is not bool
                or bool(expected.get('edition_id')) != source_url_present
                or (source_url_present and source_url != link_removal.get('source_url'))
                or (source_title_present and (not source_title or len(source_title) > 200))
                or not isinstance(expected.get('position'), int)
                or isinstance(expected.get('position'), bool)
                or expected['position'] < 0
            ):
                raise ValueError(f'work catalog correction has invalid link removal: {correction_id}')
            owner = tuple(int(expected[field]) for field in owner_fields)
            owner_position = (table, owner, expected['position'])
            if expected['link_id'] in deferred_removed_link_ids or owner_position in deferred_removed_owner_positions:
                raise ValueError(f'work catalog correction contains duplicate link removals: {correction_id}')
            deferred_removed_link_ids.add(expected['link_id'])
            deferred_removed_owner_positions.add(owner_position)
            actual = initial_links[table].get(expected['link_id'])
            if actual is None:
                if not allow_missing and initial_works.get(source_work_id) != target_work:
                    raise ValueError(f'work catalog correction link removal source absent: {correction_id}')
            else:
                partial_expected = copy.deepcopy(expected)
                partial_expected['position'] = partial_removal_position(table, expected)
                if actual not in (expected, partial_expected):
                    raise ValueError(f'work catalog correction link removal source drift: {correction_id}')
            if expected.get('edition_id'):
                edition = initial_editions.get(expected['edition_id'])
                if (
                    edition is None
                    or edition.get('work_id') != source_work_id
                    or edition.get('canonical_url') != source_url
                ):
                    raise ValueError(f'work catalog correction link removal edition source drift: {correction_id}')
            removal_values = (table, expected, allow_missing, owner, source_url, correction_id)
            removed_links.append(removal_values[:-1])
            deferred_link_removals.append(removal_values)

        target_reviews = []
        for review_update in review_updates:
            expected = review_update.get('expected')
            target = review_update.get('target')
            accepted_updated_at = review_update.get('accepted_source_updated_at', [])
            if (
                not isinstance(expected, dict)
                or not isinstance(target, dict)
                or expected.get('review_id') != target.get('review_id')
                or not isinstance(accepted_updated_at, list)
                or not all(isinstance(value, str) and value.strip() for value in accepted_updated_at)
                or utc_instant(expected.get('updated_at')) is None
                or utc_instant(target.get('updated_at')) is None
                or any(utc_instant(value) is None for value in accepted_updated_at)
            ):
                raise ValueError(f'work catalog correction has invalid review update: {correction_id}')
            accepted_instants = [utc_instant(value) for value in accepted_updated_at]
            if len(accepted_updated_at) != len(set(accepted_updated_at)) or len(accepted_instants) != len(
                set(accepted_instants)
            ):
                raise ValueError(f'work catalog correction has duplicate accepted review timestamps: {correction_id}')
            target_reviews.append((expected, target, accepted_updated_at))

        removed_aliases = []
        for alias_removal in alias_removals:
            expected = alias_removal.get('expected')
            allow_missing = alias_removal.get('allow_missing', False)
            if (
                not isinstance(expected, dict)
                or expected.get('work_id') != source_work_id
                or type(allow_missing) is not bool
            ):
                raise ValueError(f'work catalog correction has invalid alias removal: {correction_id}')
            removed_aliases.append((expected, allow_missing))
        removed_alias_ids = [row.get('alias_id') for row, _ in removed_aliases]
        if not all(removed_alias_ids) or len(removed_alias_ids) != len(set(removed_alias_ids)):
            raise ValueError(f'work catalog correction contains invalid alias removals: {correction_id}')

        for expected in referenced_aliases:
            require_exact('work_aliases', 'alias_id', expected, correction_id)

        def link_update_applied(table, expected, target, allow_missing):
            target_row = find_row(table, 'link_id', target['link_id'])
            final_target = copy.deepcopy(target)
            final_target['position'] = _correction_final_link_position(corrections, table, expected)
            if target_row in (target, final_target):
                return True
            return allow_missing and find_row(table, 'link_id', expected['link_id']) is None and target_row is None

        already_applied = (
            find_row('works_master', 'work_id', target_work_id) == target_work
            and all(
                find_row('work_editions', 'edition_id', target['edition_id']) == target for _, target in target_editions
            )
            and all(
                find_row('work_editions', 'edition_id', target['edition_id']) == target for target, _ in added_editions
            )
            and all(find_row('work_aliases', 'alias_id', target['alias_id']) == target for target in added_aliases)
            and all(
                find_row('work_aliases', 'alias_id', expected['alias_id']) == expected
                for expected in referenced_aliases
            )
            and all(
                find_row('work_edition_identifiers', 'identifier_id', identifier['identifier_id']) == identifier
                for _, identifiers in added_editions
                for identifier in identifiers
            )
            and all(
                find_row('work_editions', 'edition_id', expected['edition_id']) is None
                for expected, _ in removed_editions
            )
            and all(
                find_row('work_edition_identifiers', 'identifier_id', identifier['identifier_id']) is None
                for _, identifiers in removed_editions
                for identifier in identifiers
            )
            and all(link_update_applied(*values) for values in target_links)
            and all(
                find_row(table, 'link_id', expected['link_id']) is None for table, expected, _, _, _ in removed_links
            )
            and (
                correction_type != 'quarantine_recommendation'
                or not any(
                    link.get('work_id') == target_work_id
                    for table in ('fetish_work_links', 'compound_work_links')
                    for link in updated[table]
                )
            )
            and all(find_row('work_aliases', 'alias_id', alias_id) is None for alias_id in removed_alias_ids)
            and all(
                rows_equal('review_queue', find_row('review_queue', 'review_id', target['review_id']), target)
                for _, target, _ in target_reviews
            )
        )
        if already_applied:
            continue

        require_exact('works_master', 'work_id', expected_work, correction_id)
        if any(
            row['work_id'] != source_work_id and row.get('normalized_title') == target_work['normalized_title']
            for row in updated['works_master']
        ):
            raise ValueError(f'work catalog correction canonical collision: {correction_id}')
        for expected, expected_identifiers in removed_editions:
            require_exact('work_editions', 'edition_id', expected, correction_id)
            actual_identifiers = sorted(
                (
                    row
                    for row in updated.get('work_edition_identifiers', [])
                    if row.get('edition_id') == expected['edition_id']
                ),
                key=lambda row: row['identifier_id'],
            )
            if actual_identifiers != sorted(expected_identifiers, key=lambda row: row['identifier_id']):
                raise ValueError(f'work catalog correction edition removal identifier drift: {correction_id}')
        for target, identifiers in added_editions:
            if find_row('work_editions', 'edition_id', target['edition_id']) is not None or any(
                _edition_key(row.get('canonical_url')) == _edition_key(target['canonical_url'])
                for row in updated['work_editions']
            ):
                raise ValueError(f'work catalog correction edition addition collision: {correction_id}')
            for identifier in identifiers:
                if find_row('work_edition_identifiers', 'identifier_id', identifier['identifier_id']) is not None:
                    raise ValueError(f'work catalog correction identifier addition collision: {correction_id}')
                if any(
                    (row['scheme'], row['authority'], row['value'])
                    == (identifier['scheme'], identifier['authority'], identifier['value'])
                    for row in updated['work_edition_identifiers']
                ):
                    raise ValueError(f'work catalog correction identifier addition collision: {correction_id}')
        for target in added_aliases:
            if find_row('work_aliases', 'alias_id', target['alias_id']) is not None or any(
                row['work_id'] == target_work_id and row['normalized_alias'] == target['normalized_alias']
                for row in updated['work_aliases']
            ):
                raise ValueError(f'work catalog correction alias addition collision: {correction_id}')

        if correction_type == 'split_misassigned_edition':
            if find_row('works_master', 'work_id', target_work_id) is not None:
                raise ValueError(f'work catalog correction target collision: {correction_id}')
            updated['works_master'].append(copy.deepcopy(target_work))
        else:
            source_work = find_row('works_master', 'work_id', source_work_id)
            source_work.clear()
            source_work.update(copy.deepcopy(target_work))

        for target, identifiers in added_editions:
            updated['work_editions'].append(copy.deepcopy(target))
            updated['work_edition_identifiers'].extend(copy.deepcopy(identifiers))
        updated['work_aliases'].extend(copy.deepcopy(added_aliases))

        for expected, target in target_editions:
            edition = require_exact('work_editions', 'edition_id', expected, correction_id)
            edition.clear()
            edition.update(target)
        for table, expected, target, allow_missing in target_links:
            link = find_row(table, 'link_id', expected['link_id'])
            if link is None and allow_missing:
                collision = find_row(table, 'link_id', target['link_id'])
                if collision is not None and collision != target:
                    raise ValueError(f'work catalog correction link collision: {correction_id}')
                continue
            link = require_exact(table, 'link_id', expected, correction_id)
            collision = find_row(table, 'link_id', target['link_id'])
            if collision is not None and collision is not link:
                raise ValueError(f'work catalog correction link collision: {correction_id}')
            link.clear()
            link.update(target)
        for expected, expected_identifiers in removed_editions:
            if any(
                link.get('edition_id') == expected['edition_id']
                for link in updated['fetish_work_links'] + updated['compound_work_links']
            ):
                raise ValueError(f'work catalog correction edition still referenced: {correction_id}')
            removed_identifier_ids = {row['identifier_id'] for row in expected_identifiers}
            updated['work_edition_identifiers'] = [
                row for row in updated['work_edition_identifiers'] if row['identifier_id'] not in removed_identifier_ids
            ]
            updated['work_editions'] = [
                row for row in updated['work_editions'] if row['edition_id'] != expected['edition_id']
            ]

        for expected, allow_missing in removed_aliases:
            alias = find_row('work_aliases', 'alias_id', expected['alias_id'])
            if alias is None and allow_missing:
                continue
            require_exact('work_aliases', 'alias_id', expected, correction_id)
            if any(
                link.get('alias_id') == expected['alias_id']
                for link in updated['fetish_work_links'] + updated['compound_work_links']
            ):
                raise ValueError(f'work catalog correction alias still referenced: {correction_id}')
            updated['work_aliases'] = [
                row for row in updated['work_aliases'] if row['alias_id'] != expected['alias_id']
            ]
        for expected, target, accepted_updated_at in target_reviews:
            review = require_exact(
                'review_queue',
                'review_id',
                expected,
                correction_id,
                accepted_updated_at,
            )
            review.clear()
            review.update(copy.deepcopy(target))
        _sort_catalog_rows(updated)
        validate_catalog(updated)

    affected_link_owners = set()
    deferred_link_removals.sort(key=lambda row: (row[0], row[3], -int(row[1]['position'])))
    for table, expected, _allow_missing, owner, _source_url, _correction_id in deferred_link_removals:
        link = find_row(table, 'link_id', expected['link_id'])
        if link is None:
            continue
        updated[table] = [row for row in updated[table] if row['link_id'] != expected['link_id']]
        affected_link_owners.add((table, owner))
    for table, owner in affected_link_owners:
        owner_fields = ('fetish_id',) if table == 'fetish_work_links' else ('id_a', 'id_b')
        owner_links = sorted(
            (row for row in updated[table] if tuple(int(row[field]) for field in owner_fields) == owner),
            key=lambda row: (int(row['position']), row['link_id']),
        )
        for position, link in enumerate(owner_links):
            link['position'] = position
    for work_id in quarantined_work_ids:
        if any(
            link.get('work_id') == work_id
            for table in ('fetish_work_links', 'compound_work_links')
            for link in updated[table]
        ):
            raise ValueError(f'work catalog correction quarantined work still referenced: {work_id}')

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

    _canonicalize_alias_and_link_ids(updated, reindex_positions=True)
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
