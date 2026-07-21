"""Compatibility facade for database persistence helpers."""

import json

from . import db_work_catalog
from .db_config import load_config, save_config_value
from .db_matrix import (
    IMPORT_MATRIX_SQL,
    SAVE_MATRIX_SQL,
    build_import_matrix_rows,
    build_save_matrix_rows,
    import_matrix_rows,
    load_fetishes,
    load_matrix,
    matrix_from_rows,
    parse_fetish_rows,
    restore_matrix_snapshot,
    save_matrix_updates,
)
from .db_stats import (
    _move_promoted_stats_history,
    increment_fetish_log,
    increment_stat,
    load_disabled_questions,
    load_dropoff_totals,
    load_feedback_totals,
    load_fetish_history,
    load_fetish_log,
    load_quality_event_totals,
    load_stats,
    load_stats_history,
    promoted_stats_history_repair_report,
    record_daily_stat,
    repair_promoted_stats_history,
    save_disabled_questions,
    toggle_question_disabled,
)
from .db_work_migrations import (
    DEFAULT_RECOMMENDED_WORKS_BY_NAME,
    DIRECT_WORK_TITLE_ALIASES,
    DIRECT_WORK_URLS_BY_TITLE,
    RECOMMENDED_WORK_REPLACEMENTS_BY_TITLE,
    _canonical_work_title,
    _is_search_work_url,
    _recommended_work_dict,
    backfill_empty_recommended_works,
    backfill_recommended_work_urls,
    build_direct_work_url_lookup,
    default_recommended_works_for_name,
    recommended_work_replacement_for_title,
)


def ensure_schema(engine, *, get_conn, put_conn, execute_values, player_base_id, build_initial_matrix):
    conn = get_conn()
    try:
        with conn:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS fetishes (
                    id   INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    "desc" TEXT NOT NULL,
                    works TEXT NOT NULL DEFAULT '[]'
                )
            """)
            cur.execute("ALTER TABLE fetishes ADD COLUMN IF NOT EXISTS works TEXT NOT NULL DEFAULT '[]'")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS matrix (
                    fetish_id   INTEGER,
                    question_id INTEGER,
                    yes_count   REAL NOT NULL,
                    total_count REAL NOT NULL,
                    PRIMARY KEY (fetish_id, question_id)
                )
            """)
            cur.execute('SELECT COUNT(*) FROM fetishes')
            if cur.fetchone()[0] == 0:
                seed_fetishes = engine._load_json('fetishes.json')
                execute_values(
                    cur,
                    'INSERT INTO fetishes (id, name, "desc", works) VALUES %s',
                    [
                        (
                            fetish['id'],
                            fetish['name'],
                            fetish['desc'],
                            json.dumps(fetish.get('works', []), ensure_ascii=False),
                        )
                        for fetish in seed_fetishes
                    ],
                )
            cur.execute('SELECT COUNT(*) FROM matrix')
            if cur.fetchone()[0] == 0:
                seed_fetishes = engine._load_json('fetishes.json')
                engine._seed_db(cur, seed_fetishes)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS stats (
                    key   TEXT PRIMARY KEY,
                    value INTEGER NOT NULL DEFAULT 0
                )
            """)
            for key in ('start_count', 'completion_count', 'learn_count', 'play_count'):
                cur.execute('INSERT INTO stats (key, value) VALUES (%s, 0) ON CONFLICT DO NOTHING', (key,))
            cur.execute("""
                CREATE TABLE IF NOT EXISTS fetish_log (
                    fetish_id INTEGER PRIMARY KEY,
                    guessed   INTEGER NOT NULL DEFAULT 0,
                    correct   INTEGER NOT NULL DEFAULT 0,
                    wrong     INTEGER NOT NULL DEFAULT 0
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    data       TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS rate_limits (
                    scope TEXT NOT NULL,
                    client_ip TEXT NOT NULL,
                    timestamps JSONB NOT NULL,
                    updated_at DOUBLE PRECISION NOT NULL,
                    window_seconds INTEGER NOT NULL DEFAULT 60,
                    PRIMARY KEY (scope, client_ip)
                )
            """)
            cur.execute('ALTER TABLE rate_limits ADD COLUMN IF NOT EXISTS window_seconds INTEGER NOT NULL DEFAULT 60')
            cur.execute('CREATE INDEX IF NOT EXISTS rate_limits_updated_at_idx ON rate_limits(updated_at)')
            cur.execute("""
                CREATE TABLE IF NOT EXISTS config (
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS stats_history (
                    date  TEXT NOT NULL,
                    key   TEXT NOT NULL,
                    value INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (date, key)
                )
            """)
            cur.execute('SELECT id FROM fetishes')
            existing_ids = {row[0] for row in cur.fetchall()}
            seed = [fetish for fetish in engine._load_json('fetishes.json') if fetish['id'] < player_base_id]
            new_fetishes = [fetish for fetish in seed if fetish['id'] not in existing_ids]
            if new_fetishes:
                execute_values(
                    cur,
                    'INSERT INTO fetishes (id, name, "desc", works) VALUES %s ON CONFLICT DO NOTHING',
                    [
                        (
                            fetish['id'],
                            fetish['name'],
                            fetish['desc'],
                            json.dumps(fetish.get('works', []), ensure_ascii=False),
                        )
                        for fetish in new_fetishes
                    ],
                )
                nq = len(engine.questions)
                full_yes, full_total = build_initial_matrix(len(seed), nq)
                seed_id_to_idx = {fetish['id']: idx for idx, fetish in enumerate(seed)}
                new_rows = [
                    (
                        fetish['id'],
                        question_idx,
                        full_yes[seed_id_to_idx[fetish['id']]][question_idx],
                        full_total[seed_id_to_idx[fetish['id']]][question_idx],
                    )
                    for fetish in new_fetishes
                    for question_idx in range(nq)
                ]
                execute_values(
                    cur,
                    'INSERT INTO matrix (fetish_id, question_id, yes_count, total_count) VALUES %s ON CONFLICT DO NOTHING',
                    new_rows,
                )
            for fetish in seed:
                cur.execute(
                    'UPDATE fetishes SET name=%s, "desc"=%s WHERE id=%s',
                    (fetish['name'], fetish['desc'], fetish['id']),
                )
            backfill_empty_recommended_works(cur)
            backfill_recommended_work_urls(cur, seed)
            db_work_catalog.migrate_legacy_catalog(
                cur,
                compound_data=engine._load_json('compound_works.json'),
                execute_values=execute_values,
            )
            nq = len(engine.questions)
            cur.execute('SELECT MAX(question_id) FROM matrix')
            max_qid = cur.fetchone()[0]
            if max_qid is not None and max_qid < nq - 1:
                cur.execute('SELECT id FROM fetishes')
                all_fids = [row[0] for row in cur.fetchall()]
                alpha = 2.0
                full_yes, full_total = build_initial_matrix(len(seed), nq)
                seed_id_to_idx = {fetish['id']: idx for idx, fetish in enumerate(seed)}
                new_question_rows = []
                for fetish_id in all_fids:
                    seed_idx = seed_id_to_idx.get(fetish_id)
                    for question_idx in range(max_qid + 1, nq):
                        if seed_idx is None:
                            new_question_rows.append((fetish_id, question_idx, alpha, alpha * 2.0))
                        else:
                            new_question_rows.append(
                                (
                                    fetish_id,
                                    question_idx,
                                    full_yes[seed_idx][question_idx],
                                    full_total[seed_idx][question_idx],
                                )
                            )
                if new_question_rows:
                    execute_values(
                        cur,
                        'INSERT INTO matrix (fetish_id, question_id, yes_count, total_count) VALUES %s ON CONFLICT DO NOTHING',
                        new_question_rows,
                    )
    finally:
        put_conn(conn)


def insert_fetishes_with_neutral_matrix(fetishes, question_count, *, get_conn, put_conn, execute_values):
    if not fetishes:
        return 0
    alpha = 2.0
    conn = get_conn()
    try:
        with conn:
            cur = conn.cursor()
            execute_values(
                cur,
                'INSERT INTO fetishes (id, name, "desc", works) VALUES %s ON CONFLICT DO NOTHING',
                [
                    (
                        fetish['id'],
                        fetish['name'],
                        fetish.get('desc', fetish['name']),
                        json.dumps(fetish.get('works', []), ensure_ascii=False),
                    )
                    for fetish in fetishes
                ],
            )
            rows = [
                (fetish['id'], question_idx, alpha, alpha * 2.0)
                for fetish in fetishes
                for question_idx in range(question_count)
            ]
            if rows:
                execute_values(
                    cur,
                    'INSERT INTO matrix (fetish_id, question_id, yes_count, total_count) VALUES %s ON CONFLICT DO NOTHING',
                    rows,
                )
            return len(fetishes)
    finally:
        put_conn(conn)


def insert_fetish_with_matrix(name, desc, yes_row, total_row, *, get_conn, put_conn, execute_values, player_base_id):
    nq = len(yes_row)
    conn = get_conn()
    try:
        with conn:
            cur = conn.cursor()
            cur.execute('SELECT pg_advisory_xact_lock(%s)', (player_base_id,))
            cur.execute(
                'SELECT COALESCE(MAX(id), %s - 1) + 1 FROM fetishes WHERE id >= %s',
                (player_base_id, player_base_id),
            )
            db_id = max(cur.fetchone()[0], player_base_id)
            cur.execute(
                'INSERT INTO fetishes (id, name, "desc", works) VALUES (%s, %s, %s, %s)',
                (db_id, name, desc, '[]'),
            )
            rows = [(db_id, question_idx, yes_row[question_idx], total_row[question_idx]) for question_idx in range(nq)]
            execute_values(
                cur,
                'INSERT INTO matrix (fetish_id, question_id, yes_count, total_count) VALUES %s',
                rows,
            )
            return db_id
    finally:
        put_conn(conn)


def update_fetish_fields(
    fetish_id, *, name=None, desc=None, works=None, get_conn, put_conn, execute_values=None
):
    conn = get_conn()
    try:
        with conn:
            cur = conn.cursor()
            next_catalog = None
            if works is not None:
                if execute_values is None:
                    raise ValueError('execute_values is required when updating recommended works')
                db_work_catalog.lock_catalog(cur)
                current_catalog = db_work_catalog.load_catalog_from_cursor(cur)
                next_catalog = db_work_catalog.replace_fetish_works(current_catalog, fetish_id, works)
            updates = []
            params = []
            if name is not None:
                updates.append('name=%s')
                params.append(name)
            if desc is not None:
                updates.append('"desc"=%s')
                params.append(desc)
            if works is not None:
                updates.append('works=%s')
                params.append(json.dumps(works, ensure_ascii=False))
            if updates:
                params.append(fetish_id)
                cur.execute(f'UPDATE fetishes SET {", ".join(updates)} WHERE id=%s', params)
            if next_catalog is not None:
                db_work_catalog.replace_catalog(cur, next_catalog, execute_values=execute_values)
    finally:
        put_conn(conn)


def replace_compound_work_rows(id_a, id_b, works, *, get_conn, put_conn, execute_values):
    conn = get_conn()
    try:
        with conn:
            cur = conn.cursor()
            db_work_catalog.lock_catalog(cur)
            current = db_work_catalog.load_catalog_from_cursor(cur)
            id_a, id_b = sorted((int(id_a), int(id_b)))
            existed = any(
                int(row['id_a']) == id_a and int(row['id_b']) == id_b
                for row in current['compound_work_links']
            )
            if not works and not existed:
                return False
            updated = db_work_catalog.replace_compound_works(current, id_a, id_b, works)
            db_work_catalog.replace_catalog(cur, updated, execute_values=execute_values)
            return True
    finally:
        put_conn(conn)


def delete_fetish_rows(fetish_id, *, get_conn, put_conn):
    conn = get_conn()
    try:
        with conn:
            cur = conn.cursor()
            cur.execute('DELETE FROM fetishes WHERE id = %s', (fetish_id,))
            cur.execute('DELETE FROM matrix WHERE fetish_id = %s', (fetish_id,))
    finally:
        put_conn(conn)


def merge_fetish_rows_db(
    id_keep, id_remove, *, new_name=None, new_desc=None, keep_name=None, keep_desc=None, get_conn, put_conn
):
    conn = get_conn()
    try:
        with conn:
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE matrix AS m
                SET yes_count   = m.yes_count   + rm.yes_count,
                    total_count = m.total_count + rm.total_count
                FROM matrix rm
                WHERE m.fetish_id = %s AND rm.fetish_id = %s
                  AND m.question_id = rm.question_id
            """,
                (id_keep, id_remove),
            )
            cur.execute('DELETE FROM fetishes WHERE id = %s', (id_remove,))
            cur.execute('DELETE FROM matrix WHERE fetish_id = %s', (id_remove,))
            cur.execute(
                """
                INSERT INTO fetish_log (fetish_id, guessed, correct, wrong)
                SELECT %s, guessed, correct, wrong FROM fetish_log WHERE fetish_id = %s
                ON CONFLICT (fetish_id) DO UPDATE
                SET guessed = fetish_log.guessed + EXCLUDED.guessed,
                    correct = fetish_log.correct + EXCLUDED.correct,
                    wrong   = fetish_log.wrong   + EXCLUDED.wrong
            """,
                (id_keep, id_remove),
            )
            cur.execute('DELETE FROM fetish_log WHERE fetish_id = %s', (id_remove,))
            if new_name or new_desc:
                cur.execute(
                    'UPDATE fetishes SET name=%s, "desc"=%s WHERE id=%s',
                    (new_name or keep_name, new_desc or keep_desc, id_keep),
                )
    finally:
        put_conn(conn)


def promote_fetish_id(old_id, new_id, *, get_conn, put_conn):
    conn = get_conn()
    try:
        with conn:
            cur = conn.cursor()
            cur.execute('UPDATE fetishes  SET id = %s WHERE id = %s', (new_id, old_id))
            cur.execute('UPDATE matrix    SET fetish_id = %s WHERE fetish_id = %s', (new_id, old_id))
            cur.execute('UPDATE fetish_log SET fetish_id = %s WHERE fetish_id = %s', (new_id, old_id))
            _move_promoted_stats_history(cur, old_id, new_id)
    finally:
        put_conn(conn)


def promote_player_fetish_to_seed(old_id, *, player_base_id, get_conn, put_conn):
    conn = get_conn()
    try:
        with conn:
            cur = conn.cursor()
            cur.execute('SELECT pg_advisory_xact_lock(%s)', (player_base_id,))
            cur.execute('SELECT id FROM fetishes WHERE id = %s AND id >= %s', (old_id, player_base_id))
            if cur.fetchone() is None:
                return None
            cur.execute(
                """
                SELECT candidate
                FROM generate_series(0, %s - 1) AS candidate
                WHERE NOT EXISTS (SELECT 1 FROM fetishes WHERE id = candidate)
                ORDER BY candidate
                LIMIT 1
            """,
                (player_base_id,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            new_id = int(row[0])
            cur.execute('UPDATE fetishes  SET id = %s WHERE id = %s', (new_id, old_id))
            cur.execute('UPDATE matrix    SET fetish_id = %s WHERE fetish_id = %s', (new_id, old_id))
            cur.execute('UPDATE fetish_log SET fetish_id = %s WHERE fetish_id = %s', (new_id, old_id))
            _move_promoted_stats_history(cur, old_id, new_id)
            return new_id
    finally:
        put_conn(conn)


def build_seed_matrix_rows(fetishes, question_count, *, build_initial_matrix):
    yes, total = build_initial_matrix(len(fetishes), question_count)
    return [
        (fetish['id'], question_idx, yes[fetish_idx][question_idx], total[fetish_idx][question_idx])
        for fetish_idx, fetish in enumerate(fetishes)
        for question_idx in range(question_count)
    ]


def seed_matrix(cur, fetishes, question_count, *, execute_values, build_initial_matrix):
    rows = build_seed_matrix_rows(fetishes, question_count, build_initial_matrix=build_initial_matrix)
    execute_values(cur, 'INSERT INTO matrix (fetish_id, question_id, yes_count, total_count) VALUES %s', rows)
