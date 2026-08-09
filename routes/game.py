from contextlib import nullcontext

from flask import Blueprint

from services import share, share_links

MAX_NEW_FETISHES_PER_DIAGNOSIS = 3
_SHOWN_QUESTIONS_KEY = 'shown_question_payloads'


def question_payload(
    engine,
    question_id,
    question_text,
    count,
    total,
    *,
    hint=None,
    progress_message=None,
    contradictions=None,
    recovery_fallback=False,
):
    q_data = engine.questions[question_id]
    payload = {
        'action': 'question',
        'question_id': question_id,
        'question': question_text,
        'count': count,
        'total': total,
        'axis': engine._question_axis(question_id),
        'answer_frame': q_data.get('answer_frame', ''),
    }
    if hint:
        payload['hint'] = hint
    if progress_message:
        payload['progress_message'] = progress_message
    if contradictions:
        payload['contradictions'] = contradictions
    if recovery_fallback:
        payload['recovery_fallback'] = True
    return payload


def _remember_question_payload(ctx, payload):
    """Keep the exact UI context for back navigation in the signed session."""
    if not isinstance(payload, dict) or 'question_id' not in payload:
        return payload
    allowed = (
        'action',
        'question_id',
        'question',
        'count',
        'total',
        'axis',
        'answer_frame',
        'hint',
        'progress_message',
        'contradictions',
        'recovery_fallback',
    )
    compact = {key: payload[key] for key in allowed if key in payload}
    history = dict(ctx.session.get(_SHOWN_QUESTIONS_KEY, {}))
    history[str(payload['question_id'])] = compact
    asked = ctx.session.get('asked', [])
    active_ids = {str(question_id) for question_id in asked[-ctx.hard_max_questions :]}
    ctx.session[_SHOWN_QUESTIONS_KEY] = {key: value for key, value in history.items() if key in active_ids}
    return payload


def _question_response(ctx, payload):
    return ctx.jsonify(_remember_question_payload(ctx, payload))


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
    if getattr(ctx, 'learning_disabled', lambda: False)():
        return
    recorder = getattr(ctx, 'record_question_event', None)
    if not recorder:
        return
    category = ''
    axis = ''
    if question_id is not None and 0 <= question_id < len(ctx.engine.questions):
        q_data = ctx.engine.questions[question_id]
        category = q_data.get('category', '')
        axis = q_data.get('axis', '')
        if not axis:
            question_axis = getattr(ctx.engine, '_question_axis', None)
            if callable(question_axis):
                axis = question_axis(question_id) or ''
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
    asked = ctx.session.get('asked', [])
    recorder = getattr(ctx, 'record_gameplay_event', None)
    if callable(recorder) and asked.count(question_id) > 1 and not ctx.learning_disabled():
        recorder('question_repeated', source='start', outcome='failure', question_id=question_id)
    _record_question_event(ctx, 'question_shown', question_id, question_text)


def _record_question_answered(ctx, question_id, answer_value):
    _record_question_event(ctx, 'question_answered', question_id, answer=answer_value)


def _record_question_feedback_learning(ctx, answers, feedback_kind, target_count):
    if target_count <= 0 or not isinstance(answers, dict):
        return
    question_stats = {}
    stats_provider = getattr(ctx.engine, 'get_question_stats', None)
    if callable(stats_provider):
        try:
            question_stats = {int(row['id']): row for row in stats_provider()}
        except (KeyError, TypeError, ValueError):
            question_stats = {}
    for question_id, answer in answers.items():
        try:
            question_id = int(question_id)
            answer = float(answer)
        except (TypeError, ValueError):
            continue
        if answer == 0 or not (0 <= question_id < len(ctx.engine.questions)):
            continue
        _record_question_event(
            ctx,
            'question_feedback_learned',
            question_id,
            answer=answer,
            feedback_kind=feedback_kind,
            target_count=target_count,
            discrimination=(question_stats.get(question_id) or {}).get('disc'),
        )


def _clear_active_guess(ctx):
    ctx.session.pop('feedback_status', None)
    _clear_pending_feedback(ctx)
    _clear_guess_ids(ctx)


def _clear_guess_ids(ctx):
    ctx.session.pop('last_guess_fetish_id', None)
    ctx.session.pop('last_guess_compound_ids', None)


def _clear_pending_feedback(ctx):
    ctx.session.pop('wrong_db_ids', None)
    ctx.session.pop('negative_learned_db_ids', None)
    ctx.session.pop('candidate_db_ids', None)
    ctx.session.pop('near_miss_db_ids', None)
    ctx.session.pop('candidate_negative_factor', None)
    ctx.session.pop('pending_feedback_outcome', None)
    ctx.session.pop('pending_presented_ids', None)
    ctx.session.pop('pending_correct_db_ids', None)
    ctx.session.pop('staged_correction_db_ids', None)


def _finish_feedback(ctx, *, correction_count=0):
    feedback_outcome = ctx.session.get('pending_feedback_outcome', 'yes')
    if feedback_outcome not in {'yes', 'maybe', 'no'}:
        feedback_outcome = 'no'
    if not ctx.learning_disabled():
        ctx.record_gameplay_event(
            'feedback_completed',
            source='feedback',
            outcome=feedback_outcome,
            correction_count=correction_count,
        )
    _clear_pending_feedback(ctx)
    _clear_guess_ids(ctx)
    ctx.session['feedback_status'] = 'done'


def _require_feedback_open(ctx):
    if ctx.session.get('feedback_status') in ('pending_correction', 'done'):
        return (
            ctx.jsonify(
                {
                    'status': 'error',
                    'message': 'この診断結果へのフィードバックは処理済みです',
                }
            ),
            409,
        )
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
    allowed.update(ctx.parse_id_list(ctx.session.get('staged_correction_db_ids', [])))
    return allowed


def _stage_correction_ids(ctx, values):
    staged = ctx.parse_id_list(ctx.session.get('staged_correction_db_ids', []))
    staged.update(ctx.parse_id_list(values))
    ctx.session['staged_correction_db_ids'] = sorted(staged)


def _learning_skipped(ctx):
    resumed_unverified = ctx.session.get('client_resumed') and not ctx.session.get('resume_learning_verified')
    return ctx.learning_disabled() or resumed_unverified


def start(ctx):
    limited = ctx.rate_limit('api_start', 120)
    if limited:
        return limited
    data = ctx.request.get_json(silent=True) or {}
    previously_completed = bool(ctx.session.get('completed'))
    if not ctx.learning_disabled():
        ctx.finalize_gameplay_summary('completed' if previously_completed else 'restarted')
    test_play_enabled = ctx.preserve_test_play_flag()
    ctx.session.clear()
    ctx.restore_test_play_flag(test_play_enabled)
    if not ctx.learning_disabled():
        ctx.engine.increment_start_count()
    ctx.session['answers'] = {}
    ctx.session['asked'] = []
    ctx.session['started'] = True
    ctx.session['completed'] = False
    ctx.session['idk_recovery_count'] = 0
    ctx.session['dropoff_recorded'] = False
    ctx.session['completion_recorded'] = False
    ctx.session['exclude_ids'] = _parse_exclude_ids(data.get('exclude_ids', []))
    if not ctx.learning_disabled():
        if ctx.session['exclude_ids']:
            event_name = 'exclude_retry_started'
        elif previously_completed:
            event_name = 'retry_started'
        else:
            event_name = 'diagnosis_started'
        ctx.record_gameplay_event(event_name, source='start', outcome='success')
    question_id = ctx.best_question(ctx.engine, {}, [], exclude_ids=ctx.session.get('exclude_ids', []))
    ctx.session['asked'].append(question_id)
    q_data, q_text = _question_text(ctx, question_id)
    _record_question_shown(ctx, question_id, q_text)
    return _question_response(
        ctx,
        {
            'question_id': question_id,
            'question': q_text,
            'count': 0,
            'total': ctx.soft_max_questions,
            'axis': ctx.engine._question_axis(question_id),
            'answer_frame': q_data.get('answer_frame', ''),
        },
    )


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

    if not ctx.learning_disabled():
        ctx.finalize_gameplay_summary('completed' if ctx.session.get('completed') else 'restarted')
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
    ctx.session['idk_recovery_count'] = 0
    ctx.session['exclude_ids'] = _parse_exclude_ids(data.get('exclude_ids', []))
    if not ctx.learning_disabled():
        ctx.record_gameplay_event('resume_started', source='resume', outcome='success', answered_count=len(pairs))
    ctx.session['client_resumed'] = bool(pairs)
    ctx.session['resume_learning_verified'] = not bool(pairs)
    if pairs and not ctx.learning_disabled():
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
        question_id = ctx.best_question(ctx.engine, {}, [], exclude_ids=ctx.session.get('exclude_ids', []))
        ctx.session['asked'].append(question_id)
        q_data, q_text = _question_text(ctx, question_id)
        _record_question_shown(ctx, question_id, q_text)
        return _question_response(ctx, question_payload(ctx.engine, question_id, q_text, 0, ctx.soft_max_questions))

    next_q = ctx.best_question(
        ctx.engine,
        answers,
        asked,
        idk_streak=ctx.session['idk_streak'],
        exclude_ids=ctx.session.get('exclude_ids', []),
    )
    if next_q is None:
        return ctx.make_guess(answers)
    asked.append(next_q)
    ctx.session['asked'] = asked
    _, q_text = _question_text(ctx, next_q)
    _record_question_shown(ctx, next_q, q_text)
    return _question_response(
        ctx,
        question_payload(
            ctx.engine,
            next_q,
            q_text,
            len(asked) - 1,
            ctx.question_total_for_count(len(asked) - 1),
        ),
    )


def continue_game(ctx):
    started_error = _require_started(ctx)
    if started_error:
        return started_error
    _clear_active_guess(ctx)
    ctx.session['completed'] = False
    ctx.session.pop('provisional_result', None)
    answers = ctx.session.get('answers', {})
    asked = ctx.session.get('asked', [])
    top2 = ctx.top_guess(ctx.engine, answers, n=2)
    top_p = top2[0][1] if top2 else 0.0
    ctx.session['continue_thr'] = min(top_p + 0.20, 0.95)
    ctx.session['continued'] = True
    if not ctx.learning_disabled():
        ctx.record_gameplay_event('continue_started', source='result', outcome='success', answered_count=len(answers))
    next_q = ctx.best_question(ctx.engine, answers, asked, idk_streak=0, exclude_ids=ctx.session.get('exclude_ids', []))
    if next_q is None:
        return ctx.jsonify({'status': 'no_question'})
    asked.append(next_q)
    ctx.session['asked'] = asked
    _, q_text = _question_text(ctx, next_q)
    _record_question_shown(ctx, next_q, q_text)
    return _question_response(ctx, question_payload(ctx.engine, next_q, q_text, len(asked) - 1, ctx.hard_max_questions))


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
    ctx.session['idk_recovery_count'] = 0
    ctx.session.pop('provisional_result', None)
    count = max(0, len(asked) - 1)
    stored = ctx.session.get(_SHOWN_QUESTIONS_KEY, {}).get(str(previous_q))
    if isinstance(stored, dict):
        payload = dict(stored)
    else:
        q_data = ctx.engine.questions[previous_q]
        payload = question_payload(ctx.engine, previous_q, q_data['text'], count, ctx.question_total_for_count(count))
    return ctx.jsonify(payload)


_ANSWER_REPLAY_KEY = 'last_answer_request'
_ANSWER_REQUEST_ID_MAX_LENGTH = 64


def _answer_request_id(value):
    if not isinstance(value, str):
        return ''
    value = value.strip()
    if not value.isascii() or not (8 <= len(value) <= _ANSWER_REQUEST_ID_MAX_LENGTH):
        return ''
    if not all(char.isalnum() or char in '_-' for char in value):
        return ''
    return value


def _answer_replay_response(ctx, request_id, question_id, answer_value):
    replay = ctx.session.get(_ANSWER_REPLAY_KEY)
    if not request_id or not isinstance(replay, dict) or replay.get('request_id') != request_id:
        return None
    if replay.get('question_id') != question_id or replay.get('answer') != answer_value:
        return ctx.jsonify({'status': 'error', 'message': '同じ answer_request_id に異なる回答は指定できません'}), 409
    payload = replay.get('response')
    if not isinstance(payload, dict):
        return ctx.jsonify({'status': 'error', 'message': '回答の再生データが不正です'}), 409
    return ctx.jsonify(payload), int(replay.get('status_code') or 200)


def _store_answer_replay(ctx, request_id, question_id, answer_value, response):
    if not request_id:
        return response
    payload = response.get_json(silent=True)
    if response.status_code == 200 and isinstance(payload, dict) and payload.get('action') in ('question', 'guess'):
        # One server-side entry is sufficient: the client cannot advance until
        # this response arrives, while replay storage remains strictly bounded.
        ctx.session[_ANSWER_REPLAY_KEY] = {
            'request_id': request_id,
            'question_id': question_id,
            'answer': answer_value,
            'status_code': response.status_code,
            'response': payload,
        }
    return response


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

    request_id_value = data.get('answer_request_id')
    request_id = _answer_request_id(request_id_value)
    if request_id_value is not None and not request_id:
        return ctx.jsonify({'status': 'error', 'message': '不正な answer_request_id です'}), 400

    replay = _answer_replay_response(ctx, request_id, question_id, answer_value)
    if replay is not None:
        return replay

    def replayable(response):
        return _store_answer_replay(ctx, request_id, question_id, answer_value, response)

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
    if answer_value != 0:
        ctx.session['idk_recovery_count'] = 0
        ctx.session.pop('provisional_result', None)

    try:
        top2 = ctx.top_guess(ctx.engine, answers, n=2)
        top_p = top2[0][1]
        second_p = top2[1][1] if len(top2) > 1 else 0.0
        count = len(asked)

        guess_threshold = ctx.engine.config.get('guess_threshold', ctx.guess_threshold)
        if ctx.session.get('continued'):
            guess_threshold = ctx.session.get('continue_thr', min(guess_threshold + 0.20, 0.95))
        gap_ratio = top_p / max(second_p, 0.001)
        early_stop = (count >= 4 and top_p >= 0.70 and gap_ratio >= 3.0) or (
            count >= 8 and top_p >= 0.55 and gap_ratio >= 2.5
        )
        effective_threshold = (
            guess_threshold if (gap_ratio >= 1.8 or count >= 10) else min(guess_threshold + 0.10, 0.90)
        )
        extend_low_confidence = ctx.should_extend_low_confidence(count, top_p, second_p, guess_threshold)
        recovery_count = int(ctx.session.get('idk_recovery_count', 0) or 0)
        if idk_streak >= 4 and recovery_count < 2 and count < ctx.hard_max_questions:
            recovery = ctx.select_idk_recovery_question(answers, asked, exclude_ids=ctx.session.get('exclude_ids', []))
            recovery_q = recovery.get('question_id') if isinstance(recovery, dict) else recovery
            if recovery_q is not None:
                recovery_fallback = bool(isinstance(recovery, dict) and recovery.get('fallback'))
                asked.append(recovery_q)
                ctx.session['asked'] = asked
                ctx.session['idk_recovery_count'] = recovery_count + 1
                _, recovery_text = _question_text(ctx, recovery_q)
                _record_question_shown(ctx, recovery_q, recovery_text)
                response = _question_response(
                    ctx,
                    question_payload(
                        ctx.engine,
                        recovery_q,
                        recovery_text,
                        count,
                        ctx.question_total_for_count(count),
                        hint=(
                            '別軸の未回答質問がないため、残る質問から確認します'
                            if recovery_fallback
                            else '答えやすい別の軸から、もう少しだけ確認します'
                        ),
                        progress_message=(
                            '別軸候補を使い切ったため、通常選択へ戻りました'
                            if recovery_fallback
                            else 'まだ読み切れないため、具体的な質問に切り替えました'
                        ),
                        contradictions=ctx.engine.detect_contradictions(answers),
                        recovery_fallback=recovery_fallback,
                    ),
                )
                return replayable(response)

        should_guess = (
            idk_streak >= 6
            or top_p >= effective_threshold
            or count >= ctx.hard_max_questions
            or early_stop
            or (count >= ctx.soft_max_questions and not extend_low_confidence)
        )
        if should_guess:
            if idk_streak >= 4:
                ctx.session['provisional_result'] = True
            diversify_count = int(ctx.session.get('low_exposure_axis_probe_count', 0) or 0)
            next_q = None
            if idk_streak < 4 and diversify_count < 2:
                next_q = ctx.select_low_exposure_axis_question(
                    answers,
                    asked,
                    count=count,
                    top_p=top_p,
                    second_p=second_p,
                    exclude_ids=ctx.session.get('exclude_ids', []),
                )
            if next_q is None:
                return replayable(ctx.make_guess(answers))
            asked.append(next_q)
            ctx.session['asked'] = asked
            ctx.session['low_exposure_axis_probe_count'] = diversify_count + 1
            _, question_text = _question_text(ctx, next_q)
            _record_question_shown(ctx, next_q, question_text)
            contradictions = ctx.engine.detect_contradictions(answers)
            response = _question_response(
                ctx,
                question_payload(
                    ctx.engine,
                    next_q,
                    question_text,
                    count,
                    ctx.question_total_for_count(count),
                    hint='候補の質感をもう少し確認します',
                    progress_message='AIが別の軸も観測しています',
                    contradictions=contradictions,
                ),
            )
            return replayable(response)

        next_q = ctx.select_next_question(
            answers,
            asked,
            idk_streak=idk_streak,
            disambiguate=extend_low_confidence or count >= ctx.soft_max_questions,
            exclude_ids=ctx.session.get('exclude_ids', []),
        )
        if next_q is None:
            return replayable(ctx.make_guess(answers))

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
        response = _question_response(
            ctx,
            question_payload(
                ctx.engine,
                next_q,
                question_text,
                count,
                ctx.question_total_for_count(count),
                hint=hint,
                progress_message=progress_message,
                contradictions=contradictions,
            ),
        )
        return replayable(response)
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
        return ctx.jsonify(
            {
                'status': 'learned',
                'fetish_name': ctx.engine.fetishes[fetish_idx]['name'],
                'learning_disabled': True,
            }
        )
    factor = ctx.learn_factor(answers, total_n) * ctx.positive_feedback_factor(ctx.engine, fetish_idx)
    ctx.learn_positive(ctx.engine, answers, fetish_idx, strength_factor=factor)
    ctx.engine.log_correct(ctx.engine.fetishes[fetish_idx]['id'])
    _record_question_feedback_learning(ctx, answers, 'positive', 1)
    _finish_feedback(ctx)
    return ctx.jsonify({'status': 'learned', 'fetish_name': ctx.engine.fetishes[fetish_idx]['name']})


def _batch_feedback_sets(ctx, data, presented_ids):
    if 'correct_ids' not in data:
        return None, None
    raw = {
        'correct': ctx.parse_id_list(data.get('correct_ids')),
        'maybe': ctx.parse_id_list(data.get('maybe_ids')),
        'wrong': ctx.parse_id_list(data.get('wrong_ids')),
    }
    if any(not values.issubset(presented_ids) for values in raw.values()):
        return None, (ctx.jsonify({'status': 'error', 'message': '現在の診断結果と一致しません'}), 409)
    if (raw['correct'] & raw['maybe']) or (raw['correct'] & raw['wrong']) or (raw['maybe'] & raw['wrong']):
        return None, (
            ctx.jsonify({'status': 'error', 'message': '同じ診断項目に複数の評価は指定できません'}),
            400,
        )
    if set().union(*raw.values()) != presented_ids:
        return None, (
            ctx.jsonify({'status': 'error', 'message': 'すべての診断項目を1回ずつ評価してください'}),
            400,
        )
    return raw, None


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
        with getattr(ctx.engine, 'feedback_batch', nullcontext)():
            base_factor = ctx.learn_factor(answers, total_n=len(learn_idxs))
            learned_factors = {}
            for idx in learn_idxs:
                factor = base_factor * ctx.positive_feedback_factor(ctx.engine, idx)
                learned_factors[idx] = factor
                ctx.learn_positive(ctx.engine, answers, idx, strength_factor=factor)
                ctx.engine.log_correct(ctx.engine.fetishes[idx]['id'])
            for i in range(len(learn_idxs)):
                for j in range(i + 1, len(learn_idxs)):
                    pair_factor = (
                        learned_factors.get(learn_idxs[i], base_factor)
                        + learned_factors.get(learn_idxs[j], base_factor)
                    ) / 2
                    ctx.learn_cooccurrence(ctx.engine, answers, learn_idxs[i], learn_idxs[j], pair_factor * 0.3)
            ctx.record_guess_quality_feedback(True)
            _record_question_feedback_learning(ctx, answers, 'positive', len(learn_idxs))
        _finish_feedback(ctx)
        return ctx.jsonify({'status': 'learned'})

    compound_db_ids = set()
    for compound_id in data.get('compound_ids', []):
        try:
            compound_db_ids.add(int(compound_id))
        except (ValueError, TypeError):
            pass
    presented_db_ids = {fetish_db_id} | compound_db_ids
    batch, batch_error = _batch_feedback_sets(ctx, data, presented_db_ids)
    if batch_error:
        return batch_error
    correct_db_ids = batch['correct'] if batch else set()
    maybe_db_ids = batch['maybe'] if batch else ctx.parse_id_list(data.get('maybe_ids')) & presented_db_ids
    explicit_wrong_ids = batch['wrong'] if batch else ctx.parse_id_list(data.get('wrong_ids')) & presented_db_ids
    wrong_db_ids = explicit_wrong_ids if ('wrong_ids' in data or 'maybe_ids' in data) else set(presented_db_ids)
    if defer_learning and not batch and not maybe_db_ids and not wrong_db_ids:
        maybe_db_ids = set(presented_db_ids)
    complete_without_correction = bool(batch and correct_db_ids == presented_db_ids)
    defer_learning = defer_learning or not complete_without_correction

    with getattr(ctx.engine, 'feedback_batch', nullcontext)():
        positive_learned_count = 0
        positive_idxs = []
        if not learning_disabled and not defer_learning and correct_db_ids:
            positive_factor = ctx.learn_factor(answers, total_n=max(1, len(correct_db_ids)))
            for correct_id in correct_db_ids:
                correct_idx = ctx.engine.index_of(correct_id)
                if correct_idx is None:
                    continue
                positive_idxs.append(correct_idx)
                strength = positive_factor * ctx.positive_feedback_factor(ctx.engine, correct_idx)
                ctx.learn_positive(ctx.engine, answers, correct_idx, strength_factor=strength)
                ctx.engine.log_correct(correct_id)
                positive_learned_count += 1
            for position, left in enumerate(positive_idxs):
                for right in positive_idxs[position + 1 :]:
                    pair_factor = (
                        ctx.positive_feedback_factor(ctx.engine, left) + ctx.positive_feedback_factor(ctx.engine, right)
                    ) / 2
                    ctx.learn_cooccurrence(ctx.engine, answers, left, right, positive_factor * pair_factor * 0.3)

        factor = ctx.learn_factor(answers, total_n=max(1, len(maybe_db_ids)))
        near_learned_count = 0
        if not learning_disabled and not defer_learning:
            for maybe_id in maybe_db_ids:
                maybe_idx = ctx.engine.index_of(maybe_id)
                if maybe_idx is not None:
                    near_factor = factor * ctx.near_miss_feedback_factor(ctx.engine, maybe_idx)
                    ctx.learn_near_miss(ctx.engine, answers, maybe_idx, strength_factor=near_factor)
                    near_learned_count += 1

        negative_learned_db_ids = []
        if not data.get('add_only', False) and not learning_disabled and not defer_learning:
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
            if wrong_db_ids or maybe_db_ids:
                ctx.record_guess_quality_feedback(False)

        learned_target_count = positive_learned_count + near_learned_count + len(negative_learned_db_ids)
        if learned_target_count:
            if sum(bool(value) for value in (positive_learned_count, near_learned_count, negative_learned_db_ids)) > 1:
                feedback_kind = 'mixed'
            elif positive_learned_count:
                feedback_kind = 'positive'
            elif near_learned_count:
                feedback_kind = 'near_miss'
            else:
                feedback_kind = 'negative'
            _record_question_feedback_learning(ctx, answers, feedback_kind, learned_target_count)
        if batch and correct_db_ids == presented_db_ids and not learning_disabled:
            ctx.record_guess_quality_feedback(True)

    if batch and correct_db_ids == presented_db_ids:
        _finish_feedback(ctx)
        payload = {'status': 'learned', 'processed_count': len(presented_db_ids), 'atomic': True}
        if learning_disabled:
            payload['learning_disabled'] = True
        return ctx.jsonify(payload)

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
        ctx.session['wrong_db_ids'] = sorted(wrong_db_ids)
        ctx.session['near_miss_db_ids'] = sorted(maybe_db_ids)
        ctx.session['pending_correct_db_ids'] = sorted(correct_db_ids)
        ctx.session['candidate_db_ids'] = candidate_ids
        ctx.session['pending_feedback_outcome'] = 'maybe' if maybe_db_ids else 'no'
        ctx.session['pending_presented_ids'] = sorted(presented_db_ids)
    # Every response that needs a correction is finalized in one later batch.
    # Keeping an immediate-learning branch here would split the user's rating
    # from the selected correction and make retries capable of double learning.
    ctx.session['feedback_status'] = 'pending_correction'
    payload = {'status': 'wrong', 'fetishes': sorted_fetishes}
    if batch:
        payload.update({'processed_count': len(presented_db_ids), 'atomic': True})
    if learning_disabled:
        payload['learning_disabled'] = True
    return ctx.jsonify(payload)


def add_fetish(ctx):
    limited = ctx.rate_limit('api_add_fetish', 20)
    if limited:
        return limited
    data = ctx.request.get_json(silent=True) or {}
    name_value = data.get('name', '')
    desc_value = data.get('desc', '')
    if not isinstance(name_value, str) or not isinstance(desc_value, str):
        return ctx.jsonify({'status': 'error', 'message': 'name と desc は文字列で指定してください'}), 400
    if 'confirmed' in data and not isinstance(data['confirmed'], bool):
        return ctx.jsonify({'status': 'error', 'message': 'confirmed は真偽値で指定してください'}), 400
    name = name_value.strip()
    desc = desc_value.strip()
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
        _stage_correction_ids(ctx, [existing['id']])
        return ctx.jsonify(
            {
                'status': 'learned',
                'fetish_name': existing['name'],
                'fetish_id': existing['id'],
                'is_new': False,
            }
        )
    if confirmed:
        if _learning_skipped(ctx):
            return ctx.jsonify(
                {
                    'status': 'learned',
                    'fetish_name': name,
                    'fetish_id': 'test-play',
                    'is_new': False,
                    'learning_disabled': True,
                }
            )
        owned = set(ctx.session.get('owned_added_fetish_ids', []))
        if len(owned) >= MAX_NEW_FETISHES_PER_DIAGNOSIS:
            return (
                ctx.jsonify(
                    {
                        'status': 'error',
                        'message': f'1回の診断で追加できる性癖は{MAX_NEW_FETISHES_PER_DIAGNOSIS}件までです',
                    }
                ),
                409,
            )
        if not desc:
            desc = name
        _, db_id = ctx.engine.add_fetish(name, desc, answers)
        owned.add(db_id)
        ctx.session['owned_added_fetish_ids'] = sorted(owned)
        return ctx.jsonify({'status': 'learned', 'fetish_name': name, 'fetish_id': db_id, 'is_new': True})
    similar = ctx.find_similar(name, ctx.engine.fetishes)
    if similar:
        _stage_correction_ids(ctx, [candidate.get('id') for candidate in similar])
        return ctx.jsonify({'status': 'similar', 'candidates': similar})
    return ctx.jsonify({'status': 'needs_desc'})


def finalize_added(ctx):
    data = ctx.request.get_json(silent=True) or {}
    items = data.get('items', [])
    if not isinstance(items, list):
        return ctx.jsonify({'status': 'error', 'message': 'items はリストで指定してください'}), 400
    if len(items) > 10:
        return ctx.jsonify({'status': 'error', 'message': 'items は10件以内で指定してください'}), 400
    normalized_items = []
    submitted_ids = set()
    for item in items:
        if not isinstance(item, dict):
            return ctx.jsonify({'status': 'error', 'message': 'items の各要素はオブジェクトで指定してください'}), 400
        try:
            db_id = int(item.get('id'))
        except (ValueError, TypeError):
            return ctx.jsonify({'status': 'error', 'message': '不正な fetish_id です'}), 400
        if 'is_new' in item and not isinstance(item['is_new'], bool):
            return ctx.jsonify({'status': 'error', 'message': 'is_new は真偽値で指定してください'}), 400
        if db_id in submitted_ids:
            return ctx.jsonify({'status': 'error', 'message': '同じ fetish_id は1回だけ指定してください'}), 400
        submitted_ids.add(db_id)
        normalized_items.append({'id': db_id, 'is_new': bool(item.get('is_new'))})
    replay_signature = sorted((item['id'], item['is_new']) for item in normalized_items)
    replay = ctx.session.get('last_finalize_added')
    if ctx.session.get('feedback_status') == 'done' and isinstance(replay, dict):
        stored_signature = [tuple(item) for item in replay.get('signature', [])]
        if stored_signature != replay_signature:
            return ctx.jsonify({'status': 'error', 'message': '処理済みの確定内容と一致しません'}), 409
        return ctx.jsonify(replay['response'])
    active_guess_error = _require_active_guess(ctx)
    if active_guess_error:
        return active_guess_error
    allowed_ids = _feedback_allowed_ids(ctx)
    if submitted_ids and not submitted_ids.issubset(allowed_ids):
        return ctx.jsonify({'status': 'error', 'message': '現在の診断候補と一致しません'}), 409
    owned_ids = ctx.parse_id_list(ctx.session.get('owned_added_fetish_ids', []))
    if any(item['is_new'] != (item['id'] in owned_ids) for item in normalized_items):
        return ctx.jsonify({'status': 'error', 'message': '訂正候補の新規作成状態と一致しません'}), 409
    if _learning_skipped(ctx):
        response_payload = {'status': 'done', 'learning_disabled': True}
        ctx.session['last_finalize_added'] = {'signature': replay_signature, 'response': response_payload}
        _finish_feedback(ctx)
        return ctx.jsonify(response_payload)
    answers = ctx.session.get('answers', {})
    feedback_outcome = ctx.session.get('pending_feedback_outcome', 'no')
    wrong_db_ids = list(ctx.session.get('wrong_db_ids', []))
    previously_negative = set(ctx.session.get('negative_learned_db_ids', []))
    near_miss_db_ids = set(ctx.session.get('near_miss_db_ids', []))
    if feedback_outcome == 'maybe' and not near_miss_db_ids:
        near_miss_db_ids = ctx.parse_id_list(ctx.session.get('pending_presented_ids', []))
    pending_correct_db_ids = ctx.parse_id_list(ctx.session.get('pending_correct_db_ids', []))
    correction_n = max(1, len(normalized_items))
    correction_factor = ctx.learn_factor(answers, correction_n)
    pending_positive_factor = ctx.learn_factor(answers, max(1, len(pending_correct_db_ids)))
    near_factor = ctx.learn_factor(answers, max(1, len(near_miss_db_ids)))
    correct_db_ids = set()
    positive_count = 0
    correction_count = 0
    near_count = 0
    negative_count = 0

    with getattr(ctx.engine, 'feedback_batch', nullcontext)():
        for db_id in pending_correct_db_ids:
            idx = ctx.engine.index_of(db_id)
            if idx is None:
                continue
            correct_db_ids.add(db_id)
            ctx.learn_positive(
                ctx.engine,
                answers,
                idx,
                strength_factor=pending_positive_factor * ctx.positive_feedback_factor(ctx.engine, idx),
            )
            ctx.engine.log_correct(db_id)
            positive_count += 1

        for item in normalized_items:
            db_id = item['id']
            is_new = item['is_new']
            idx = ctx.engine.index_of(db_id)
            if idx is None:
                continue
            correct_db_ids.add(db_id)
            ctx.engine.log_correction_selected(db_id)
            if is_new:
                ctx.engine.boost_learn_new(idx, answers)
            else:
                ctx.learn_positive(
                    ctx.engine,
                    answers,
                    idx,
                    strength_factor=correction_factor * ctx.positive_feedback_factor(ctx.engine, idx),
                )
            positive_count += 1
            correction_count += 1

        correct_idxs = [ctx.engine.index_of(db_id) for db_id in correct_db_ids]
        correct_idxs = [idx for idx in correct_idxs if idx is not None]
        for position, left in enumerate(correct_idxs):
            for right in correct_idxs[position + 1 :]:
                pair_factor = (
                    ctx.positive_feedback_factor(ctx.engine, left) + ctx.positive_feedback_factor(ctx.engine, right)
                ) / 2
                ctx.learn_cooccurrence(ctx.engine, answers, left, right, correction_factor * pair_factor * 0.3)

        for db_id in near_miss_db_ids:
            if db_id in correct_db_ids:
                continue
            idx = ctx.engine.index_of(db_id)
            if idx is None:
                continue
            ctx.learn_near_miss(
                ctx.engine,
                answers,
                idx,
                strength_factor=near_factor * ctx.near_miss_feedback_factor(ctx.engine, idx),
            )
            near_count += 1

        for db_id in wrong_db_ids:
            if db_id in correct_db_ids or db_id in previously_negative:
                continue
            idx = ctx.engine.index_of(db_id)
            if idx is None:
                continue
            ctx.engine.log_wrong(db_id)
            ctx.learn_negative(
                ctx.engine,
                answers,
                idx,
                strength_factor=ctx.negative_feedback_factor(ctx.engine, idx),
            )
            negative_count += 1

        if near_count or negative_count:
            ctx.record_guess_quality_feedback(False)

    target_count = positive_count + near_count + negative_count
    if target_count:
        kinds = [
            kind
            for kind, count in (('positive', positive_count), ('near_miss', near_count), ('negative', negative_count))
            if count
        ]
        _record_question_feedback_learning(
            ctx,
            answers,
            kinds[0] if len(kinds) == 1 else 'mixed',
            target_count,
        )
    response_payload = {
        'status': 'done',
        'atomic': True,
        'feedback_outcome': feedback_outcome,
        'correction_count': correction_count,
    }
    ctx.session['last_finalize_added'] = {'signature': replay_signature, 'response': response_payload}
    _finish_feedback(ctx, correction_count=correction_count)
    return ctx.jsonify(response_payload)


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
        share_id, payload = share_links.create_link(
            {
                'name': name,
                'probability': probability,
                'desc': desc,
                'title': share.result_title(probability),
                'rank': share.result_rarity(probability),
            },
            environ=ctx.environ,
        )
    except (OSError, RuntimeError, ValueError):
        return ctx.jsonify({'status': 'error', 'message': 'share link could not be created'}), 500
    return ctx.jsonify(
        {
            'status': 'ok',
            'share_id': share_id,
            'share_url': f'/r/{share_id}',
            'result': payload,
        }
    )


def share_event(ctx):
    limited = ctx.rate_limit('api_share_event', 180)
    if limited:
        return limited
    if ctx.learning_disabled():
        return ctx.jsonify({'status': 'ok', 'recorded': False, 'learning_disabled': True})
    data = ctx.request.get_json(silent=True) or {}
    event = ctx.record_share_event(
        data.get('event_name', ''),
        result_name=data.get('result_name', ''),
        channel=data.get('channel', ''),
        success=data.get('success') if 'success' in data else None,
        work_title=data.get('work_title', ''),
        work_id=data.get('work_id', ''),
        edition_id=data.get('edition_id', ''),
        page=data.get('page', ''),
    )
    return ctx.jsonify({'status': 'ok', 'recorded': bool(event)})


def gameplay_event(ctx):
    limited = ctx.rate_limit('api_gameplay_event', 240)
    if limited:
        return limited
    if ctx.learning_disabled():
        return ctx.jsonify({'status': 'ok', 'recorded': False, 'learning_disabled': True})
    data = ctx.request.get_json(silent=True) or {}
    event = ctx.record_gameplay_event(
        data.get('event_name', ''),
        source=data.get('source', ''),
        outcome=data.get('outcome', ''),
        result_id=data.get('result_id'),
        question_id=data.get('question_id'),
        answered_count=data.get('answered_count'),
        work_id=data.get('work_id', ''),
        edition_id=data.get('edition_id', ''),
    )
    if not event:
        return ctx.jsonify({'status': 'error', 'message': '不正な gameplay event です'}), 400
    if data.get('event_name') == 'draft_discarded':
        ctx.finalize_gameplay_summary('expired' if data.get('outcome') == 'expired' else 'discarded')
    return ctx.jsonify({'status': 'ok', 'recorded': True})


def dropoff(ctx):
    limited = ctx.rate_limit('api_dropoff', 240)
    if limited:
        return limited
    if not ctx.session.get('started'):
        return ctx.jsonify({'status': 'ignored', 'reason': 'not_started'})
    if ctx.session.get('dropoff_recorded'):
        return ctx.jsonify({'status': 'ignored', 'reason': 'already_finalized'})
    if ctx.session.get('completed'):
        ctx.finalize_gameplay_summary('completed')
        ctx.session['dropoff_recorded'] = True
        return ctx.jsonify({'status': 'ok', 'completed': True})
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
    ctx.update_gameplay_summary('progress', answered_count=answered_count)
    if not ctx.learning_disabled():
        ctx.engine.log_dropoff(answered_count)
        ctx.finalize_gameplay_summary('abandoned')
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

    @bp.route('/api/gameplay_event', methods=['POST'])
    def gameplay_event_route():
        return gameplay_event(ctx_factory())

    @bp.route('/api/share_event', methods=['POST'])
    def share_event_route():
        return share_event(ctx_factory())

    return bp
