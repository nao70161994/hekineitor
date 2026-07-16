def best_question(engine, answers, asked, *, idk_streak=0):
    return engine.best_question(answers, asked, idk_streak=idk_streak)


def best_disambiguating_question(engine, answers, asked, *, candidate_count=3, idk_streak=0):
    return engine.best_disambiguating_question(
        answers,
        asked,
        candidate_count=candidate_count,
        idk_streak=idk_streak,
    )


HEAVY_RESULT_NAMES = {'共依存', '激重感情', '共生関係', '執着'}
LOW_EXPOSURE_DIVERSIFYING_CATEGORIES = {'attribute', 'world', 'aesthetic', 'value', 'role'}


def _ranked_result_names(engine, answers, limit=4):
    probs = engine.posteriors(answers)
    ranked = sorted(range(len(probs)), key=lambda index: probs[index], reverse=True)[:limit]
    return [engine.fetishes[index].get('name', '') for index in ranked]


def should_probe_low_exposure_axis(engine, answers, asked, *, count, top_p, second_p, hard_max_questions):
    if count < 4 or count >= hard_max_questions:
        return False
    ranked_names = _ranked_result_names(engine, answers, limit=5)
    heavy_count = sum(name in HEAVY_RESULT_NAMES for name in ranked_names)
    if heavy_count < 2 and not (ranked_names and ranked_names[0] in HEAVY_RESULT_NAMES and top_p >= 0.45):
        return False
    asked_categories = [engine._question_category(q) for q in asked]
    diversifying_count = sum(category in LOW_EXPOSURE_DIVERSIFYING_CATEGORIES for category in asked_categories)
    if diversifying_count >= 3 and (top_p - second_p) >= 0.25:
        return False
    return True


def best_low_exposure_axis_question(engine, answers, asked, *, preferred_categories=None):
    preferred_categories = preferred_categories or LOW_EXPOSURE_DIVERSIFYING_CATEGORIES
    probs = engine.posteriors(answers)
    h0 = engine._entropy(probs)
    best_q, best_score = None, -1.0
    recent_categories = [engine._question_category(q) for q in list(asked)[-3:]]
    for question_id in range(len(engine.questions)):
        if question_id in asked or question_id in engine.disabled_questions:
            continue
        category = engine._question_category(question_id)
        if category not in preferred_categories:
            continue
        p_yes = sum(
            probs[fetish_idx] * engine._prob(fetish_idx, question_id) for fetish_idx in range(len(engine.fetishes))
        )
        p_no = 1.0 - p_yes
        if p_yes < 0.05 or p_no < 0.05:
            continue
        yes_probs = [
            probs[fetish_idx] * engine._prob(fetish_idx, question_id) for fetish_idx in range(len(engine.fetishes))
        ]
        yes_total = sum(yes_probs) or 1e-9
        yes_probs = [value / yes_total for value in yes_probs]
        no_probs = [
            probs[fetish_idx] * (1 - engine._prob(fetish_idx, question_id))
            for fetish_idx in range(len(engine.fetishes))
        ]
        no_total = sum(no_probs) or 1e-9
        no_probs = [value / no_total for value in no_probs]
        score = h0 - (p_yes * engine._entropy(yes_probs) + p_no * engine._entropy(no_probs))
        if category in recent_categories:
            score *= 0.75
        if score > best_score:
            best_q, best_score = question_id, score
    return best_q


def question_total_for_count(count, soft_max_questions, hard_max_questions):
    return hard_max_questions if count >= soft_max_questions else soft_max_questions


def progress_message(count, top_p, second_p, focus_thr):
    """質問中に表示する短い進捗メッセージ。返さない時は空文字。"""
    if count <= 0:
        return ''
    gap_ratio = top_p / max(second_p, 0.001)
    if count >= 3 and second_p >= 0.15 and gap_ratio < 1.25:
        return '候補が2つに割れています'
    if top_p >= focus_thr or (count >= 4 and top_p >= 0.45 and gap_ratio >= 2.0):
        return '次の質問でかなり絞れそうです'
    if count % 5 == 0:
        if top_p < 0.35 and gap_ratio < 1.5:
            return 'AIが少し迷っています'
        return 'かなり見えてきました'
    return ''


def should_extend_low_confidence(count, top_p, second_p, guess_threshold, soft_max_questions, hard_max_questions):
    if count < soft_max_questions or count >= hard_max_questions:
        return False
    gap_points = top_p - second_p
    return top_p < guess_threshold or gap_points < 0.20


def make_question_total_for_count(soft_max_questions, hard_max_questions):
    return lambda count: question_total_for_count(count, soft_max_questions, hard_max_questions)


def make_low_confidence_extender(soft_max_questions, hard_max_questions):
    return lambda count, top_p, second_p, guess_threshold: should_extend_low_confidence(
        count,
        top_p,
        second_p,
        guess_threshold,
        soft_max_questions,
        hard_max_questions,
    )


def select_next_question(engine, answers, asked, *, idk_streak=0, disambiguate=False):
    asked_in_order = list(dict.fromkeys(asked))
    if disambiguate:
        return best_disambiguating_question(engine, answers, asked_in_order, idk_streak=idk_streak)
    return best_question(engine, answers, asked_in_order, idk_streak=idk_streak)


def make_next_question_selector(engine):
    return lambda answers, asked, idk_streak=0, disambiguate=False: select_next_question(
        engine,
        answers,
        asked,
        idk_streak=idk_streak,
        disambiguate=disambiguate,
    )


def make_low_exposure_axis_probe(engine, hard_max_questions):
    def probe(answers, asked, *, count, top_p, second_p):
        asked_in_order = list(dict.fromkeys(asked))
        if not should_probe_low_exposure_axis(
            engine,
            answers,
            asked_in_order,
            count=count,
            top_p=top_p,
            second_p=second_p,
            hard_max_questions=hard_max_questions,
        ):
            return None
        return best_low_exposure_axis_question(engine, answers, asked_in_order)

    return probe
