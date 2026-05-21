def best_question(engine, answers, asked, *, idk_streak=0):
    return engine.best_question(answers, asked, idk_streak=idk_streak)


def best_disambiguating_question(engine, answers, asked, *, candidate_count=3, idk_streak=0):
    return engine.best_disambiguating_question(
        answers,
        asked,
        candidate_count=candidate_count,
        idk_streak=idk_streak,
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
        count, top_p, second_p, guess_threshold, soft_max_questions, hard_max_questions,
    )


def select_next_question(engine, answers, asked, *, idk_streak=0, disambiguate=False):
    asked_set = set(asked)
    if disambiguate:
        return best_disambiguating_question(engine, answers, asked_set, idk_streak=idk_streak)
    return best_question(engine, answers, asked_set, idk_streak=idk_streak)


def make_next_question_selector(engine):
    return lambda answers, asked, idk_streak=0, disambiguate=False: select_next_question(
        engine, answers, asked, idk_streak=idk_streak, disambiguate=disambiguate,
    )
