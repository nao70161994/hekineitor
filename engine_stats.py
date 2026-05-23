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
            'play': raw.get(day, {}).get('play', 0),
            'learn': raw.get(day, {}).get('learn', 0),
            'correct': raw.get(day, {}).get('correct', 0),
            'wrong': raw.get(day, {}).get('wrong', 0),
        }
        for day in date_range
    ]


def load_disabled_questions_file(path):
    return set(read_json_path(path, {}).get('disabled', []))


def save_disabled_questions_file(path, disabled_questions, *, atomic_write):
    atomic_write(path, {'disabled': sorted(disabled_questions)})


def increment_fetish_log_file(path, fetish_db_id, column, *, lock, atomic_write):
    with lock:
        data = read_json_path(path, {})
        key = str(fetish_db_id)
        entry = data.get(key, {'guessed': 0, 'correct': 0, 'wrong': 0})
        entry[column] = entry.get(column, 0) + 1
        data[key] = entry
        atomic_write(path, data)


def load_fetish_log_file(path):
    raw = read_json_path(path, {})
    return {int(key): value for key, value in raw.items()}
