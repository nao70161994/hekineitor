def fetish_feedback_totals_from_history(raw, date_range):
    totals = {}
    for day in date_range:
        for key, value in raw.get(day, {}).items():
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


def recent_fetish_ranking_from_history(raw, date_range, id_to_name, top_n):
    return format_recent_fetish_ranking(
        fetish_feedback_totals_from_history(raw, date_range),
        id_to_name,
        top_n,
    )


def format_recent_fetish_ranking(totals, id_to_name, top_n, source='recent'):
    results = []
    for fetish_id, counts in totals.items():
        guessed = int(counts.get('guessed', 0) or 0)
        correct = int(counts.get('correct', 0) or 0)
        wrong = int(counts.get('wrong', 0) or 0)
        feedback_total = correct + wrong
        total = guessed if guessed > 0 else feedback_total
        if total == 0:
            continue
        results.append({
            'fetish_id': fetish_id,
            'fetish_name': id_to_name.get(fetish_id, f'ID {fetish_id}'),
            'guessed': guessed,
            'correct': correct,
            'wrong': wrong,
            'feedback_total': feedback_total,
            'total': total,
            'acc': round(correct / feedback_total * 100) if feedback_total > 0 else None,
            'source': source,
        })
    results.sort(key=lambda item: (item['total'], item['feedback_total']), reverse=True)
    return results[:top_n]


def fetish_history_rows(raw, date_range, correct_key, wrong_key):
    return [
        {
            'date': day,
            'correct': raw.get(day, {}).get(correct_key, 0),
            'wrong': raw.get(day, {}).get(wrong_key, 0),
        }
        for day in date_range
    ]


def quality_event_summary_from_history(raw, date_range, keys, days):
    totals = {key: 0 for key in keys}
    for day in date_range:
        day_data = raw.get(day, {})
        for key in keys:
            totals[key] += int(day_data.get(key, 0) or 0)
    return quality_event_summary_from_totals(totals, days)


def quality_event_summary_from_totals(totals, days):
    return {
        'days': days,
        'low_confidence': {
            'guesses': totals['q_low_conf_guess'],
            'correct': totals['q_low_conf_correct'],
            'wrong': totals['q_low_conf_wrong'],
        },
        'additional_questions': {
            'guesses': totals['q_additional_guess'],
            'correct': totals['q_additional_correct'],
            'wrong': totals['q_additional_wrong'],
            'questions': totals['q_additional_question'],
        },
    }
