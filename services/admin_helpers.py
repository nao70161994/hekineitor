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



def most_similar_fetishes(engine, fetish_ids, limit=1):
    """Return nearest matrix neighbors for a small set of fetish ids."""
    import math
    question_count = len(engine.questions)
    vectors = []
    for idx, fetish in enumerate(engine.fetishes):
        vector = [engine._prob(idx, question_id) - 0.5 for question_id in range(question_count)]
        norm = math.sqrt(sum(value * value for value in vector))
        vectors.append((fetish['id'], fetish['name'], vector, norm))

    result = {}
    for fetish_id in fetish_ids:
        idx = engine.index_of(fetish_id)
        if idx is None or idx >= len(vectors):
            result[fetish_id] = []
            continue
        _, _, base_vector, base_norm = vectors[idx]
        matches = []
        for other_id, other_name, other_vector, other_norm in vectors:
            if other_id == fetish_id:
                continue
            if base_norm < 1e-9 or other_norm < 1e-9:
                cosine = 0.0
            else:
                cosine = sum(a * b for a, b in zip(base_vector, other_vector)) / (base_norm * other_norm)
            matches.append({
                'fetish_id': other_id,
                'fetish_name': other_name,
                'cosine': round(cosine, 3),
            })
        matches.sort(key=lambda row: -abs(row['cosine']))
        result[fetish_id] = matches[:limit]
    return result


def build_admin_maintenance_checklist(engine, works_summary_fn):
    report = engine.get_quality_report()
    questions_by_id = {question['id']: question for question in engine.get_question_stats()}
    weak_ids = [int(row['fetish_id']) for row in report.get('weak_fetishes', [])]
    nearest = most_similar_fetishes(engine, weak_ids, limit=1) if weak_ids else {}

    weak_fetishes = []
    for row in report.get('weak_fetishes', []):
        fetish_id = int(row['fetish_id'])
        weak_fetishes.append({
            **row,
            'nearest_similar': (nearest.get(fetish_id) or [None])[0],
            'edit_anchor': '#seed-edit-section',
            'similarity_anchor': '#similarity-section',
            'hint': '説明・作品・特徴質問を見直し、近い性癖との判別差を確認',
        })

    duplicate_questions = []
    for pair in report.get('high_correlation_questions', []):
        q1 = questions_by_id.get(pair['q1_id'], {})
        q2 = questions_by_id.get(pair['q2_id'], {})
        weaker = q1 if q1.get('disc', 0) <= q2.get('disc', 0) else q2
        duplicate_questions.append({
            **pair,
            'suggested_action': f"Q{weaker.get('id')} の無効化または文言差し替えを検討",
            'weaker_question_id': weaker.get('id'),
        })

    low_questions = [{
        **question,
        'suggested_action': '文言を具体化するか、類似質問と統合/無効化を検討',
    } for question in report.get('low_questions', [])]

    works = works_summary_fn()
    checklist = [
        {
            'id': 'weak_fetishes',
            'label': '改善候補の性癖',
            'count': len(weak_fetishes),
            'severity': 'warn' if weak_fetishes else 'ok',
            'next_action': '編集欄で説明・作品を補強し、類似度チェックで近い性癖との差分を見る',
        },
        {
            'id': 'duplicate_questions',
            'label': '重複度が高い質問',
            'count': len(duplicate_questions),
            'severity': 'warn' if duplicate_questions else 'ok',
            'next_action': '弱い方の質問を無効化、または別軸の文言に差し替える',
        },
        {
            'id': 'low_questions',
            'label': '低識別力の質問',
            'count': len(low_questions),
            'severity': 'warn' if low_questions else 'ok',
            'next_action': '質問一覧で識別力と使用量を確認して編集する',
        },
        {
            'id': 'works',
            'label': '作品データの不足',
            'count': works['missing_work_fetish_count'] + works['missing_url_work_count'] + works['unsafe_url_work_count'],
            'severity': 'warn' if (
                works['missing_work_fetish_count'] or works['missing_url_work_count'] or works['unsafe_url_work_count']
            ) else 'ok',
            'next_action': '作品リンク確認からURLなし・不正URL・作品なしの性癖を補修する',
        },
    ]
    return {
        'checklist': checklist,
        'weak_fetishes': weak_fetishes,
        'duplicate_questions': duplicate_questions,
        'low_questions': low_questions,
        'works': works,
    }


def build_work_maintenance_summary(engine, work_title_fn, safe_work_url_fn, sample_limit=8):
    from services import works_links

    return works_links.build_work_maintenance_summary(
        engine.fetishes,
        work_title_fn=work_title_fn,
        safe_work_url_fn=safe_work_url_fn,
        sample_limit=sample_limit,
    )


def make_admin_maintenance_checklist(engine, work_title_fn, safe_work_url_fn):
    def checklist():
        return build_admin_maintenance_checklist(
            engine,
            lambda: build_work_maintenance_summary(engine, work_title_fn, safe_work_url_fn),
        )
    return checklist
