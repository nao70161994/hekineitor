"""Catalog schema upgrades and structural validation."""

import copy

from engine.work_catalog_identifiers import build_edition_identifier
from work_utils import safe_work_url

CATALOG_SCHEMA_VERSION = 2
SUPPORTED_CATALOG_SCHEMA_VERSIONS = frozenset({1, CATALOG_SCHEMA_VERSION})


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


