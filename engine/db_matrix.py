"""Matrix row conversion and persistence helpers."""

import json

from . import db_work_catalog

SAVE_MATRIX_SQL = """
    INSERT INTO matrix (fetish_id, question_id, yes_count, total_count)
    VALUES (%s, %s, %s, %s)
    ON CONFLICT (fetish_id, question_id) DO UPDATE
    SET yes_count   = matrix.yes_count   + EXCLUDED.yes_count,
        total_count = matrix.total_count + EXCLUDED.total_count
"""

IMPORT_MATRIX_SQL = """
    INSERT INTO matrix (fetish_id, question_id, yes_count, total_count)
    VALUES %s
    ON CONFLICT (fetish_id, question_id) DO UPDATE
        SET yes_count   = EXCLUDED.yes_count,
            total_count = EXCLUDED.total_count
"""


def build_save_matrix_rows(all_updates, idx_to_db_id=None, fetishes=None):
    rows = []
    for fetish_idx, updates in all_updates.items():
        if idx_to_db_id is not None:
            db_id = idx_to_db_id.get(fetish_idx)
        elif fetishes is not None and fetish_idx < len(fetishes):
            db_id = fetishes[fetish_idx]['id']
        else:
            db_id = None
        if db_id is None:
            continue
        for question_idx, delta_yes, delta_total in updates:
            rows.append((db_id, question_idx, delta_yes, delta_total))
    return rows


def build_import_matrix_rows(updates, idx_map):
    id_map = {idx: fetish_id for fetish_id, idx in idx_map.items()}
    rows = []
    for fetish_idx, questions in updates.items():
        db_id = id_map.get(fetish_idx)
        if db_id is None:
            continue
        for question_idx, yes, total in questions:
            rows.append((db_id, question_idx, yes, total))
    return rows


def save_matrix_updates(all_updates, idx_to_db_id, fetishes, *, get_conn, put_conn):
    rows = build_save_matrix_rows(all_updates, idx_to_db_id=idx_to_db_id, fetishes=fetishes)
    if not rows:
        return
    conn = get_conn()
    try:
        with conn:
            cur = conn.cursor()
            cur.executemany(SAVE_MATRIX_SQL, rows)
    finally:
        put_conn(conn)


def import_matrix_rows(updates, idx_map, *, get_conn, put_conn, execute_values):
    rows = build_import_matrix_rows(updates, idx_map)
    if not rows:
        return
    conn = get_conn()
    try:
        with conn:
            cur = conn.cursor()
            execute_values(cur, IMPORT_MATRIX_SQL, rows)
    finally:
        put_conn(conn)


def restore_matrix_snapshot(fetishes, matrix_rows, *, get_conn, put_conn, execute_values, work_catalog=None):
    conn = get_conn()
    try:
        with conn:
            cur = conn.cursor()
            if fetishes:
                execute_values(
                    cur,
                    'INSERT INTO fetishes (id, name, "desc", works) VALUES %s',
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
            if work_catalog is not None:
                db_work_catalog.ensure_schema(cur)
                db_work_catalog.lock_catalog(cur)
                db_work_catalog.replace_catalog(cur, work_catalog, execute_values=execute_values)
            rows = [
                (
                    int(row['fetish_id']),
                    int(row['question_id']),
                    float(row['yes']),
                    float(row['total']),
                )
                for row in matrix_rows
            ]
            if rows:
                execute_values(cur, IMPORT_MATRIX_SQL, rows)
    finally:
        put_conn(conn)


def parse_fetish_rows(rows):
    parsed = []
    for row in rows:
        try:
            works = json.loads(row[3]) if row[3] else []
            if not isinstance(works, list):
                works = []
        except (TypeError, json.JSONDecodeError):
            works = []
        parsed.append({'id': row[0], 'name': row[1], 'desc': row[2], 'works': works})
    return parsed


def load_fetishes(*, get_conn, put_conn):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute('SELECT id, name, "desc", works FROM fetishes ORDER BY id')
        return parse_fetish_rows(cur.fetchall())
    finally:
        put_conn(conn)


def matrix_from_rows(fetishes, questions, rows):
    nf = len(fetishes)
    nq = len(questions)
    id_to_idx = {fetish['id']: idx for idx, fetish in enumerate(fetishes)}
    yes = [[0.0] * nq for _ in range(nf)]
    total = [[0.0] * nq for _ in range(nf)]
    for fetish_id, question_idx, yes_count, total_count in rows:
        idx = id_to_idx.get(fetish_id)
        if idx is not None and 0 <= question_idx < nq:
            yes[idx][question_idx] = yes_count
            total[idx][question_idx] = total_count
    return {'yes': yes, 'total': total}


def load_matrix(fetishes, questions, *, get_conn, put_conn):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute('SELECT fetish_id, question_id, yes_count, total_count FROM matrix')
        return matrix_from_rows(fetishes, questions, cur.fetchall())
    finally:
        put_conn(conn)
