"""PostgreSQL persistence for the normalized recommended-work catalog."""

import json

from .work_catalog import (
    build_catalog_from_inline,
    delete_fetish_references,
    promote_fetish_references,
    replace_compound_works,
    replace_fetish_works,
    validate_catalog,
)

_CATALOG_LOCK_SQL = "SELECT pg_advisory_xact_lock(hashtext('recommended_work_catalog_write'))"

_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS works_master (
        work_id TEXT PRIMARY KEY,
        canonical_title TEXT NOT NULL,
        normalized_title TEXT NOT NULL,
        media_type TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'active'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS work_editions (
        edition_id TEXT PRIMARY KEY,
        work_id TEXT NOT NULL REFERENCES works_master(work_id) ON DELETE CASCADE,
        asin TEXT,
        canonical_url TEXT NOT NULL DEFAULT '',
        format TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'active'
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS work_editions_asin_unique ON work_editions(asin) WHERE asin IS NOT NULL AND asin <> ''",
    """
    CREATE TABLE IF NOT EXISTS work_aliases (
        alias_id TEXT PRIMARY KEY,
        work_id TEXT NOT NULL REFERENCES works_master(work_id) ON DELETE CASCADE,
        alias TEXT NOT NULL,
        normalized_alias TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS fetish_work_links (
        link_id TEXT PRIMARY KEY,
        fetish_id INTEGER NOT NULL REFERENCES fetishes(id) ON DELETE CASCADE,
        work_id TEXT NOT NULL REFERENCES works_master(work_id) ON DELETE CASCADE,
        edition_id TEXT REFERENCES work_editions(edition_id) ON DELETE RESTRICT,
        alias_id TEXT REFERENCES work_aliases(alias_id) ON DELETE RESTRICT,
        position INTEGER NOT NULL CHECK (position >= 0),
        context_label TEXT NOT NULL DEFAULT '',
        recommendation_reason TEXT NOT NULL DEFAULT '',
        UNIQUE (fetish_id, position)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS compound_work_links (
        link_id TEXT PRIMARY KEY,
        fetish_id_a INTEGER NOT NULL REFERENCES fetishes(id) ON DELETE CASCADE,
        fetish_id_b INTEGER NOT NULL REFERENCES fetishes(id) ON DELETE CASCADE,
        work_id TEXT NOT NULL REFERENCES works_master(work_id) ON DELETE CASCADE,
        edition_id TEXT REFERENCES work_editions(edition_id) ON DELETE RESTRICT,
        alias_id TEXT REFERENCES work_aliases(alias_id) ON DELETE RESTRICT,
        position INTEGER NOT NULL CHECK (position >= 0),
        context_label TEXT NOT NULL DEFAULT '',
        recommendation_reason TEXT NOT NULL DEFAULT '',
        CHECK (fetish_id_a < fetish_id_b),
        UNIQUE (fetish_id_a, fetish_id_b, position)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS work_identity_reviews (
        review_id TEXT PRIMARY KEY,
        review_type TEXT NOT NULL,
        candidate_key TEXT NOT NULL,
        work_ids JSONB NOT NULL,
        titles JSONB NOT NULL,
        asins JSONB NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        decision TEXT NOT NULL DEFAULT '',
        target_work_id TEXT REFERENCES works_master(work_id) ON DELETE SET NULL,
        version INTEGER NOT NULL DEFAULT 1,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
)


def lock_catalog(cur):
    cur.execute(_CATALOG_LOCK_SQL)


def ensure_schema(cur):
    for statement in _SCHEMA_STATEMENTS:
        cur.execute(statement)


def _compound_rows(compound_data):
    if isinstance(compound_data, list):
        return list(compound_data)
    rows = []
    for key, works in sorted((compound_data or {}).items()):
        parts = str(key).split(',')
        if len(parts) != 2:
            continue
        try:
            id_a, id_b = (int(value) for value in parts)
        except ValueError:
            continue
        rows.append({'key': key, 'id_a': id_a, 'id_b': id_b, 'works': works})
    return rows


def _legacy_fetishes(cur):
    cur.execute('SELECT id, name, "desc", works FROM fetishes ORDER BY id')
    rows = []
    for fetish_id, name, desc, works_raw in cur.fetchall():
        try:
            works = json.loads(works_raw) if works_raw else []
        except (TypeError, json.JSONDecodeError):
            works = []
        if not isinstance(works, list):
            works = []
        rows.append({'id': int(fetish_id), 'name': name, 'desc': desc, 'works': works})
    return rows


def catalog_is_empty(cur):
    cur.execute('SELECT COUNT(*) FROM works_master')
    return int(cur.fetchone()[0] or 0) == 0


def replace_catalog(cur, catalog, *, execute_values):
    """Replace the complete catalog inside the caller-owned transaction."""
    validate_catalog(catalog)
    for table in (
        'work_identity_reviews',
        'compound_work_links',
        'fetish_work_links',
        'work_aliases',
        'work_editions',
        'works_master',
    ):
        cur.execute(f'DELETE FROM {table}')

    batches = (
        (
            'INSERT INTO works_master (work_id, canonical_title, normalized_title, media_type, status) VALUES %s',
            [
                (
                    row['work_id'],
                    row['canonical_title'],
                    row['normalized_title'],
                    row.get('media_type', ''),
                    row.get('status', 'active'),
                )
                for row in catalog['works_master']
            ],
        ),
        (
            'INSERT INTO work_editions (edition_id, work_id, asin, canonical_url, format, status) VALUES %s',
            [
                (
                    row['edition_id'],
                    row['work_id'],
                    row.get('asin') or None,
                    row.get('canonical_url', ''),
                    row.get('format', ''),
                    row.get('status', 'active'),
                )
                for row in catalog['work_editions']
            ],
        ),
        (
            'INSERT INTO work_aliases (alias_id, work_id, alias, normalized_alias) VALUES %s',
            [
                (row['alias_id'], row['work_id'], row['alias'], row['normalized_alias'])
                for row in catalog['work_aliases']
            ],
        ),
        (
            'INSERT INTO fetish_work_links (link_id, fetish_id, work_id, edition_id, alias_id, position, context_label, recommendation_reason) VALUES %s',
            [
                (
                    row['link_id'],
                    row['fetish_id'],
                    row['work_id'],
                    row.get('edition_id'),
                    row.get('alias_id'),
                    row['position'],
                    row.get('context_label', ''),
                    row.get('recommendation_reason', ''),
                )
                for row in catalog['fetish_work_links']
            ],
        ),
        (
            'INSERT INTO compound_work_links (link_id, fetish_id_a, fetish_id_b, work_id, edition_id, alias_id, position, context_label, recommendation_reason) VALUES %s',
            [
                (
                    row['link_id'],
                    row['id_a'],
                    row['id_b'],
                    row['work_id'],
                    row.get('edition_id'),
                    row.get('alias_id'),
                    row['position'],
                    row.get('context_label', ''),
                    row.get('recommendation_reason', ''),
                )
                for row in catalog['compound_work_links']
            ],
        ),
        (
            'INSERT INTO work_identity_reviews (review_id, review_type, candidate_key, work_ids, titles, asins, '
            'status, decision, target_work_id, version, updated_at) VALUES %s',
            [
                (
                    row['review_id'],
                    row['review_type'],
                    row['candidate_key'],
                    json.dumps(row.get('work_ids', []), ensure_ascii=False),
                    json.dumps(row.get('titles', []), ensure_ascii=False),
                    json.dumps(row.get('asins', []), ensure_ascii=False),
                    row.get('status', 'pending'),
                    row.get('decision', ''),
                    row.get('target_work_id'),
                    int(row.get('version', 1)),
                    row.get('updated_at') or '1970-01-01T00:00:00+00:00',
                )
                for row in catalog['review_queue']
            ],
        ),
    )
    for statement, rows in batches:
        if rows:
            execute_values(cur, statement, rows)
    return {
        'works_master': len(catalog['works_master']),
        'work_editions': len(catalog['work_editions']),
        'work_aliases': len(catalog['work_aliases']),
        'fetish_work_links': len(catalog['fetish_work_links']),
        'compound_work_links': len(catalog['compound_work_links']),
        'review_queue': len(catalog['review_queue']),
    }


def migrate_legacy_catalog(cur, *, compound_data, execute_values):
    """Create a shadow catalog exactly once; later writes belong to the catalog repository."""
    ensure_schema(cur)
    lock_catalog(cur)
    if not catalog_is_empty(cur):
        return {'migrated': False}
    catalog = build_catalog_from_inline(_legacy_fetishes(cur), compound_rows=_compound_rows(compound_data))
    counts = replace_catalog(cur, catalog, execute_values=execute_values)
    return {'migrated': True, **counts}


def _json_list(value):
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def _serialized_timestamp(value):
    if value is None or isinstance(value, str):
        return value
    isoformat = getattr(value, 'isoformat', None)
    return isoformat() if callable(isoformat) else str(value)


def load_catalog_from_cursor(cur):
    """Read one catalog snapshot from the caller's transaction."""
    cur.execute(
        'SELECT work_id, canonical_title, normalized_title, media_type, status FROM works_master ORDER BY work_id'
    )
    works_master = [
        {
            'work_id': row[0],
            'canonical_title': row[1],
            'normalized_title': row[2],
            'media_type': row[3],
            'status': row[4],
        }
        for row in cur.fetchall()
    ]
    cur.execute(
        'SELECT edition_id, work_id, asin, canonical_url, format, status FROM work_editions ORDER BY edition_id'
    )
    work_editions = [
        {
            'edition_id': row[0],
            'work_id': row[1],
            'asin': row[2] or '',
            'canonical_url': row[3],
            'format': row[4],
            'status': row[5],
        }
        for row in cur.fetchall()
    ]
    cur.execute('SELECT alias_id, work_id, alias, normalized_alias FROM work_aliases ORDER BY alias_id')
    work_aliases = [
        {'alias_id': row[0], 'work_id': row[1], 'alias': row[2], 'normalized_alias': row[3]} for row in cur.fetchall()
    ]
    cur.execute(
        'SELECT link_id, fetish_id, work_id, edition_id, alias_id, position, '
        'context_label, recommendation_reason FROM fetish_work_links '
        'ORDER BY fetish_id, position, link_id'
    )
    fetish_work_links = [
        {
            'link_id': row[0],
            'fetish_id': row[1],
            'work_id': row[2],
            'edition_id': row[3],
            'alias_id': row[4],
            'position': row[5],
            'context_label': row[6],
            'recommendation_reason': row[7],
        }
        for row in cur.fetchall()
    ]
    cur.execute(
        'SELECT link_id, fetish_id_a, fetish_id_b, work_id, edition_id, alias_id, position, '
        'context_label, recommendation_reason FROM compound_work_links '
        'ORDER BY fetish_id_a, fetish_id_b, position, link_id'
    )
    compound_work_links = [
        {
            'link_id': row[0],
            'id_a': row[1],
            'id_b': row[2],
            'work_id': row[3],
            'edition_id': row[4],
            'alias_id': row[5],
            'position': row[6],
            'context_label': row[7],
            'recommendation_reason': row[8],
        }
        for row in cur.fetchall()
    ]
    cur.execute(
        'SELECT review_id, review_type, candidate_key, work_ids, titles, asins, status, '
        'decision, target_work_id, version, updated_at FROM work_identity_reviews ORDER BY review_id'
    )
    review_queue = [
        {
            'review_id': row[0],
            'review_type': row[1],
            'candidate_key': row[2],
            'work_ids': _json_list(row[3]),
            'titles': _json_list(row[4]),
            'asins': _json_list(row[5]),
            'status': row[6],
            'decision': row[7],
            'target_work_id': row[8],
            'version': row[9],
            'updated_at': _serialized_timestamp(row[10]),
        }
        for row in cur.fetchall()
    ]
    catalog = {
        'schema_version': 1,
        'works_master': works_master,
        'work_editions': work_editions,
        'work_aliases': work_aliases,
        'fetish_work_links': fetish_work_links,
        'compound_work_links': compound_work_links,
        'review_queue': review_queue,
    }
    validate_catalog(catalog)
    return catalog


def replace_fetish_works_in_transaction(cur, fetish_id, works, *, execute_values, acquire_lock=True):
    """Replace one fetish owner inside the caller-owned DB transaction."""
    if acquire_lock:
        lock_catalog(cur)
    current = load_catalog_from_cursor(cur)
    updated = replace_fetish_works(current, fetish_id, works)
    return replace_catalog(cur, updated, execute_values=execute_values)


def replace_compound_works_in_transaction(cur, id_a, id_b, works, *, execute_values, acquire_lock=True):
    """Replace one compound owner inside the caller-owned DB transaction."""
    if acquire_lock:
        lock_catalog(cur)
    current = load_catalog_from_cursor(cur)
    updated = replace_compound_works(current, id_a, id_b, works)
    return replace_catalog(cur, updated, execute_values=execute_values)


def load_catalog(*, get_conn, put_conn):
    """Load all catalog tables from one repeatable-read snapshot."""
    conn = get_conn()
    try:
        with conn:
            cur = conn.cursor()
            cur.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            return load_catalog_from_cursor(cur)
    finally:
        put_conn(conn)
