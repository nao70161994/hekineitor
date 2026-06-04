def posteriors(engine, answers):
    return engine.posteriors(answers)


def top_guess(engine, answers, n=1):
    return engine.top_guess(answers, n=n)


def answer_contributions(engine, answers, fetish_idx, top_n=3):
    return engine.get_answer_contributions(answers, fetish_idx, top_n=top_n)


def compute_guess(ctx, answers):
    """Build diagnosis response without changing Engine state."""
    engine = ctx.engine
    probs = posteriors(engine, answers)
    exclude_ids = set(ctx.session.get('exclude_ids', []))
    ranked = sorted(range(len(probs)), key=lambda i: probs[i], reverse=True)
    adjust_result_ranking = getattr(ctx, 'adjust_result_ranking', None)
    if callable(adjust_result_ranking) and not exclude_ids:
        ranked = adjust_result_ranking(probs, ranked)
    if exclude_ids:
        ranked = [i for i in ranked if engine.fetishes[i]['id'] not in exclude_ids] + [
            i for i in ranked if engine.fetishes[i]['id'] in exclude_ids
        ]
    best_i = ranked[0]
    best_p = probs[best_i]
    best_f = engine.fetishes[best_i]
    best_db = best_f['id']

    compound_ratio = engine.config.get('compound_ratio', ctx.compound_ratio)
    triple_ratio = engine.config.get('triple_ratio', ctx.triple_ratio)
    compound = []
    compound_db_ids = set()
    if len(ranked) > 1 and probs[ranked[1]] >= best_p * compound_ratio:
        candidate = engine.fetishes[ranked[1]]
        compound.append({
            'fetish_id': candidate['id'],
            'fetish_name': candidate['name'],
            'probability': round(probs[ranked[1]] * 100, 1),
        })
        compound_db_ids.add(candidate['id'])
        if len(ranked) > 2 and probs[ranked[2]] >= best_p * triple_ratio:
            candidate = engine.fetishes[ranked[2]]
            compound.append({
                'fetish_id': candidate['id'],
                'fetish_name': candidate['name'],
                'probability': round(probs[ranked[2]] * 100, 1),
            })
            compound_db_ids.add(candidate['id'])

    threshold = max(best_p * ctx.profile_min_ratio, ctx.profile_min_prob)
    profile = []
    for fetish_index in ranked[1:]:
        fetish = engine.fetishes[fetish_index]
        if fetish['id'] == best_db or fetish['id'] in compound_db_ids:
            continue
        if probs[fetish_index] >= threshold:
            profile.append({
                'fetish_id': fetish['id'],
                'fetish_name': fetish['name'],
                'probability': round(probs[fetish_index] * 100, 1),
            })

    related_seen = {item['fetish_id'] for item in profile} | compound_db_ids | {best_db}
    related = []
    for source_db_id in [best_db] + list(compound_db_ids):
        for relation in engine.get_related(source_db_id):
            if relation['fetish_id'] not in related_seen:
                related.append(relation)
                related_seen.add(relation['fetish_id'])

    top_chart = []
    for fetish_index in ranked[:5]:
        fetish = engine.fetishes[fetish_index]
        top_chart.append({'fetish_name': fetish['name'], 'probability': round(probs[fetish_index] * 100, 1)})

    seen_titles = set()
    cross_works = []
    merged_works = []

    def add_work(work, target):
        title = ctx.work_title(work)
        if title and title not in seen_titles:
            seen_titles.add(title)
            target.append(work)

    if compound:
        for item in compound:
            for work in ctx.get_compound_works(best_db, item['fetish_id']):
                add_work(work, cross_works)
        compound_ids = [item['fetish_id'] for item in compound]
        for i in range(len(compound_ids)):
            for j in range(i + 1, len(compound_ids)):
                for work in ctx.get_compound_works(compound_ids[i], compound_ids[j]):
                    add_work(work, cross_works)

    for work in best_f.get('works', []):
        add_work(work, merged_works)
    for item in compound:
        candidate_index = engine.index_of(item['fetish_id'])
        if candidate_index is not None:
            for work in engine.fetishes[candidate_index].get('works', []):
                add_work(work, merged_works)

    return {
        'action': 'guess',
        'fetish_id': best_db,
        'fetish_name': best_f['name'],
        'fetish_desc': best_f['desc'],
        'probability': round(best_p * 100, 1),
        'compound': compound,
        'profile': profile,
        'related': related,
        'top_chart': top_chart,
        'reasons': engine.get_answer_contributions(answers, best_i),
        'works': merged_works,
        'cross_works': cross_works,
    }


def _record_result_contributions(ctx, result):
    recorder = getattr(ctx, 'record_question_event', None)
    if not recorder:
        return
    for rank, item in enumerate(result.get('reasons', [])[:5], start=1):
        question_id = item.get('q_id') if isinstance(item, dict) else None
        answer = None
        if isinstance(item, dict):
            answer = item.get('answer')
            if answer is None:
                answer = item.get('ans')
        recorder(
            'question_result_contribution',
            question_id=question_id,
            result_name=result.get('fetish_name', ''),
            result_rank=rank,
            answer=answer,
        )


def make_guess(ctx, answers):
    result = compute_guess(ctx.inference_context(), answers)
    if not ctx.session.get('completion_recorded'):
        ctx.engine.increment_play_count()
        ctx.session['completion_recorded'] = True
    ctx.session['last_guess_fetish_id'] = result['fetish_id']
    ctx.session['last_guess_compound_ids'] = [item['fetish_id'] for item in result.get('compound', [])]
    ctx.session.pop('feedback_status', None)
    ctx.session['completed'] = True
    ctx.mark_guess_quality(ctx.engine, ctx.session, answers, ctx.soft_max_questions)
    _record_result_contributions(ctx, result)
    record_result_exposure = getattr(ctx, 'record_result_exposure', None)
    if callable(record_result_exposure):
        record_result_exposure(
            result['fetish_id'],
            result.get('fetish_name', ''),
            result.get('probability'),
            rank=1,
        )
    guessed_ids = {result['fetish_id']} | {item['fetish_id'] for item in result.get('compound', [])}
    for fetish_id in guessed_ids:
        ctx.engine.log_guessed(fetish_id)
    return ctx.jsonify(result)
