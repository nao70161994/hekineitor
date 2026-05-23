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
