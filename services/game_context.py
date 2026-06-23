from services import context, ids, inference, learning, name_matching, quality_stats, question_selection, result_exposure


PROFILE_MIN_RATIO = 0.25
PROFILE_MIN_PROB = 0.08
COMPOUND_RATIO = 0.55
TRIPLE_RATIO = 0.45


def build(
    *,
    engine,
    flask_runtime,
    random_choice,
    logger,
    player_fetish_base_id,
    soft_max_questions,
    hard_max_questions,
    guess_threshold,
    focus_threshold,
    work_title,
    get_compound_works,
    record_share_event,
    record_question_event,
    preserve_test_play_flag,
    restore_test_play_flag,
    learning_disabled,
    environ=None,
):
    request = flask_runtime.request
    session = flask_runtime.session
    jsonify = flask_runtime.jsonify
    def inference_context():
        return context.build_inference_context(
            engine=engine,
            session=session,
            work_title=work_title,
            get_compound_works=get_compound_works,
            profile_min_ratio=PROFILE_MIN_RATIO,
            profile_min_prob=PROFILE_MIN_PROB,
            compound_ratio=COMPOUND_RATIO,
            triple_ratio=TRIPLE_RATIO,
            adjusted_score_provider=lambda probs, ranked: result_exposure.adjusted_scores(engine, probs, ranked),
        )

    def adjusted_top_guess(engine_arg, answers, n=1):
        probs = inference.posteriors(engine_arg, answers)
        raw_ranked = sorted(range(len(probs)), key=lambda index: probs[index], reverse=True)
        scores = result_exposure.adjusted_scores(engine_arg, probs, raw_ranked)
        ranked = sorted(raw_ranked, key=lambda index: (-scores.get(index, {}).get('adjusted_score', float(probs[index])), raw_ranked.index(index)))
        exclude_ids = set(session.get('exclude_ids', []))
        if exclude_ids:
            ranked = [index for index in ranked if engine_arg.fetishes[index].get('id') not in exclude_ids] + [
                index for index in ranked if engine_arg.fetishes[index].get('id') in exclude_ids
            ]
        return [(index, scores.get(index, {}).get('adjusted_score', float(probs[index]))) for index in ranked[:max(1, int(n or 1))]]

    def make_guess(answers):
        guess_context = context.game_guess(
            engine=engine,
            session=session,
            jsonify=jsonify,
            soft_max_questions=soft_max_questions,
            inference_context=inference_context,
            mark_guess_quality=(
                (lambda engine, session, answers, soft_max: None)
                if learning_disabled() else quality_stats.mark_guess_quality
            ),
            record_question_event=record_question_event,
            record_result_exposure=result_exposure.safe_record_result,
        )
        return inference.make_guess(guess_context, answers)

    runtime = context.game_runtime(
        engine=engine,
        request=request,
        session=session,
        jsonify=jsonify,
        rate_limit=flask_runtime.rate_limit,
        random_choice=random_choice,
        logger=logger,
        record_share_event=record_share_event,
        record_question_event=record_question_event,
        preserve_test_play_flag=preserve_test_play_flag,
        restore_test_play_flag=restore_test_play_flag,
        learning_disabled=learning_disabled,
        environ=environ or {},
    )
    question_flow = context.game_question_flow(
        best_question=question_selection.best_question,
        top_guess=adjusted_top_guess,
        make_guess=make_guess,
        question_total_for_count=question_selection.make_question_total_for_count(
            soft_max_questions, hard_max_questions,
        ),
        soft_max_questions=soft_max_questions,
        hard_max_questions=hard_max_questions,
        guess_threshold=guess_threshold,
        focus_threshold=focus_threshold,
        should_extend_low_confidence=question_selection.make_low_confidence_extender(
            soft_max_questions, hard_max_questions,
        ),
        select_next_question=question_selection.make_next_question_selector(engine),
        select_low_exposure_axis_question=question_selection.make_low_exposure_axis_probe(engine, hard_max_questions),
        progress_message=question_selection.progress_message,
    )
    feedback_factors = learning.make_feedback_factor_provider(engine, environ=environ or {})
    game_learning = context.game_learning(
        learn_factor=learning.make_learn_factor(engine, inference.posteriors, guess_threshold),
        learn_positive=learning.learn_positive,
        learn_cooccurrence=learning.learn_cooccurrence,
        learn_near_miss=learning.learn_near_miss,
        learn_negative=learning.learn_negative,
        positive_feedback_factor=feedback_factors['positive'],
        negative_feedback_factor=feedback_factors['negative'],
        near_miss_feedback_factor=learning.near_miss_feedback_factor,
        posteriors=inference.posteriors,
        parse_id_list=ids.parse_id_list,
        record_guess_quality_feedback=quality_stats.make_guess_quality_feedback_recorder(engine, session),
        find_similar=name_matching.find_similar,
    )
    admin_bridge = context.game_admin_bridge(
        admin_guard_response=flask_runtime.admin_guard_response,
        require_confirm=flask_runtime.require_confirm,
        player_fetish_base_id=player_fetish_base_id,
    )
    return context.build_game_context(runtime, question_flow, game_learning, admin_bridge)
