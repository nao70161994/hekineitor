import math


def probability(engine, fetish_idx, question_idx):
    yes = engine.matrix['yes'][fetish_idx][question_idx]
    total = engine.matrix['total'][fetish_idx][question_idx]
    if total == 0:
        return 0.5
    return max(min(yes / total, 0.999), 0.001)


def posteriors(engine, answers, *, fetish_prior_weights):
    engine._reload_matrix_if_stale()
    nf = len(engine.fetishes)
    nq = len(engine.questions)
    dyn = engine._get_dynamic_prior_weights()
    log_p = [
        math.log(
            max(
                dyn.get(
                    engine.fetishes[f]['id'],
                    fetish_prior_weights.get(engine.fetishes[f]['id'], 1.0),
                ),
                1e-9,
            )
        )
        for f in range(nf)
    ]
    for q_str, ans in answers.items():
        try:
            q = int(q_str)
        except (ValueError, TypeError):
            continue
        if not (0 <= q < nq):
            continue
        if ans == 0:
            for f in range(nf):
                p = engine._prob(f, q)
                log_p[f] -= 0.05 * abs(p - 0.5)
            continue
        weight = abs(ans)
        for f in range(nf):
            p = engine._prob(f, q)
            log_p[f] += weight * (math.log(p) if ans > 0 else math.log(1 - p))
    mx = max(log_p)
    probs = [math.exp(lp - mx) for lp in log_p]
    total = sum(probs)
    return [p / total for p in probs]


def top_guess(engine, answers, n=1):
    probs = engine.posteriors(answers)
    ranked = sorted(range(len(probs)), key=lambda i: probs[i], reverse=True)
    top = ranked[:n]
    if n == 1:
        return top[0], probs[top[0]]
    return [(fetish_idx, probs[fetish_idx]) for fetish_idx in top]


def contrastive_answer_contributions(engine, answers, winner_idx, runner_idx, top_n=3):
    rows = []
    for question_key, raw_answer in answers.items():
        try:
            question_id = int(question_key)
            answer = float(raw_answer)
        except (TypeError, ValueError):
            continue
        if answer == 0 or not (0 <= question_id < len(engine.questions)):
            continue
        winner_probability = engine._prob(winner_idx, question_id)
        runner_probability = engine._prob(runner_idx, question_id)
        if answer < 0:
            winner_probability, runner_probability = 1 - winner_probability, 1 - runner_probability
        advantage = abs(answer) * (math.log(max(winner_probability, 0.001)) - math.log(max(runner_probability, 0.001)))
        if advantage > 0:
            rows.append(
                {
                    'q_id': question_id,
                    'text': engine.questions[question_id]['text'],
                    'ans': answer,
                    'advantage': round(advantage, 4),
                }
            )
    rows.sort(key=lambda row: row['advantage'], reverse=True)
    return rows[:top_n]


def answer_contributions(engine, answers, fetish_idx, top_n=3):
    nq = len(engine.questions)
    contribs = []
    for q_str, ans in answers.items():
        try:
            q = int(q_str)
        except (ValueError, TypeError):
            continue
        if ans == 0 or not (0 <= q < nq):
            continue
        p = engine._prob(fetish_idx, q)
        weight = abs(ans)
        log_c = weight * (math.log(max(p, 0.001)) if ans > 0 else math.log(max(1 - p, 0.001)))
        contribs.append({'q_id': q, 'text': engine.questions[q]['text'], 'ans': ans, 'contrib': log_c})
    contribs.sort(key=lambda item: item['contrib'], reverse=True)
    return [{'q_id': row['q_id'], 'text': row['text'], 'ans': row['ans']} for row in contribs[:top_n]]
