def bounded_int(value, default, min_value=1, max_value=100):
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(min_value, min(max_value, number))


def build_fetish_log_rows(engine):
    fetish_log = engine.get_fetish_log()
    rows = []
    for fetish in engine.fetishes:
        log = fetish_log.get(fetish['id'], {'guessed': 0, 'correct': 0, 'wrong': 0})
        guessed = log['guessed']
        correct = log['correct']
        wrong = log['wrong']
        accuracy = round(correct / guessed * 100) if guessed else None
        rows.append({
            'id': fetish['id'],
            'name': fetish['name'],
            'guessed': guessed,
            'correct': correct,
            'wrong': wrong,
            'acc': accuracy,
        })
    rows.sort(key=lambda row: -row['guessed'])
    return rows


def paged_fetish_log_rows(rows, args):
    query = (args.get('q') or '').strip().lower()
    min_guessed = bounded_int(args.get('min_guessed'), 0, 0, 1000000)
    acc_filter = args.get('acc_filter') or 'all'
    sort_key = args.get('sort') or 'guessed'
    order = args.get('order') or 'desc'
    page = bounded_int(args.get('page'), 1, 1, 1000000)
    per_page = bounded_int(args.get('per_page'), 50, 10, 200)

    def include(row):
        accuracy = row['acc']
        return (
            query in row['name'].lower()
            and row['guessed'] >= min_guessed
            and (
                acc_filter == 'all'
                or (acc_filter == 'low' and accuracy is not None and accuracy < 50)
                or (acc_filter == 'high' and accuracy is not None and accuracy >= 70)
                or (acc_filter == 'none' and accuracy is None)
            )
        )

    filtered = [row for row in rows if include(row)]
    key_map = {
        'name': lambda row: row['name'],
        'guessed': lambda row: row['guessed'],
        'correct': lambda row: row['correct'],
        'wrong': lambda row: row['wrong'],
        'acc': lambda row: -1 if row['acc'] is None else row['acc'],
    }
    filtered.sort(key=key_map.get(sort_key, key_map['guessed']), reverse=(order != 'asc'))
    total = len(filtered)
    start = (page - 1) * per_page
    return {
        'rows': filtered[start:start + per_page],
        'page': page,
        'per_page': per_page,
        'total': total,
        'pages': max(1, (total + per_page - 1) // per_page),
    }
