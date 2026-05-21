def record_quality_stat(engine, key, count=1):
    for _ in range(max(0, int(count or 0))):
        engine._record_daily_stat(key)


def record_guess_quality_feedback(engine, session, correct):
    quality = session.pop('last_guess_quality', None) or {}
    if not quality:
        return
    suffix = 'correct' if correct else 'wrong'
    if quality.get('low_confidence_extended'):
        record_quality_stat(engine, f'q_low_conf_{suffix}')
    if quality.get('additional_questions', 0) > 0:
        record_quality_stat(engine, f'q_additional_{suffix}')


def mark_guess_quality(engine, session, answers, soft_max_questions):
    additional_questions = max(0, len(answers or {}) - soft_max_questions)
    low_confidence_extended = bool(session.get('low_confidence_extended'))
    session['last_guess_quality'] = {
        'low_confidence_extended': low_confidence_extended,
        'additional_questions': additional_questions,
    }
    if low_confidence_extended:
        record_quality_stat(engine, 'q_low_conf_guess')
    if additional_questions > 0:
        record_quality_stat(engine, 'q_additional_guess')
        record_quality_stat(engine, 'q_additional_question', additional_questions)
