from flask import Blueprint

from services import share, share_links


def question_payload(engine, question_id, question_text, count, total, *, hint=None, progress_message=None, contradictions=None):
    q_data = engine.questions[question_id]
    payload = {
        'action': 'question',
        'question_id': question_id,
        'question': question_text,
        'count': count,
        'total': total,
        'axis': engine._question_axis(question_id),
        'q_hint': q_data.get('hint', ''),
    }
    if hint:
        payload['hint'] = hint
    if progress_message:
        payload['progress_message'] = progress_message
    if contradictions:
        payload['contradictions'] = contradictions
    return payload


def _parse_exclude_ids(raw_ids):
    ids = []
    for value in raw_ids or []:
        try:
            ids.append(int(value))
        except (ValueError, TypeError):
            pass
    return ids


def _parse_question_id(value):
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _question_text(ctx, question_id):
    q_data = ctx.engine.questions[question_id]
    variants = q_data.get('variants', [])
    text = ctx.random_choice([q_data['text']] + variants) if variants else q_data['text']
    return q_data, text


def _record_question_event(ctx, event_name, question_id=None, question_text='', **kwargs):
    recorder = getattr(ctx, 'record_question_event', None)
    if not recorder:
        return
    category = ''
    axis = ''
    if question_id is not None and 0 <= question_id < len(ctx.engine.questions):
        q_data = ctx.engine.questions[question_id]
        category = q_data.get('category', '')
        axis = q_data.get('axis', '')
        question_text = question_text or q_data.get('text', '')
    recorder(
        event_name,
        question_id=question_id,
        question_text=question_text,
        category=category,
        axis=axis,
        **kwargs,
    )


def _record_question_shown(ctx, question_id, question_text):
    _record_question_event(ctx, 'question_shown', question_id, question_text)


def _record_question_answered(ctx, question_id, answer_value):
    _record_question_event(ctx, 'question_answered', question_id, answer=answer_value)


def _clear_active_guess(ctx):
    ctx.session.pop('feedback_status', None)
    _clear_pending_feedback(ctx)
    _clear_guess_ids(ctx)


def _clear_guess_ids(ctx):
    ctx.session.pop('last_guess_fetish_id', None)
    ctx.session.pop('last_guess_compound_ids', None)


def _clear_pending_feedback(ctx):
    ctx.session.pop('wrong_db_ids', None)
    ctx.session.pop('candidate_db_ids', None)
    ctx.session.pop('near_miss_db_ids', None)
    ctx.session.pop('candidate_negative_factor', None)


def _finish_feedback(ctx):
    _clear_pending_feedback(ctx)
    _clear_guess_ids(ctx)
    ctx.session['feedback_status'] = 'done'


def _require_feedback_open(ctx):
    if ctx.session.get('feedback_status') in ('pending_correction', 'done'):
        return ctx.jsonify({
            'status': 'error',
            'message': 'この診断結果へのフィードバックは処理済みです',
        }), 409
    return None


def _require_started(ctx):
    if not ctx.session.get('started'):
        return ctx.jsonify({'status': 'session_expired'}), 440
    return None


def _active_guess_ids(ctx):
    try:
        main_id = int(ctx.session.get('last_guess_fetish_id'))
    except (TypeError, ValueError):
        return None, set()
    compound_ids = ctx.parse_id_list(ctx.session.get('last_guess_compound_ids', []))
    return main_id, compound_ids


def _require_active_guess(ctx):
    started_error = _require_started(ctx)
    if started_error:
        return started_error
    main_id, _ = _active_guess_ids(ctx)
    if main_id is None:
        return ctx.jsonify({'status': 'session_expired', 'message': '診断結果が見つかりません'}), 440
    return None


def _validate_guess_payload(ctx, fetish_db_id, compound_ids=None):
    main_id, active_compound_ids = _active_guess_ids(ctx)
    if main_id is None or fetish_db_id != main_id:
        return ctx.jsonify({'status': 'error', 'message': '現在の診断結果と一致しません'}), 409
    requested_compound_ids = ctx.parse_id_list(compound_ids or [])
    if not requested_compound_ids.issubset(active_compound_ids):
        return ctx.jsonify({'status': 'error', 'message': '現在の診断結果と一致しません'}), 409
    return None


def _feedback_allowed_ids(ctx):
    main_id, active_compound_ids = _active_guess_ids(ctx)
    allowed = set()
    if main_id is not None:
        allowed.add(main_id)
    allowed.update(active_compound_ids)
    allowed.update(ctx.parse_id_list(ctx.session.get('candidate_db_ids', [])))
    allowed.update(ctx.parse_id_list(ctx.session.get('near_miss_db_ids', [])))
    allowed.update(ctx.parse_id_list(ctx.session.get('owned_added_fetish_ids', [])))
    return allowed


def _learning_skipped(ctx):
    resumed_unverified = ctx.session.get('client_resumed') and not ctx.session.get('resume_learning_verified')
    return ctx.learning_disabled() or resumed_unverified


def start(ctx):
    limited = ctx.rate_limit('api_start', 120)
    if limited:
        return limited
    data = ctx.request.get_json(silent=True) or {}
    test_play_enabled = ctx.preserve_test_play_flag()
    ctx.session.clear()
    ctx.restore_test_play_flag(test_play_enabled)
    ctx.engine.increment_start_count()
    ctx.session['answers'] = {}
    ctx.session['asked'] = []
    ctx.session['started'] = True
    ctx.session['completed'] = False
    ctx.session['dropoff_recorded'] = False
    ctx.session['completion_recorded'] = False
    ctx.session['exclude_ids'] = _parse_exclude_ids(data.get('exclude_ids', []))
    question_id = ctx.best_question(ctx.engine, {}, set())
    ctx.session['asked'].append(question_id)
    q_data, q_text = _question_text(ctx, question_id)
    _record_question_shown(ctx, question_id, q_text)
    return ctx.jsonify({
        'question_id': question_id,
        'question': q_text,
        'count': 0,
        'total': ctx.soft_max_questions,
        'axis': ctx.engine._question_axis(question_id),
        'q_hint': q_data.get('hint', ''),
    })


def resume(ctx):
    limited = ctx.rate_limit('api_resume', 60)
    if limited:
        return limited
    data = ctx.request.get_json(silent=True) or {}
    pairs = data.get('pairs', [])
    if not isinstance(pairs, list):
        return ctx.jsonify({'status': 'error', 'message': 'pairs はリストで指定してください'}), 400
    if len(pairs) > ctx.hard_max_questions:
        return ctx.jsonify({'status': 'error', 'message': '復元する回答数が多すぎます'}), 400

    test_play_enabled = ctx.preserve_test_play_flag()
    ctx.session.clear()
    ctx.restore_test_play_flag(test_play_enabled)
    ctx.session['started'] = True
    ctx.session['completed'] = False
    ctx.session['dropoff_recorded'] = False
    ctx.session['completion_recorded'] = False
    ctx.session['answers'] = {}
    ctx.session['asked'] = []
    ctx.session['idk_streak'] = 0
    ctx.session['exclude_ids'] = _parse_exclude_ids(data.get('exclude_ids', []))
    ctx.session['client_resumed'] = bool(pairs)
    ctx.session['resume_learning_verified'] = not bool(pairs)
    if pairs:
        ctx.engine.increment_start_count()
    for item in pairs:
        try:
            question_id = int(item['q_id'])
            answer = float(item['answer'])
        except (KeyError, ValueError, TypeError):
            return ctx.jsonify({'status': 'error', 'message': '不正な復元データです'}), 400
        if answer not in (1, 0.5, 0, -0.5, -1):
            return ctx.jsonify({'status': 'error', 'message': '不正な回答値です'}), 400
        if question_id < 0 or question_id >= len(ctx.engine.questions):
            return ctx.jsonify({'status': 'error', 'message': '不正な質問IDです'}), 400
        if str(question_id) in ctx.session['answers']:
            return ctx.jsonify({'status': 'error', 'message': '重複した質問IDです'}), 400
        ctx.session['answers'][str(question_id)] = answer
        ctx.session['asked'].append(question_id)
        ctx.session['idk_streak'] = ctx.session['idk_streak'] + 1 if answer == 0 else 0

    answers = ctx.session['answers']
    asked = ctx.session['asked']
    if not answers:
        question_id = ctx.best_question(ctx.engine, {}, set())
        ctx.session['asked'].append(question_id)
        q_data, q_text = _question_text(ctx, question_id)
        _record_question_shown(ctx, question_id, q_text)
        return ctx.jsonify(question_payload(ctx.engine, question_id, q_text, 0, ctx.soft_max_questions))

    next_q = ctx.best_question(ctx.engine, answers, set(asked), idk_streak=ctx.session['idk_streak'])
    if next_q is None:
        return ctx.make_guess(answers)
    asked.append(next_q)
    ctx.session['asked'] = asked
    _, q_text = _question_text(ctx, next_q)
    _record_question_shown(ctx, next_q, q_text)
    return ctx.jsonify(question_payload(
        ctx.engine,
        next_q,
        q_text,
        len(asked) - 1,
        ctx.question_total_for_count(len(asked) - 1),
    ))


def continue_game(ctx):
    started_error = _require_started(ctx)
    if started_error:
        return started_error
    _clear_active_guess(ctx)
    ctx.session['completed'] = False
    answers = ctx.session.get('answers', {})
    asked = ctx.session.get('asked', [])
    top2 = ctx.top_guess(ctx.engine, answers, n=2)
    top_p = top2[0][1] if top2 else 0.0
    ctx.session['continue_thr'] = min(top_p + 0.20, 0.95)
    ctx.session['continued'] = True
    next_q = ctx.best_question(ctx.engine, answers, set(asked), idk_streak=0)
    if next_q is None:
        return ctx.jsonify({'status': 'no_question'})
    asked.append(next_q)
    ctx.session['asked'] = asked
    _, q_text = _question_text(ctx, next_q)
    _record_question_shown(ctx, next_q, q_text)
    return ctx.jsonify(question_payload(ctx.engine, next_q, q_text, len(asked) - 1, ctx.hard_max_questions))


def back(ctx):
    started_error = _require_started(ctx)
    if started_error:
        return started_error
    _clear_active_guess(ctx)
    asked = ctx.session.get('asked', [])
    answers = ctx.session.get('answers', {})
    if len(asked) < 2:
        return ctx.jsonify({'status': 'no_history'})
    asked.pop()
    previous_q = asked[-1]
    answers.pop(str(previous_q), None)
    ctx.session['asked'] = asked
    ctx.session['answers'] = answers
    ctx.session['idk_streak'] = 0
    count = max(0, len(asked) - 1)
    return ctx.jsonify({
        'question_id': previous_q,
        'question': ctx.engine.questions[previous_q]['text'],
        'count': count,
        'total': ctx.question_total_for_count(count),
    })


def answer(ctx):
    limited = ctx.rate_limit('api_answer', 240)
    if limited:
        return limited
    started_error = _require_started(ctx)
    if started_error:
        return started_error
    data = ctx.request.get_json(silent=True) or {}
    if 'question_id' not in data or 'answer' not in data:
        return ctx.jsonify({'status': 'error', 'message': 'question_id と answer が必要です'}), 400
    try:
        question_id = int(data['question_id'])
        answer_value = float(data['answer'])
    except (ValueError, TypeError):
        return ctx.jsonify({'status': 'error', 'message': '不正な値です'}), 400
    if answer_value not in (1, 0.5, 0, -0.5, -1):
        return ctx.jsonify({'status': 'error', 'message': '不正な回答値です'}), 400
    if question_id < 0 or question_id >= len(ctx.engine.questions):
        return ctx.jsonify({'status': 'error', 'message': '不正な質問IDです'}), 400

    answers = ctx.session.get('answers', {})
    asked = ctx.session.get('asked', [])
    if not asked or asked[-1] != question_id or str(question_id) in answers:
        return ctx.jsonify({'status': 'error', 'message': '現在の質問IDと一致しません'}), 409
    _clear_active_guess(ctx)
    answers[str(question_id)] = answer_value
    ctx.session['answers'] = answers
    _record_question_answered(ctx, question_id, answer_value)
    if ctx.session.get('client_resumed'):
        ctx.session['resume_learning_verified'] = True

    idk_streak = ctx.session.get('idk_streak', 0)
    idk_streak = idk_streak + 1 if answer_value == 0 else 0
    ctx.session['idk_streak'] = idk_streak

    try:
        top2 = ctx.top_guess(ctx.engine, answers, n=2)
        top_p = top2[0][1]
        second_p = top2[1][1] if len(top2) > 1 else 0.0
        count = len(asked)

        guess_threshold = ctx.engine.config.get('guess_threshold', ctx.guess_threshold)
        if ctx.session.get('continued'):
            guess_threshold = ctx.session.get('continue_thr', min(guess_threshold + 0.20, 0.95))
        gap_ratio = top_p / max(second_p, 0.001)
        early_stop = (count >= 4 and top_p >= 0.70 and gap_ratio >= 3.0) or (count >= 8 and top_p >= 0.55 and gap_ratio >= 2.5)
        effective_threshold = guess_threshold if (gap_ratio >= 1.8 or count >= 10) else min(guess_threshold + 0.10, 0.90)
        extend_low_confidence = ctx.should_extend_low_confidence(count, top_p, second_p, guess_threshold)
        should_guess = (
            idk_streak >= 4
            or top_p >= effective_threshold
            or count >= ctx.hard_max_questions
            or early_stop
            or (count >= ctx.soft_max_questions and not extend_low_confidence)
        )
        if should_guess:
            diversify_count = int(ctx.session.get('low_exposure_axis_probe_count', 0) or 0)
            next_q = None
            if idk_streak < 4 and diversify_count < 2:
                next_q = ctx.select_low_exposure_axis_question(
                    answers,
                    asked,
                    count=count,
                    top_p=top_p,
                    second_p=second_p,
                )
            if next_q is None:
                return ctx.make_guess(answers)
            asked.append(next_q)
            ctx.session['asked'] = asked
            ctx.session['low_exposure_axis_probe_count'] = diversify_count + 1
            _, question_text = _question_text(ctx, next_q)
            _record_question_shown(ctx, next_q, question_text)
            contradictions = ctx.engine.detect_contradictions(answers)
            return ctx.jsonify(question_payload(
                ctx.engine,
                next_q,
                question_text,
                count,
                ctx.question_total_for_count(count),
                hint='候補の質感をもう少し確認します',
                progress_message='AIが別の軸も観測しています',
                contradictions=contradictions,
            ))

        next_q = ctx.select_next_question(
            answers,
            asked,
            idk_streak=idk_streak,
            disambiguate=extend_low_confidence or count >= ctx.soft_max_questions,
        )
        if next_q is None:
            return ctx.make_guess(answers)

        asked.append(next_q)
        ctx.session['asked'] = asked

        focus_threshold = ctx.engine.config.get('focus_threshold', ctx.focus_threshold)
        hint = '答えが見えてきました…もう少しです' if top_p >= focus_threshold else None
        progress_message = ctx.progress_message(count, top_p, second_p, focus_thr=focus_threshold)
        if extend_low_confidence:
            hint = '候補が接戦です。もう少し絞り込みます'
            progress_message = progress_message or 'AIが少し迷っています'
            ctx.session['low_confidence_extended'] = True

        _, question_text = _question_text(ctx, next_q)
        _record_question_shown(ctx, next_q, question_text)
        contradictions = ctx.engine.detect_contradictions(answers)
        return ctx.jsonify(question_payload(
            ctx.engine,
            next_q,
            question_text,
            count,
            ctx.question_total_for_count(count),
            hint=hint,
            progress_message=progress_message,
            contradictions=contradictions,
        ))
    except Exception:
        ctx.logger.exception('answer() 推論エラー')
        return ctx.jsonify({'status': 'session_expired', 'restart': True}), 440


def teach(ctx):
    data = ctx.request.get_json(silent=True) or {}
    if 'fetish_id' not in data:
        return ctx.jsonify({'status': 'error', 'message': 'fetish_id が必要です'}), 400
    try:
        fetish_db_id = int(data['fetish_id'])
    except (ValueError, TypeError):
        return ctx.jsonify({'status': 'error', 'message': '不正な fetish_id です'}), 400
    fetish_idx = ctx.engine.index_of(fetish_db_id)
    if fetish_idx is None:
        return ctx.jsonify({'status': 'error', 'message': '存在しない fetish_id です'}), 400
    active_guess_error = _require_active_guess(ctx)
    if active_guess_error:
        return active_guess_error
    feedback_error = _require_feedback_open(ctx)
    if feedback_error:
        return feedback_error
    main_id, compound_ids = _active_guess_ids(ctx)
    if fetish_db_id not in ({main_id} | compound_ids):
        return ctx.jsonify({'status': 'error', 'message': '現在の診断結果と一致しません'}), 409
    answers = ctx.session.get('answers', {})
    try:
        total_n = max(1, int(data.get('total_n', 1)))
    except (ValueError, TypeError):
        return ctx.jsonify({'status': 'error', 'message': '不正な total_n です'}), 400
    if _learning_skipped(ctx):
        _finish_feedback(ctx)
        return ctx.jsonify({
            'status': 'learned',
            'fetish_name': ctx.engine.fetishes[fetish_idx]['name'],
            'learning_disabled': True,
        })
    factor = ctx.learn_factor(answers, total_n) * ctx.positive_feedback_factor(ctx.engine, fetish_idx)
    ctx.learn_positive(ctx.engine, answers, fetish_idx, strength_factor=factor)
    ctx.engine.log_correct(ctx.engine.fetishes[fetish_idx]['id'])
    _finish_feedback(ctx)
    return ctx.jsonify({'status': 'learned', 'fetish_name': ctx.engine.fetishes[fetish_idx]['name']})


def confirm(ctx):
    data = ctx.request.get_json(silent=True) or {}
    if 'correct' not in data or 'fetish_id' not in data:
        return ctx.jsonify({'status': 'error', 'message': 'correct と fetish_id が必要です'}), 400
    try:
        fetish_db_id = int(data['fetish_id'])
    except (ValueError, TypeError):
        return ctx.jsonify({'status': 'error', 'message': '不正な fetish_id です'}), 400
    fetish_idx = ctx.engine.index_of(fetish_db_id)
    if fetish_idx is None:
        return ctx.jsonify({'status': 'error', 'message': '存在しない fetish_id です'}), 400
    active_guess_error = _require_active_guess(ctx)
    if active_guess_error:
        return active_guess_error
    feedback_error = _require_feedback_open(ctx)
    if feedback_error:
        return feedback_error
    guess_payload_error = _validate_guess_payload(ctx, fetish_db_id, data.get('compound_ids', []))
    if guess_payload_error:
        return guess_payload_error
    answers = ctx.session.get('answers', {})
    learning_disabled = _learning_skipped(ctx)
    defer_learning = bool(data.get('defer_learning'))

    if data['correct']:
        learn_idxs = [fetish_idx]
        for compound_id in data.get('compound_ids', []):
            try:
                compound_idx = ctx.engine.index_of(int(compound_id))
                if compound_idx is not None and compound_idx != fetish_idx:
                    learn_idxs.append(compound_idx)
            except (ValueError, TypeError):
                pass
        if learning_disabled:
            _finish_feedback(ctx)
            return ctx.jsonify({'status': 'learned', 'learning_disabled': True})
        base_factor = ctx.learn_factor(answers, total_n=len(learn_idxs))
        learned_factors = {}
        for idx in learn_idxs:
            factor = base_factor * ctx.positive_feedback_factor(ctx.engine, idx)
            learned_factors[idx] = factor
            ctx.learn_positive(ctx.engine, answers, idx, strength_factor=factor)
            ctx.engine.log_correct(ctx.engine.fetishes[idx]['id'])
        for i in range(len(learn_idxs)):
            for j in range(i + 1, len(learn_idxs)):
                pair_factor = (learned_factors.get(learn_idxs[i], base_factor) + learned_factors.get(learn_idxs[j], base_factor)) / 2
                ctx.learn_cooccurrence(ctx.engine, answers, learn_idxs[i], learn_idxs[j], pair_factor * 0.3)
        ctx.record_guess_quality_feedback(True)
        _finish_feedback(ctx)
        return ctx.jsonify({'status': 'learned'})

    compound_db_ids = set()
    for compound_id in data.get('compound_ids', []):
        try:
            compound_db_ids.add(int(compound_id))
        except (ValueError, TypeError):
            pass
    presented_db_ids = {fetish_db_id} | compound_db_ids
    maybe_db_ids = ctx.parse_id_list(data.get('maybe_ids')) & presented_db_ids
    explicit_wrong_ids = ctx.parse_id_list(data.get('wrong_ids')) & presented_db_ids
    wrong_db_ids = explicit_wrong_ids if ('wrong_ids' in data or 'maybe_ids' in data) else set(presented_db_ids)

    factor = ctx.learn_factor(answers, total_n=max(1, len(maybe_db_ids)))
    if not learning_disabled and not defer_learning:
        for maybe_id in maybe_db_ids:
            maybe_idx = ctx.engine.index_of(maybe_id)
            if maybe_idx is not None:
                near_factor = factor * ctx.near_miss_feedback_factor(ctx.engine, maybe_idx)
                ctx.learn_near_miss(ctx.engine, answers, maybe_idx, strength_factor=near_factor)

    if not data.get('add_only', False) and not learning_disabled and not defer_learning:
        negative_learned_db_ids = []
        for wrong_id in wrong_db_ids:
            ctx.engine.log_wrong(wrong_id)
            wrong_idx = ctx.engine.index_of(wrong_id)
            if wrong_idx is not None:
                ctx.learn_negative(
                    ctx.engine,
                    answers,
                    wrong_idx,
                    strength_factor=ctx.negative_feedback_factor(ctx.engine, wrong_idx),
                )
                negative_learned_db_ids.append(wrong_id)
        if negative_learned_db_ids:
            ctx.session['negative_learned_db_ids'] = sorted(negative_learned_db_ids)
        ctx.record_guess_quality_feedback(False)

    probs = ctx.posteriors(ctx.engine, answers)
    candidates = []
    for idx, fetish in enumerate(ctx.engine.fetishes):
        if fetish['id'] in presented_db_ids:
            continue
        candidates.append((probs[idx], fetish))
    candidates.sort(key=lambda item: item[0], reverse=True)
    sorted_fetishes = [dict(fetish, prob=round(probability * 100, 1)) for probability, fetish in candidates[:20]]

    candidate_ids = [fetish['id'] for fetish in sorted_fetishes]
    if defer_learning:
        ctx.session['wrong_db_ids'] = []
        ctx.session['near_miss_db_ids'] = []
        ctx.session['candidate_db_ids'] = candidate_ids
        ctx.session['candidate_negative_factor'] = 0.3
    elif not data.get('add_only', False):
        ctx.session['wrong_db_ids'] = sorted(wrong_db_ids)
        ctx.session['near_miss_db_ids'] = sorted(maybe_db_ids)
        ctx.session['candidate_db_ids'] = candidate_ids
        ctx.session['candidate_negative_factor'] = 0.15 if maybe_db_ids else 0.3
    else:
        ctx.session['wrong_db_ids'] = []
        ctx.session['near_miss_db_ids'] = []
        ctx.session['candidate_db_ids'] = candidate_ids
        ctx.session['candidate_negative_factor'] = 0.3
    ctx.session['feedback_status'] = 'pending_correction'
    payload = {'status': 'wrong', 'fetishes': sorted_fetishes}
    if learning_disabled:
        payload['learning_disabled'] = True
    return ctx.jsonify(payload)


def add_fetish(ctx):
    data = ctx.request.get_json(silent=True) or {}
    name = data.get('name', '').strip()
    desc = data.get('desc', '').strip()
    confirmed = data.get('confirmed', False)
    answers = ctx.session.get('answers', {})
    if not name:
        return ctx.jsonify({'status': 'error', 'message': '名前を入力してください'}), 400
    if len(name) > 100:
        return ctx.jsonify({'status': 'error', 'message': '名前は100文字以内で入力してください'}), 400
    if len(desc) > 500:
        return ctx.jsonify({'status': 'error', 'message': '説明は500文字以内で入力してください'}), 400
    active_guess_error = _require_active_guess(ctx)
    if active_guess_error:
        return active_guess_error
    existing = next((fetish for fetish in ctx.engine.fetishes if fetish['name'] == name), None)
    if existing:
        return ctx.jsonify({
            'status': 'learned',
            'fetish_name': existing['name'],
            'fetish_id': existing['id'],
            'is_new': False,
        })
    if confirmed:
        if _learning_skipped(ctx):
            return ctx.jsonify({
                'status': 'learned',
                'fetish_name': name,
                'fetish_id': 'test-play',
                'is_new': False,
                'learning_disabled': True,
            })
        if not desc:
            desc = name
        _, db_id = ctx.engine.add_fetish(name, desc, answers)
        owned = set(ctx.session.get('owned_added_fetish_ids', []))
        owned.add(db_id)
        ctx.session['owned_added_fetish_ids'] = sorted(owned)
        return ctx.jsonify({'status': 'learned', 'fetish_name': name, 'fetish_id': db_id, 'is_new': True})
    similar = ctx.find_similar(name, ctx.engine.fetishes)
    if similar:
        return ctx.jsonify({'status': 'similar', 'candidates': similar})
    return ctx.jsonify({'status': 'needs_desc'})


def finalize_added(ctx):
    data = ctx.request.get_json(silent=True) or {}
    items = data.get('items', [])
    if not isinstance(items, list):
        return ctx.jsonify({'status': 'error', 'message': 'items はリストで指定してください'}), 400
    if len(items) > 10:
        return ctx.jsonify({'status': 'error', 'message': 'items は10件以内で指定してください'}), 400
    active_guess_error = _require_active_guess(ctx)
    if active_guess_error:
        return active_guess_error
    allowed_ids = _feedback_allowed_ids(ctx)
    submitted_ids = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            submitted_ids.add(int(item.get('id')))
        except (ValueError, TypeError):
            return ctx.jsonify({'status': 'error', 'message': '不正な fetish_id です'}), 400
    if submitted_ids and not submitted_ids.issubset(allowed_ids):
        return ctx.jsonify({'status': 'error', 'message': '現在の診断候補と一致しません'}), 409
    if _learning_skipped(ctx):
        _finish_feedback(ctx)
        return ctx.jsonify({'status': 'done', 'learning_disabled': True})
    answers = ctx.session.get('answers', {})
    total_n = max(1, len([item for item in items if isinstance(item, dict)]))
    factor = ctx.learn_factor(answers, total_n)
    correct_db_ids = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            db_id = int(item.get('id'))
            is_new = bool(item.get('is_new'))
        except (ValueError, TypeError):
            continue
        idx = ctx.engine.index_of(db_id)
        if idx is None:
            continue
        correct_db_ids.add(db_id)
        ctx.engine.log_correct(db_id)
        if is_new:
            ctx.engine.boost_learn_new(idx, answers)
        else:
            scaled_factor = factor * ctx.positive_feedback_factor(ctx.engine, idx)
            ctx.learn_positive(ctx.engine, answers, idx, strength_factor=scaled_factor)

    correct_idxs = [ctx.engine.index_of(db_id) for db_id in correct_db_ids
                    if ctx.engine.index_of(db_id) is not None]
    for i in range(len(correct_idxs)):
        for j in range(i + 1, len(correct_idxs)):
            pair_factor = (
                ctx.positive_feedback_factor(ctx.engine, correct_idxs[i])
                + ctx.positive_feedback_factor(ctx.engine, correct_idxs[j])
            ) / 2
            ctx.learn_cooccurrence(ctx.engine, answers, correct_idxs[i], correct_idxs[j], factor * pair_factor * 0.3)

    wrong_db_ids = ctx.session.pop('wrong_db_ids', [])
    negative_learned_db_ids = set(ctx.session.pop('negative_learned_db_ids', []))
    for wrong_id in wrong_db_ids:
        if wrong_id not in correct_db_ids and wrong_id not in negative_learned_db_ids:
            wrong_idx = ctx.engine.index_of(wrong_id)
            if wrong_idx is not None:
                ctx.learn_negative(
                    ctx.engine,
                    answers,
                    wrong_idx,
                    strength_factor=ctx.negative_feedback_factor(ctx.engine, wrong_idx),
                )

    candidate_db_ids = ctx.session.pop('candidate_db_ids', [])
    near_miss_db_ids = set(ctx.session.pop('near_miss_db_ids', []))
    already_learned = set(wrong_db_ids) | correct_db_ids | near_miss_db_ids
    unselected = [cid for cid in candidate_db_ids if cid not in already_learned]
    n_unsel = max(1, len(unselected))
    candidate_negative_factor = ctx.session.pop('candidate_negative_factor', 0.3)
    for cid in unselected:
        candidate_idx = ctx.engine.index_of(cid)
        if candidate_idx is not None:
            ctx.learn_negative(
                ctx.engine,
                answers,
                candidate_idx,
                strength_factor=(
                    factor
                    * candidate_negative_factor
                    * ctx.negative_feedback_factor(ctx.engine, candidate_idx)
                    / (n_unsel ** 0.5)
                ),
            )
    _finish_feedback(ctx)
    return ctx.jsonify({'status': 'done'})


def delete_fetish(ctx, fetish_id):
    owned = set(ctx.session.get('owned_added_fetish_ids', []))
    if fetish_id not in owned:
        guard = ctx.admin_guard_response()
        if guard:
            return guard
        confirm_error = ctx.require_confirm('DELETE')
        if confirm_error:
            return confirm_error
    if fetish_id < ctx.player_fetish_base_id:
        return ctx.jsonify({'status': 'error', 'message': 'シード性癖は削除できません'}), 403
    ok = ctx.engine.delete_fetish(fetish_id)
    if not ok:
        return ctx.jsonify({'status': 'error', 'message': '見つかりません'}), 404
    if fetish_id in owned:
        owned.remove(fetish_id)
        ctx.session['owned_added_fetish_ids'] = sorted(owned)
    return ctx.jsonify({'status': 'deleted'})


def create_share_link(ctx):
    limited = ctx.rate_limit('api_share_link', 120)
    if limited:
        return limited
    data = ctx.request.get_json(silent=True) or {}
    name = str(data.get('name') or data.get('result_name') or data.get('fetish') or data.get('f') or '')[:60]
    probability = share.clean_probability(data.get('probability') or data.get('percent') or data.get('p') or '')
    desc = str(data.get('desc') or data.get('d') or '')[:120]
    if not name:
        return ctx.jsonify({'status': 'error', 'message': 'name is required'}), 400
    try:
        share_id, payload = share_links.create_link({
            'name': name,
            'probability': probability,
            'desc': desc,
            'title': share.result_title(probability),
            'rank': share.result_rarity(probability),
        })
    except (OSError, RuntimeError, ValueError):
        return ctx.jsonify({'status': 'error', 'message': 'share link could not be created'}), 500
    return ctx.jsonify({
        'status': 'ok',
        'share_id': share_id,
        'share_url': f'/r/{share_id}',
        'result': payload,
    })


def share_event(ctx):
    limited = ctx.rate_limit('api_share_event', 180)
    if limited:
        return limited
    data = ctx.request.get_json(silent=True) or {}
    event = ctx.record_share_event(
        data.get('event_name', ''),
        result_name=data.get('result_name', ''),
        channel=data.get('channel', ''),
        success=data.get('success') if 'success' in data else None,
    )
    return ctx.jsonify({'status': 'ok', 'recorded': bool(event)})



def dropoff(ctx):
    limited = ctx.rate_limit('api_dropoff', 240)
    if limited:
        return limited
    if not ctx.session.get('started'):
        return ctx.jsonify({'status': 'ignored', 'reason': 'not_started'})
    if ctx.session.get('completed') or ctx.session.get('dropoff_recorded'):
        return ctx.jsonify({'status': 'ignored', 'reason': 'already_finalized'})
    answers = ctx.session.get('answers', {})
    answered_count = len(answers) if isinstance(answers, dict) else 0
    data = ctx.request.get_json(silent=True) or {}
    question_id = data.get('question_id')
    if question_id is None:
        asked = ctx.session.get('asked', [])
        question_id = asked[-1] if asked else None
    else:
        question_id = _parse_question_id(question_id)
        if question_id is None or question_id < 0 or question_id >= len(ctx.engine.questions):
            return ctx.jsonify({'status': 'error', 'message': '不正な question_id です'}), 400
    _record_question_event(ctx, 'question_dropoff', question_id, answered_count=answered_count)
    ctx.engine.log_dropoff(answered_count)
    ctx.session['dropoff_recorded'] = True
    return ctx.jsonify({'status': 'ok', 'answered_count': answered_count})


def create_blueprint(ctx_factory):
    bp = Blueprint('game', __name__)

    @bp.route('/api/start', methods=['POST'])
    def start_route():
        return start(ctx_factory())

    @bp.route('/api/resume', methods=['POST'])
    def resume_route():
        return resume(ctx_factory())

    @bp.route('/api/continue', methods=['POST'])
    def continue_game_route():
        return continue_game(ctx_factory())

    @bp.route('/api/answer', methods=['POST'])
    def answer_route():
        return answer(ctx_factory())

    @bp.route('/api/dropoff', methods=['POST'])
    def dropoff_route():
        return dropoff(ctx_factory())

    @bp.route('/api/back', methods=['POST'])
    def back_route():
        return back(ctx_factory())

    @bp.route('/api/confirm', methods=['POST'])
    def confirm_route():
        return confirm(ctx_factory())

    @bp.route('/api/teach', methods=['POST'])
    def teach_route():
        return teach(ctx_factory())

    @bp.route('/api/add_fetish', methods=['POST'])
    def add_fetish_route():
        return add_fetish(ctx_factory())

    @bp.route('/api/finalize_added', methods=['POST'])
    def finalize_added_route():
        return finalize_added(ctx_factory())

    @bp.route('/api/fetish/<int:fetish_id>', methods=['DELETE'])
    def delete_fetish_route(fetish_id):
        return delete_fetish(ctx_factory(), fetish_id)

    @bp.route('/api/share_link', methods=['POST'])
    def create_share_link_route():
        return create_share_link(ctx_factory())

    @bp.route('/api/share_event', methods=['POST'])
    def share_event_route():
        return share_event(ctx_factory())

    return bp
