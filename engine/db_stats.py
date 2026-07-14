"""Statistics, history, question-state, and fetish-log database helpers."""

import time


def _move_promoted_stats_history(cur, old_id, new_id):
    for prefix in ('f_guessed_', 'f_correct_', 'f_wrong_'):
        old_key = f'{prefix}{old_id}'
        new_key = f'{prefix}{new_id}'
        cur.execute(
            """
            INSERT INTO stats_history (date, key, value)
            SELECT date, %s, value FROM stats_history WHERE key = %s
            ON CONFLICT (date, key) DO UPDATE
            SET value = stats_history.value + EXCLUDED.value
        """,
            (new_key, old_key),
        )
        cur.execute('DELETE FROM stats_history WHERE key = %s', (old_key,))


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
        stats = {
            key: {'row_count': int(count or 0), 'value_sum': int(total or 0)} for key, count, total in cur.fetchall()
        }
        rows = []
        for old_id, new_id in pairs:
            for prefix in ('f_guessed_', 'f_correct_', 'f_wrong_'):
                old_key = f'{prefix}{old_id}'
                new_key = f'{prefix}{new_id}'
                entry = stats.get(old_key, {'row_count': 0, 'value_sum': 0})
                rows.append(
                    {
                        'old_id': old_id,
                        'new_id': new_id,
                        'old_key': old_key,
                        'new_key': new_key,
                        'row_count': entry['row_count'],
                        'value_sum': entry['value_sum'],
                    }
                )
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
                    cur.execute(
                        """
                        INSERT INTO stats_history (date, key, value)
                        SELECT date, %s, value FROM stats_history WHERE key = %s
                        ON CONFLICT (date, key) DO UPDATE
                        SET value = stats_history.value + EXCLUDED.value
                    """,
                        (temp_key, old_key),
                    )
                    cur.execute('DELETE FROM stats_history WHERE key = %s', (old_key,))
            for temp_key, new_key in temp_entries:
                cur.execute(
                    """
                    INSERT INTO stats_history (date, key, value)
                    SELECT date, %s, value FROM stats_history WHERE key = %s
                    ON CONFLICT (date, key) DO UPDATE
                    SET value = stats_history.value + EXCLUDED.value
                """,
                    (new_key, temp_key),
                )
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
                'INSERT INTO stats (key, value) VALUES (%s, 1) ON CONFLICT (key) DO UPDATE SET value = stats.value + 1',
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
                'INSERT INTO stats_history (date, key, value) VALUES (%s, %s, 1) '
                'ON CONFLICT (date, key) DO UPDATE SET value = stats_history.value + 1',
                (today, key),
            )
    finally:
        put_conn(conn)


def load_stats(keys, *, get_conn, put_conn):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute('SELECT key, value FROM stats WHERE key = ANY(%s)', (list(keys),))
        result = dict(cur.fetchall())
        return {key: result.get(key, 0) for key in keys}
    finally:
        put_conn(conn)


def load_stats_history(date_range, *, get_conn, put_conn):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute('SELECT date, key, value FROM stats_history WHERE date >= %s', (date_range[0],))
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
                    answered_count = int(key[len('dropoff_q_') :])
                except ValueError:
                    continue
                by_answered[answered_count] = by_answered.get(answered_count, 0) + value
        return {'total': total, 'by_answered': by_answered}
    finally:
        put_conn(conn)


def load_feedback_totals(since, until=None, *, get_conn, put_conn):
    conn = get_conn()
    try:
        cur = conn.cursor()
        if until:
            cur.execute(
                "SELECT key, SUM(value) FROM stats_history WHERE date >= %s AND date <= %s AND (key LIKE 'f_guessed_%%' OR key LIKE 'f_correct_%%' OR key LIKE 'f_wrong_%%') GROUP BY key",
                (since, until),
            )
        else:
            cur.execute(
                "SELECT key, SUM(value) FROM stats_history WHERE date >= %s AND (key LIKE 'f_guessed_%%' OR key LIKE 'f_correct_%%' OR key LIKE 'f_wrong_%%') GROUP BY key",
                (since,),
            )
        totals = {}
        for key, value in cur.fetchall():
            if key.startswith('f_guessed_'):
                fetish_id = int(key[len('f_guessed_') :])
                totals.setdefault(fetish_id, {'guessed': 0, 'correct': 0, 'wrong': 0})['guessed'] += int(value or 0)
            elif key.startswith('f_correct_'):
                fetish_id = int(key[len('f_correct_') :])
                totals.setdefault(fetish_id, {'guessed': 0, 'correct': 0, 'wrong': 0})['correct'] += int(value or 0)
            elif key.startswith('f_wrong_'):
                fetish_id = int(key[len('f_wrong_') :])
                totals.setdefault(fetish_id, {'guessed': 0, 'correct': 0, 'wrong': 0})['wrong'] += int(value or 0)
        return totals
    finally:
        put_conn(conn)


def load_fetish_history(date_range, correct_key, wrong_key, *, get_conn, put_conn):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            'SELECT date, key, value FROM stats_history WHERE date >= %s AND key IN (%s, %s)',
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
            'SELECT key, SUM(value) FROM stats_history WHERE date >= %s AND key = ANY(%s) GROUP BY key',
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
        return {int(row[0][len('disabled_q_') :]) for row in cur.fetchall()}
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
                    'INSERT INTO stats (key, value) VALUES (%s, 1) ON CONFLICT (key) DO UPDATE SET value=1',
                    (f'disabled_q_{question_id}',),
                )
    finally:
        put_conn(conn)


def toggle_question_disabled(question_id, *, get_conn, put_conn):
    key = f'disabled_q_{int(question_id)}'
    conn = get_conn()
    try:
        with conn:
            cur = conn.cursor()
            cur.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', (key,))
            cur.execute('DELETE FROM stats WHERE key = %s RETURNING key', (key,))
            if cur.fetchone():
                return False
            cur.execute(
                'INSERT INTO stats (key, value) VALUES (%s, 1) ON CONFLICT (key) DO UPDATE SET value=1',
                (key,),
            )
            return True
    finally:
        put_conn(conn)


def increment_fetish_log(fetish_db_id, column, *, get_conn, put_conn):
    if column not in ('guessed', 'correct', 'wrong'):
        raise ValueError(f'不正な列名: {column}')
    conn = get_conn()
    try:
        with conn:
            cur = conn.cursor()
            cur.execute(
                f"""
                INSERT INTO fetish_log (fetish_id, {column}) VALUES (%s, 1)
                ON CONFLICT (fetish_id) DO UPDATE SET {column} = fetish_log.{column} + 1
            """,
                (fetish_db_id,),
            )
    finally:
        put_conn(conn)


def load_fetish_log(*, get_conn, put_conn):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute('SELECT fetish_id, guessed, correct, wrong FROM fetish_log')
        return {row[0]: {'guessed': row[1], 'correct': row[2], 'wrong': row[3]} for row in cur.fetchall()}
    finally:
        put_conn(conn)
