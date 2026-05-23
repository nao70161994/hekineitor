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
        math.log(max(dyn.get(
            engine.fetishes[f]['id'],
            fetish_prior_weights.get(engine.fetishes[f]['id'], 1.0),
        ), 1e-9))
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
