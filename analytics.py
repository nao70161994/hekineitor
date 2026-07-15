def _as_int(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _pct(part, total):
    return round(part / total * 100, 1) if total else None


def _feedback_totals(log):
    totals = {'guessed': 0, 'correct': 0, 'wrong': 0}
    for entry in log.values():
        totals['guessed'] += _as_int(entry.get('guessed'))
        totals['correct'] += _as_int(entry.get('correct'))
        totals['wrong'] += _as_int(entry.get('wrong'))
    feedback = totals['correct'] + totals['wrong']
    no_feedback = max(totals['guessed'] - feedback, 0)
    return {
        **totals,
        'feedback_total': feedback,
        'accuracy': _pct(totals['correct'], feedback),
        'wrong_rate': _pct(totals['wrong'], feedback),
        'no_feedback_guesses': no_feedback,
        'no_feedback_rate': _pct(no_feedback, totals['guessed']),
    }


def _history_summary(engine, days):
    rows = engine.get_stats_history(days=days)
    play = sum(_as_int(r.get('play')) for r in rows)
    learn = sum(_as_int(r.get('learn')) for r in rows)
    correct = sum(_as_int(r.get('correct')) for r in rows)
    wrong = sum(_as_int(r.get('wrong')) for r in rows)
    feedback = correct + wrong
    return {
        'days': days,
        'play': play,
        'learn': learn,
        'correct': correct,
        'wrong': wrong,
        'feedback_total': feedback,
        'accuracy': _pct(correct, feedback),
        'wrong_rate': _pct(wrong, feedback),
    }


def _quality_event_summary(engine, days=30):
    if not hasattr(engine, 'get_quality_event_summary'):
        return {'days': days, 'tracked': False}
    raw = engine.get_quality_event_summary(days=days)
    low = raw.get('low_confidence', {})
    add = raw.get('additional_questions', {})
    low_feedback = _as_int(low.get('correct')) + _as_int(low.get('wrong'))
    add_feedback = _as_int(add.get('correct')) + _as_int(add.get('wrong'))
    low_guesses = _as_int(low.get('guesses'))
    add_guesses = _as_int(add.get('guesses'))
    return {
        'days': raw.get('days', days),
        'tracked': bool(low_guesses or add_guesses or low_feedback or add_feedback),
        'low_confidence_guesses': low_guesses,
        'low_confidence_feedback_total': low_feedback,
        'low_confidence_correct': _as_int(low.get('correct')),
        'low_confidence_wrong': _as_int(low.get('wrong')),
        'low_confidence_accuracy': _pct(_as_int(low.get('correct')), low_feedback),
        'low_confidence_wrong_rate': _pct(_as_int(low.get('wrong')), low_feedback),
        'low_confidence_no_feedback': max(low_guesses - low_feedback, 0),
        'additional_question_guesses': add_guesses,
        'additional_question_feedback_total': add_feedback,
        'additional_question_correct': _as_int(add.get('correct')),
        'additional_question_wrong': _as_int(add.get('wrong')),
        'additional_question_accuracy': _pct(_as_int(add.get('correct')), add_feedback),
        'additional_question_wrong_rate': _pct(_as_int(add.get('wrong')), add_feedback),
        'additional_questions_asked': _as_int(add.get('questions')),
        'avg_additional_questions': round(_as_int(add.get('questions')) / add_guesses, 2) if add_guesses else None,
    }


def build_quality_report(engine):
    """Build admin-facing diagnosis quality indicators from an Engine instance."""
    q_stats = engine.get_question_stats()
    low_questions = [q for q in q_stats if not q['disabled'] and q['disc'] < 0.06][:10]
    high_corr = [p for p in engine.get_correlation_stats(top_n=50) if abs(p['cos']) >= 0.92][:10]

    log = engine.get_fetish_log()
    id_to_f = {f['id']: f for f in engine.fetishes}
    weak_fetishes = []
    no_feedback_fetishes = []
    for fid, entry in log.items():
        guessed = _as_int(entry.get('guessed'))
        correct = _as_int(entry.get('correct'))
        wrong = _as_int(entry.get('wrong'))
        feedback = correct + wrong
        no_feedback = max(guessed - feedback, 0)
        if guessed >= 5 and no_feedback >= 3:
            no_feedback_fetishes.append(
                {
                    'fetish_id': fid,
                    'fetish_name': id_to_f.get(fid, {}).get('name', f'ID {fid}'),
                    'guessed': guessed,
                    'feedback_total': feedback,
                    'no_feedback_guesses': no_feedback,
                    'no_feedback_rate': _pct(no_feedback, guessed),
                }
            )
        if guessed < 3 and feedback < 3:
            continue
        acc = _pct(correct, guessed)
        wrong_rate = _pct(wrong, feedback) or 0
        if wrong_rate >= 35 or (acc is not None and acc < 45):
            weak_fetishes.append(
                {
                    'fetish_id': fid,
                    'fetish_name': id_to_f.get(fid, {}).get('name', f'ID {fid}'),
                    'guessed': guessed,
                    'correct': correct,
                    'wrong': wrong,
                    'accuracy': acc,
                    'wrong_rate': wrong_rate,
                }
            )
    weak_fetishes.sort(key=lambda r: (-r['wrong_rate'], r['accuracy'] if r['accuracy'] is not None else 999))
    no_feedback_fetishes.sort(key=lambda r: (-r['no_feedback_guesses'], -(r['no_feedback_rate'] or 0)))

    feedback_summary = _feedback_totals(log)
    feedback_summary['recent_7_days'] = _history_summary(engine, 7)
    feedback_summary['recent_30_days'] = _history_summary(engine, 30)
    low_conf_summary = _quality_event_summary(engine, 30)

    action_items = []
    if feedback_summary['feedback_total'] < 20:
        action_items.append(
            {
                'type': 'feedback_volume',
                'severity': 'info',
                'message': 'フィードバック件数が少ないため、品質判断は暫定です。',
            }
        )
    if feedback_summary['wrong_rate'] is not None and feedback_summary['wrong_rate'] >= 35:
        action_items.append(
            {
                'type': 'overall_wrong_rate',
                'severity': 'warning',
                'message': '全体の外れ率が高めです。改善候補の性癖と重複質問を優先確認してください。',
            }
        )
    if low_conf_summary.get('low_confidence_feedback_total', 0) >= 5:
        low_acc = low_conf_summary.get('low_confidence_accuracy')
        if low_acc is not None and low_acc < (feedback_summary.get('accuracy') or 0):
            action_items.append(
                {
                    'type': 'low_confidence_extension',
                    'severity': 'warning',
                    'message': '低信頼時の追加質問後も正解率が全体より低いです。終盤質問と閾値を見直してください。',
                }
            )

    return {
        'low_questions': low_questions,
        'high_correlation_questions': high_corr,
        'weak_fetishes': weak_fetishes[:10],
        'feedback_summary': feedback_summary,
        'confusion_summary': {
            'weak_fetishes': weak_fetishes[:10],
            'no_feedback_fetishes': no_feedback_fetishes[:10],
        },
        'low_confidence_summary': low_conf_summary,
        'action_items': action_items,
    }
