import json


def read_json_path(path, default):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def increment_counter_file(path, key, *, lock, atomic_write):
    with lock:
        data = read_json_path(path, {})
        data[key] = data.get(key, 0) + 1
        atomic_write(path, data)


def record_daily_counter_file(path, key, today, *, lock, atomic_write):
    with lock:
        data = read_json_path(path, {})
        day = data.setdefault(today, {})
        day[key] = day.get(key, 0) + 1
        atomic_write(path, data)


def counters_from_file(path, keys):
    data = read_json_path(path, {})
    return {key: data.get(key, 0) for key in keys}


def history_rows_from_file(path, date_range):
    raw = read_json_path(path, {})
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


def load_disabled_questions_file(path):
    return set(read_json_path(path, {}).get('disabled', []))


def save_disabled_questions_file(path, disabled_questions, *, atomic_write):
    atomic_write(path, {'disabled': sorted(disabled_questions)})


FETISH_LOG_FIELDS = (
    'guessed',
    'correct',
    'wrong',
    'correction_selected',
    'exposure_guessed',
    'exposure_correct',
)


def empty_fetish_log_entry():
    return {field: 0 for field in FETISH_LOG_FIELDS}


def increment_fetish_log_counters_file(path, fetish_db_id, increments, *, lock, atomic_write):
    invalid = set(increments) - set(FETISH_LOG_FIELDS)
    if invalid:
        raise ValueError(f'不正な列名: {sorted(invalid)[0]}')
    with lock:
        data = read_json_path(path, {})
        key = str(fetish_db_id)
        entry = {**empty_fetish_log_entry(), **data.get(key, {})}
        for column, amount in increments.items():
            entry[column] = entry.get(column, 0) + int(amount)
        data[key] = entry
        atomic_write(path, data)


def increment_fetish_log_file(path, fetish_db_id, column, *, lock, atomic_write):
    increment_fetish_log_counters_file(
        path,
        fetish_db_id,
        {column: 1},
        lock=lock,
        atomic_write=atomic_write,
    )


def load_fetish_log_file(path):
    raw = read_json_path(path, {})
    return {int(key): {**empty_fetish_log_entry(), **value} for key, value in raw.items()}
