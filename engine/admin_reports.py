import math


def matrix_heatmap(engine, n_fetishes=20, n_questions=20):
    nf = len(engine.fetishes)
    nq = len(engine.questions)
    n_fetishes = min(n_fetishes, nf)
    n_questions = min(n_questions, nq)
    weights = [sum(engine.matrix['total'][fi]) for fi in range(nf)]
    top_fi = sorted(range(nf), key=lambda i: -weights[i])[:n_fetishes]
    discs = [
        sum(abs(engine._prob(f, q) - 0.5) for f in range(nf)) / max(nf, 1)
        for q in range(nq)
    ]
    top_qi = sorted(sorted(range(nq), key=lambda q: -discs[q])[:n_questions])
    rows = [
        {
            'name': engine.fetishes[fi]['name'][:12],
            'id': engine.fetishes[fi]['id'],
            'cells': [round(engine._prob(fi, qi), 2) for qi in top_qi],
        }
        for fi in top_fi
    ]
    q_labels = [f'Q{qi}' for qi in top_qi]
    q_texts = [engine.questions[qi]['text'][:18] for qi in top_qi]
    return {'rows': rows, 'q_labels': q_labels, 'q_texts': q_texts}


def learning_stats(engine, *, domain_priors, pseudo):
    nq = len(engine.questions)
    prior_qs = {}
    for fetish_idx, question_idx, _probability in domain_priors:
        prior_qs.setdefault(fetish_idx, set()).add(question_idx)
    stats = []
    for fetish_idx, fetish in enumerate(engine.fetishes):
        n_prior = len(prior_qs.get(fetish_idx, set()))
        baseline = n_prior * float(pseudo) + (nq - n_prior) * 4.0
        data_weight = sum(engine.matrix['total'][fetish_idx]) - baseline
        stats.append({
            'id': fetish['id'],
            'index': fetish_idx,
            'name': fetish['name'],
            'data_weight': round(data_weight, 1),
        })
    return sorted(stats, key=lambda item: item['data_weight'])


def question_stats(engine):
    nf = len(engine.fetishes)
    result = []
    for question_idx, question in enumerate(engine.questions):
        probs = [engine._prob(fetish_idx, question_idx) for fetish_idx in range(nf)]
        disc = sum(abs(probability - 0.5) for probability in probs) / nf
        ask_count = sum(engine.matrix['total'][fetish_idx][question_idx] for fetish_idx in range(nf))
        result.append({
            'id': question_idx,
            'text': question['text'],
            'category': question.get('category') or 'unknown',
            'axis': question.get('axis') or '',
            'disc': round(disc, 3),
            'disabled': question_idx in engine.disabled_questions,
            'ask_count': round(ask_count, 1),
            'variants_count': len(question.get('variants', [])),
        })
    return sorted(result, key=lambda item: item['disc'])


def axis_stats(engine, *, question_axes):
    questions = question_stats(engine)
    disc_map = {row['id']: row['disc'] for row in questions}
    disabled_map = {row['id']: row['disabled'] for row in questions}
    merged = {}
    for axis_name, axis_range in question_axes:
        if axis_name not in merged:
            merged[axis_name] = {'name': axis_name, 'ids': []}
        for question_idx in axis_range:
            if question_idx < len(engine.questions):
                merged[axis_name]['ids'].append(question_idx)
    result = []
    for axis_name, info in merged.items():
        ids = info['ids']
        if not ids:
            continue
        avg_disc = round(sum(disc_map.get(question_idx, 0) for question_idx in ids) / len(ids), 3)
        disabled_count = sum(1 for question_idx in ids if disabled_map.get(question_idx, False))
        result.append({
            'name': axis_name,
            'count': len(ids),
            'avg_disc': avg_disc,
            'disabled': disabled_count,
        })
    return result


def fetish_similarity(engine, id_a, id_b):
    idx_a = engine.index_of(id_a)
    idx_b = engine.index_of(id_b)
    if idx_a is None or idx_b is None:
        return None
    nq = len(engine.questions)
    vector_a = [engine._prob(idx_a, question_idx) - 0.5 for question_idx in range(nq)]
    vector_b = [engine._prob(idx_b, question_idx) - 0.5 for question_idx in range(nq)]
    dot = sum(a * b for a, b in zip(vector_a, vector_b))
    norm_a = math.sqrt(sum(value * value for value in vector_a))
    norm_b = math.sqrt(sum(value * value for value in vector_b))
    cosine = 0.0 if norm_a < 1e-9 or norm_b < 1e-9 else round(dot / (norm_a * norm_b), 3)
    diffs = sorted(range(nq), key=lambda q: abs(vector_a[q] - vector_b[q]), reverse=True)
    top_diff = [
        {
            'q_id': question_idx,
            'text': engine.questions[question_idx]['text'],
            'p_a': round(engine._prob(idx_a, question_idx), 3),
            'p_b': round(engine._prob(idx_b, question_idx), 3),
        }
        for question_idx in diffs[:5]
    ]
    return {
        'cosine': cosine,
        'name_a': engine.fetishes[idx_a]['name'],
        'name_b': engine.fetishes[idx_b]['name'],
        'top_diff': top_diff,
    }
