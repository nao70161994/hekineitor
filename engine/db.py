import json
import time


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


def load_config(defaults, *, use_db, get_conn, put_conn, config_path, read_json):
    values = dict(defaults)
    if use_db():
        conn = get_conn()
        try:
            cur = conn.cursor()
            cur.execute('SELECT key, value FROM config')
            for key, value in cur.fetchall():
                if key in values:
                    values[key] = float(value)
        except Exception:
            pass
        finally:
            put_conn(conn)
    else:
        stored = read_json(config_path, {})
        for key, value in stored.items():
            if key in values:
                values[key] = float(value)
    return values


def save_config_value(key, value, *, use_db, get_conn, put_conn, config_path, read_json, atomic_write):
    if use_db():
        conn = get_conn()
        try:
            with conn:
                cur = conn.cursor()
                cur.execute(
                    "INSERT INTO config (key, value) VALUES (%s, %s) "
                    "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                    (key, str(value)),
                )
        finally:
            put_conn(conn)
    else:
        stored = read_json(config_path, {})
        stored[key] = value
        atomic_write(config_path, stored)


def ensure_schema(engine, *, get_conn, put_conn, execute_values, player_base_id, build_initial_matrix):
    conn = get_conn()
    try:
        with conn:
            cur = conn.cursor()
            cur.execute('''
                CREATE TABLE IF NOT EXISTS fetishes (
                    id   INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    "desc" TEXT NOT NULL,
                    works TEXT NOT NULL DEFAULT '[]'
                )
            ''')
            cur.execute("ALTER TABLE fetishes ADD COLUMN IF NOT EXISTS works TEXT NOT NULL DEFAULT '[]'")
            cur.execute('''
                CREATE TABLE IF NOT EXISTS matrix (
                    fetish_id   INTEGER,
                    question_id INTEGER,
                    yes_count   REAL NOT NULL,
                    total_count REAL NOT NULL,
                    PRIMARY KEY (fetish_id, question_id)
                )
            ''')
            cur.execute('SELECT COUNT(*) FROM fetishes')
            if cur.fetchone()[0] == 0:
                seed_fetishes = engine._load_json('fetishes.json')
                execute_values(
                    cur,
                    'INSERT INTO fetishes (id, name, "desc", works) VALUES %s',
                    [
                        (fetish['id'], fetish['name'], fetish['desc'],
                         json.dumps(fetish.get('works', []), ensure_ascii=False))
                        for fetish in seed_fetishes
                    ],
                )
            cur.execute('SELECT COUNT(*) FROM matrix')
            if cur.fetchone()[0] == 0:
                seed_fetishes = engine._load_json('fetishes.json')
                engine._seed_db(cur, seed_fetishes)
            cur.execute('''
                CREATE TABLE IF NOT EXISTS stats (
                    key   TEXT PRIMARY KEY,
                    value INTEGER NOT NULL DEFAULT 0
                )
            ''')
            for key in ('start_count', 'completion_count', 'learn_count', 'play_count'):
                cur.execute(
                    "INSERT INTO stats (key, value) VALUES (%s, 0) ON CONFLICT DO NOTHING", (key,)
                )
            cur.execute('''
                CREATE TABLE IF NOT EXISTS fetish_log (
                    fetish_id INTEGER PRIMARY KEY,
                    guessed   INTEGER NOT NULL DEFAULT 0,
                    correct   INTEGER NOT NULL DEFAULT 0,
                    wrong     INTEGER NOT NULL DEFAULT 0
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    data       TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS config (
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS stats_history (
                    date  TEXT NOT NULL,
                    key   TEXT NOT NULL,
                    value INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (date, key)
                )
            ''')
            cur.execute('SELECT id FROM fetishes')
            existing_ids = {row[0] for row in cur.fetchall()}
            seed = [fetish for fetish in engine._load_json('fetishes.json') if fetish['id'] < player_base_id]
            new_fetishes = [fetish for fetish in seed if fetish['id'] not in existing_ids]
            if new_fetishes:
                execute_values(
                    cur,
                    'INSERT INTO fetishes (id, name, "desc", works) VALUES %s ON CONFLICT DO NOTHING',
                    [
                        (fetish['id'], fetish['name'], fetish['desc'],
                         json.dumps(fetish.get('works', []), ensure_ascii=False))
                        for fetish in new_fetishes
                    ],
                )
                nq = len(engine.questions)
                full_yes, full_total = build_initial_matrix(len(seed), nq)
                seed_id_to_idx = {fetish['id']: idx for idx, fetish in enumerate(seed)}
                new_rows = [
                    (fetish['id'], question_idx,
                     full_yes[seed_id_to_idx[fetish['id']]][question_idx],
                     full_total[seed_id_to_idx[fetish['id']]][question_idx])
                    for fetish in new_fetishes for question_idx in range(nq)
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
                            new_question_rows.append((
                                fetish_id,
                                question_idx,
                                full_yes[seed_idx][question_idx],
                                full_total[seed_idx][question_idx],
                            ))
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


def update_fetish_fields(fetish_id, *, name=None, desc=None, works=None, get_conn, put_conn):
    conn = get_conn()
    try:
        with conn:
            cur = conn.cursor()
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


def merge_fetish_rows_db(id_keep, id_remove, *, new_name=None, new_desc=None, keep_name=None, keep_desc=None, get_conn, put_conn):
    conn = get_conn()
    try:
        with conn:
            cur = conn.cursor()
            cur.execute('''
                UPDATE matrix AS m
                SET yes_count   = m.yes_count   + rm.yes_count,
                    total_count = m.total_count + rm.total_count
                FROM matrix rm
                WHERE m.fetish_id = %s AND rm.fetish_id = %s
                  AND m.question_id = rm.question_id
            ''', (id_keep, id_remove))
            cur.execute('DELETE FROM fetishes WHERE id = %s', (id_remove,))
            cur.execute('DELETE FROM matrix WHERE fetish_id = %s', (id_remove,))
            cur.execute('''
                INSERT INTO fetish_log (fetish_id, guessed, correct, wrong)
                SELECT %s, guessed, correct, wrong FROM fetish_log WHERE fetish_id = %s
                ON CONFLICT (fetish_id) DO UPDATE
                SET guessed = fetish_log.guessed + EXCLUDED.guessed,
                    correct = fetish_log.correct + EXCLUDED.correct,
                    wrong   = fetish_log.wrong   + EXCLUDED.wrong
            ''', (id_keep, id_remove))
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
            for prefix in ('f_guessed_', 'f_correct_', 'f_wrong_'):
                old_key = f'{prefix}{old_id}'
                new_key = f'{prefix}{new_id}'
                cur.execute('''
                    INSERT INTO stats_history (date, key, value)
                    SELECT date, %s, value FROM stats_history WHERE key = %s
                    ON CONFLICT (date, key) DO UPDATE
                    SET value = stats_history.value + EXCLUDED.value
                ''', (new_key, old_key))
                cur.execute('DELETE FROM stats_history WHERE key = %s', (old_key,))
    finally:
        put_conn(conn)


def promoted_stats_history_repair_report(mappings, *, get_conn, put_conn):
    pairs = [(int(old_id), int(new_id)) for old_id, new_id in mappings if int(old_id) != int(new_id)]
    if not pairs:
        return {'mapping_count': 0, 'rows': [], 'total_value': 0}
    old_keys = [f'{prefix}{old_id}' for old_id, _new_id in pairs for prefix in ('f_guessed_', 'f_correct_', 'f_wrong_')]
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            'SELECT key, COUNT(*), COALESCE(SUM(value), 0) FROM stats_history WHERE key = ANY(%s) GROUP BY key',
            (old_keys,),
        )
        stats = {key: {'row_count': int(count or 0), 'value_sum': int(total or 0)} for key, count, total in cur.fetchall()}
        rows = []
        for old_id, new_id in pairs:
            for prefix in ('f_guessed_', 'f_correct_', 'f_wrong_'):
                old_key = f'{prefix}{old_id}'
                new_key = f'{prefix}{new_id}'
                entry = stats.get(old_key, {'row_count': 0, 'value_sum': 0})
                rows.append({
                    'old_id': old_id,
                    'new_id': new_id,
                    'old_key': old_key,
                    'new_key': new_key,
                    'row_count': entry['row_count'],
                    'value_sum': entry['value_sum'],
                })
        return {
            'mapping_count': len(pairs),
            'rows': rows,
            'total_value': sum(row['value_sum'] for row in rows),
        }
    finally:
        put_conn(conn)


def repair_promoted_stats_history(mappings, *, get_conn, put_conn):
    pairs = [(int(old_id), int(new_id)) for old_id, new_id in mappings if int(old_id) != int(new_id)]
    report = promoted_stats_history_repair_report(pairs, get_conn=get_conn, put_conn=put_conn)
    if not pairs:
        return {**report, 'applied': False}
    conn = get_conn()
    try:
        with conn:
            cur = conn.cursor()
            token = str(int(time.time() * 1000000))
            temp_entries = []
            for old_id, new_id in pairs:
                for prefix in ('f_guessed_', 'f_correct_', 'f_wrong_'):
                    old_key = f'{prefix}{old_id}'
                    temp_key = f'__repair_{token}_{old_key}'
                    new_key = f'{prefix}{new_id}'
                    temp_entries.append((temp_key, new_key))
                    cur.execute('''
                        INSERT INTO stats_history (date, key, value)
                        SELECT date, %s, value FROM stats_history WHERE key = %s
                        ON CONFLICT (date, key) DO UPDATE
                        SET value = stats_history.value + EXCLUDED.value
                    ''', (temp_key, old_key))
                    cur.execute('DELETE FROM stats_history WHERE key = %s', (old_key,))
            for temp_key, new_key in temp_entries:
                cur.execute('''
                    INSERT INTO stats_history (date, key, value)
                    SELECT date, %s, value FROM stats_history WHERE key = %s
                    ON CONFLICT (date, key) DO UPDATE
                    SET value = stats_history.value + EXCLUDED.value
                ''', (new_key, temp_key))
                cur.execute('DELETE FROM stats_history WHERE key = %s', (temp_key,))
    finally:
        put_conn(conn)
    return {**report, 'applied': True}


def increment_stat(key, *, get_conn, put_conn):
    conn = get_conn()
    try:
        with conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO stats (key, value) VALUES (%s, 1) ON CONFLICT (key) DO UPDATE SET value = stats.value + 1",
                (key,),
            )
    finally:
        put_conn(conn)


def record_daily_stat(key, today, *, get_conn, put_conn):
    conn = get_conn()
    try:
        with conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO stats_history (date, key, value) VALUES (%s, %s, 1) "
                "ON CONFLICT (date, key) DO UPDATE SET value = stats_history.value + 1",
                (today, key),
            )
    finally:
        put_conn(conn)


def load_stats(keys, *, get_conn, put_conn):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT key, value FROM stats WHERE key = ANY(%s)", (list(keys),))
        result = dict(cur.fetchall())
        return {key: result.get(key, 0) for key in keys}
    finally:
        put_conn(conn)


def load_stats_history(date_range, *, get_conn, put_conn):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT date, key, value FROM stats_history WHERE date >= %s", (date_range[0],))
        raw = {}
        for day, key, value in cur.fetchall():
            raw.setdefault(day, {})[key] = value
        return [
            {
                'date': day,
                'start': raw.get(day, {}).get('start', 0),
                'play': raw.get(day, {}).get('play', 0),
                'completion': raw.get(day, {}).get('completion', 0),
                'learn': raw.get(day, {}).get('learn', 0),
                'correct': raw.get(day, {}).get('correct', 0),
                'wrong': raw.get(day, {}).get('wrong', 0),
                'dropoff': raw.get(day, {}).get('dropoff', 0),
            }
            for day in date_range
        ]
    finally:
        put_conn(conn)



def load_dropoff_totals(since, *, get_conn, put_conn):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT key, SUM(value) FROM stats_history WHERE date >= %s AND (key = 'dropoff' OR key LIKE 'dropoff_q_%%') GROUP BY key",
            (since,),
        )
        total = 0
        by_answered = {}
        for key, value in cur.fetchall():
            value = int(value or 0)
            if key == 'dropoff':
                total += value
            elif key.startswith('dropoff_q_'):
                try:
                    answered_count = int(key[len('dropoff_q_'):])
                except ValueError:
                    continue
                by_answered[answered_count] = by_answered.get(answered_count, 0) + value
        return {'total': total, 'by_answered': by_answered}
    finally:
        put_conn(conn)

def load_feedback_totals(since, *, get_conn, put_conn):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT key, SUM(value) FROM stats_history WHERE date >= %s AND (key LIKE 'f_guessed_%%' OR key LIKE 'f_correct_%%' OR key LIKE 'f_wrong_%%') GROUP BY key",
            (since,),
        )
        totals = {}
        for key, value in cur.fetchall():
            if key.startswith('f_guessed_'):
                fetish_id = int(key[len('f_guessed_'):])
                totals.setdefault(fetish_id, {'guessed': 0, 'correct': 0, 'wrong': 0})['guessed'] += int(value or 0)
            elif key.startswith('f_correct_'):
                fetish_id = int(key[len('f_correct_'):])
                totals.setdefault(fetish_id, {'guessed': 0, 'correct': 0, 'wrong': 0})['correct'] += int(value or 0)
            elif key.startswith('f_wrong_'):
                fetish_id = int(key[len('f_wrong_'):])
                totals.setdefault(fetish_id, {'guessed': 0, 'correct': 0, 'wrong': 0})['wrong'] += int(value or 0)
        return totals
    finally:
        put_conn(conn)


def load_fetish_history(date_range, correct_key, wrong_key, *, get_conn, put_conn):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT date, key, value FROM stats_history WHERE date >= %s AND key IN (%s, %s)",
            (date_range[0], correct_key, wrong_key),
        )
        raw = {}
        for day, key, value in cur.fetchall():
            raw.setdefault(day, {})[key] = value
        return raw
    finally:
        put_conn(conn)


def load_quality_event_totals(date_range, keys, *, get_conn, put_conn):
    totals = {key: 0 for key in keys}
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT key, SUM(value) FROM stats_history WHERE date >= %s AND key = ANY(%s) GROUP BY key",
            (date_range[0], list(keys)),
        )
        for key, value in cur.fetchall():
            totals[key] = int(value or 0)
        return totals
    finally:
        put_conn(conn)


def load_disabled_questions(*, get_conn, put_conn):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT key FROM stats WHERE key LIKE 'disabled_q_%'")
        return {int(row[0][len('disabled_q_'):]) for row in cur.fetchall()}
    finally:
        put_conn(conn)


def save_disabled_questions(disabled_questions, *, get_conn, put_conn):
    conn = get_conn()
    try:
        with conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM stats WHERE key LIKE 'disabled_q_%'")
            for question_id in disabled_questions:
                cur.execute(
                    "INSERT INTO stats (key, value) VALUES (%s, 1) ON CONFLICT (key) DO UPDATE SET value=1",
                    (f'disabled_q_{question_id}',),
                )
    finally:
        put_conn(conn)


def increment_fetish_log(fetish_db_id, column, *, get_conn, put_conn):
    if column not in ('guessed', 'correct', 'wrong'):
        raise ValueError(f'不正な列名: {column}')
    conn = get_conn()
    try:
        with conn:
            cur = conn.cursor()
            cur.execute(f'''
                INSERT INTO fetish_log (fetish_id, {column}) VALUES (%s, 1)
                ON CONFLICT (fetish_id) DO UPDATE SET {column} = fetish_log.{column} + 1
            ''', (fetish_db_id,))
    finally:
        put_conn(conn)


def load_fetish_log(*, get_conn, put_conn):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute('SELECT fetish_id, guessed, correct, wrong FROM fetish_log')
        return {
            row[0]: {'guessed': row[1], 'correct': row[2], 'wrong': row[3]}
            for row in cur.fetchall()
        }
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
