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
        for update in updates:
            question_idx, delta_yes, delta_total = update[:3]
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


def restore_matrix_snapshot(
    fetishes,
    matrix_rows,
    *,
    get_conn,
    put_conn,
    execute_values,
    work_catalog=None,
    restored_inline_fetishes=None,
    inline_corrections=None,
    inline_correction_manifests=None,
    legacy_projection_fetishes=None,
    inline_projection_direction='forward',
):
    conn = get_conn()
    try:
        with conn:
            cur = conn.cursor()
            if work_catalog is not None or restored_inline_fetishes:
                db_work_catalog.ensure_schema(cur)
                db_work_catalog.lock_catalog(cur)
            if work_catalog is None and restored_inline_fetishes:
                current = db_work_catalog.load_catalog_from_cursor(cur)
                work_catalog = db_work_catalog.merge_restored_fetish_works(current, restored_inline_fetishes)
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
            inline_fetishes = None
            if work_catalog is not None and (inline_corrections is not None or inline_correction_manifests is not None):
                cur.execute('SELECT id, name, "desc", works FROM fetishes ORDER BY id FOR UPDATE')
                inline_fetishes = parse_fetish_rows(cur.fetchall())
                persisted_works = {row['id']: row.get('works') or [] for row in inline_fetishes}
                if legacy_projection_fetishes is not None:
                    restored_works = {row['id']: row.get('works') or [] for row in legacy_projection_fetishes}
                    for fetish in inline_fetishes:
                        if fetish['id'] in restored_works:
                            fetish['works'] = restored_works[fetish['id']]
                manifests = (
                    tuple(inline_correction_manifests)
                    if inline_correction_manifests is not None
                    else (inline_corrections,)
                )
                if inline_projection_direction == 'canonical':
                    try:
                        projection = db_work_catalog.project_approved_inline_correction_manifests(
                            inline_fetishes,
                            correction_manifests=manifests,
                            tables={'fetish_work_links'},
                        )
                    except ValueError:
                        source = db_work_catalog.project_approved_inline_correction_manifests(
                            inline_fetishes,
                            correction_manifests=manifests,
                            direction='reverse',
                            tables={'fetish_work_links'},
                        )
                        projection = db_work_catalog.project_approved_inline_correction_manifests(
                            source['fetishes'],
                            correction_manifests=manifests,
                            tables={'fetish_work_links'},
                        )
                else:
                    projection = db_work_catalog.project_approved_inline_correction_manifests(
                        inline_fetishes,
                        correction_manifests=manifests,
                        direction=inline_projection_direction,
                        tables={'fetish_work_links'},
                    )
                projected_by_id = {row['id']: row for row in projection['fetishes']}
                for fetish in inline_fetishes:
                    projected = projected_by_id[fetish['id']]
                    if projected.get('works') == persisted_works[fetish['id']]:
                        continue
                    cur.execute(
                        'UPDATE fetishes SET works=%s WHERE id=%s',
                        (json.dumps(projected.get('works') or [], ensure_ascii=False), fetish['id']),
                    )
                inline_fetishes = projection['fetishes']
            if work_catalog is not None:
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
            return inline_fetishes
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
