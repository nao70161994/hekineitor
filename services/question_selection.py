def best_question(engine, answers, asked, *, idk_streak=0, exclude_ids=None):
    if exclude_ids and hasattr(engine, '_best_question_with_exclusions'):
        return engine._best_question_with_exclusions(answers, asked, idk_streak=idk_streak, exclude_ids=exclude_ids)
    return engine.best_question(answers, asked, idk_streak=idk_streak)


def best_disambiguating_question(engine, answers, asked, *, candidate_count=3, idk_streak=0, exclude_ids=None):
    if exclude_ids and hasattr(engine, '_best_disambiguating_question_with_exclusions'):
        return engine._best_disambiguating_question_with_exclusions(
            answers, asked, candidate_count=candidate_count, idk_streak=idk_streak, exclude_ids=exclude_ids
        )
    return engine.best_disambiguating_question(answers, asked, candidate_count=candidate_count, idk_streak=idk_streak)


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


def best_low_exposure_axis_question(
    engine,
    answers,
    asked,
    *,
    preferred_categories=None,
    exclude_ids=None,
    allowed_question_ids=None,
):
    preferred_categories = preferred_categories or LOW_EXPOSURE_DIVERSIFYING_CATEGORIES
    probs = engine.posteriors(answers)
    excluded = {int(value) for value in (exclude_ids or ())}
    if excluded:
        probs = [
            probability if engine.fetishes[index].get('id') not in excluded else 0.0
            for index, probability in enumerate(probs)
        ]
        total = sum(probs)
        probs = [probability / total for probability in probs] if total > 0 else engine.posteriors(answers)
    h0 = engine._entropy(probs)
    best_q, best_score = None, -1.0
    recent_categories = [engine._question_category(q) for q in list(asked)[-3:]]
    allowed = set(allowed_question_ids) if allowed_question_ids is not None else None
    from engine import question_selection as engine_question_selection

    eligible = engine_question_selection.eligible_question_ids(engine, asked)
    for question_id in range(len(engine.questions)):
        if allowed is not None and question_id not in allowed:
            continue
        if question_id in asked or question_id in engine.disabled_questions:
            continue
        if question_id not in eligible:
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


def _recent_idk_dimensions(engine, answers, asked, limit=4):
    axes = set()
    categories = set()
    inspected = 0
    for question_id in reversed(list(asked)):
        if answers.get(str(question_id)) != 0 or inspected >= limit:
            break
        axis = engine._question_axis(question_id)
        category = engine._question_category(question_id)
        if axis:
            axes.add(axis)
        if category:
            categories.add(category)
        inspected += 1
    return axes, categories


def idk_recovery_selection(engine, answers, asked, *, exclude_ids=None):
    """Return a different-axis recovery, with an explicit last-resort fallback."""
    concrete = {'attribute', 'world', 'aesthetic', 'value', 'role'}
    asked_in_order = list(dict.fromkeys(asked))
    recent_axes, recent_categories = _recent_idk_dimensions(engine, answers, asked_in_order)
    from engine import question_selection as engine_question_selection

    eligible = engine_question_selection.eligible_question_ids(engine, asked_in_order)
    alternate = [
        question_id
        for question_id in range(len(engine.questions))
        if question_id not in asked_in_order
        and question_id not in engine.disabled_questions
        and question_id in eligible
        and engine._question_axis(question_id) not in recent_axes
    ]
    different_category = [
        question_id for question_id in alternate if engine._question_category(question_id) not in recent_categories
    ]
    candidates = different_category or alternate
    question_id = best_low_exposure_axis_question(
        engine,
        answers,
        asked_in_order,
        preferred_categories=concrete,
        exclude_ids=exclude_ids,
        allowed_question_ids=candidates,
    )
    if question_id is None and candidates:
        available_categories = {
            engine._question_category(candidate) for candidate in candidates if engine._question_category(candidate)
        }
        question_id = best_low_exposure_axis_question(
            engine,
            answers,
            asked_in_order,
            preferred_categories=available_categories,
            exclude_ids=exclude_ids,
            allowed_question_ids=candidates,
        )
    if question_id is None and candidates:
        question_id = min(
            candidates,
            key=lambda q: sum(engine.matrix['total'][f][q] for f in range(len(engine.fetishes))),
        )
    if question_id is not None:
        return {'question_id': question_id, 'fallback': False, 'avoided_axes': sorted(recent_axes)}
    fallback = best_question(engine, answers, asked_in_order, idk_streak=4, exclude_ids=exclude_ids)
    if fallback is None:
        return None
    return {'question_id': fallback, 'fallback': True, 'avoided_axes': sorted(recent_axes)}


def best_idk_recovery_question(engine, answers, asked, *, exclude_ids=None):
    selection = idk_recovery_selection(engine, answers, asked, exclude_ids=exclude_ids)
    return selection['question_id'] if selection else None


def make_idk_recovery_selector(engine):
    return lambda answers, asked, exclude_ids=None: idk_recovery_selection(
        engine, answers, asked, exclude_ids=exclude_ids
    )


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


def select_next_question(engine, answers, asked, *, idk_streak=0, disambiguate=False, exclude_ids=None):
    asked_in_order = list(dict.fromkeys(asked))
    if disambiguate:
        return best_disambiguating_question(
            engine,
            answers,
            asked_in_order,
            idk_streak=idk_streak,
            exclude_ids=exclude_ids,
        )
    return best_question(
        engine,
        answers,
        asked_in_order,
        idk_streak=idk_streak,
        exclude_ids=exclude_ids,
    )


def make_next_question_selector(engine):
    return lambda answers, asked, idk_streak=0, disambiguate=False, exclude_ids=None: select_next_question(
        engine,
        answers,
        asked,
        idk_streak=idk_streak,
        disambiguate=disambiguate,
        exclude_ids=exclude_ids,
    )


def make_low_exposure_axis_probe(engine, hard_max_questions):
    def probe(answers, asked, *, count, top_p, second_p, exclude_ids=None):
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
        return best_low_exposure_axis_question(engine, answers, asked_in_order, exclude_ids=exclude_ids)

    return probe
