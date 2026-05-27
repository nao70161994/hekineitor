import math
import random


HEAVY_RELATION_RESULT_NAMES = {'共依存', '激重感情', '共生関係', '執着'}
DIVERSIFYING_EARLY_CATEGORIES = {'attribute', 'world', 'aesthetic', 'value', 'role'}
HEAVY_RELATION_CATEGORIES = {'relation', 'attachment'}
HEAVY_EMOTION_CATEGORIES = {'relation', 'attachment', 'tone'}


def question_axis(question_id, question_axes):
    for name, question_range in question_axes:
        if question_id in question_range:
            return name
    return None


def question_category(engine, question_id):
    try:
        category = engine.questions[question_id].get('category')
    except (IndexError, AttributeError):
        category = None
    if category:
        return category
    axis = engine._question_axis(question_id)
    if axis == 'content':
        return 'role'
    if axis == 'personality':
        return 'value'
    if axis == 'abstract':
        return 'relation'
    return 'value'


def best_question(engine, answers, asked, idk_streak=0, *, question_axes, focus_threshold_default,
                  ucb_explore_c, focus_top_n, early_random_depth, early_random_top_k,
                  axis_indirect_bonus):
    probs = engine.posteriors(answers)
    nf = len(engine.fetishes)
    asked_list = list(asked)

    focus_threshold = engine.config.get('focus_threshold', focus_threshold_default)
    ucb_c = engine.config.get('ucb_explore_c', ucb_explore_c)
    top_p = max(probs)
    ranked_by_prob = sorted(range(nf), key=lambda i: probs[i], reverse=True)
    top_fetish = engine.fetishes[ranked_by_prob[0]] if ranked_by_prob else {}
    top_names = [engine.fetishes[index].get('name') for index in ranked_by_prob[:4]]
    heavy_relation_top = top_fetish.get('name') in HEAVY_RELATION_RESULT_NAMES
    heavy_relation_cluster = sum(name in HEAVY_RELATION_RESULT_NAMES for name in top_names) >= 2
    if top_p >= focus_threshold:
        ranked = sorted(range(nf), key=lambda i: probs[i], reverse=True)
        focus = set(ranked[:focus_top_n])
        weighted_probs = [probs[f] if f in focus else 0.0 for f in range(nf)]
        total = sum(weighted_probs)
        weighted_probs = [p / total for p in weighted_probs]
    else:
        weighted_probs = probs

    h0 = engine._entropy(weighted_probs)
    asked_axes = {engine._question_axis(q) for q in asked_list}
    asked_axes.discard(None)
    asked_categories = [engine._question_category(q) for q in asked_list]
    asked_category_set = {category for category in asked_categories if category}
    recent_categories = [category for category in asked_categories[-3:] if category]
    all_axis_names = {name for name, _ in question_axes}

    early_game = len(asked_list) < early_random_depth
    has_early_abstract = early_game and any(
        engine._question_axis(q) == 'abstract'
        for q in range(len(engine.questions))
        if q not in asked and q not in engine.disabled_questions
    )

    if has_early_abstract:
        axis_filter = {'abstract'}
    elif idk_streak >= 2:
        recent_idk_axes = []
        for asked_question in reversed(asked_list):
            answer = answers.get(str(asked_question))
            if answer == 0:
                axis = engine._question_axis(asked_question)
                if axis:
                    recent_idk_axes.append(axis)
                if len(recent_idk_axes) >= idk_streak:
                    break
            else:
                break
        if recent_idk_axes and len(set(recent_idk_axes)) == 1:
            axis_filter = all_axis_names - {recent_idk_axes[0]}
        else:
            axis_filter = {'abstract', 'personality'}
    elif len(asked_list) < 3 and (all_axis_names - asked_axes):
        axis_filter = all_axis_names - asked_axes
    else:
        axis_filter = None

    question_vectors = {}
    for asked_question in asked_list:
        vector = [engine._prob(f, asked_question) - 0.5 for f in range(nf)]
        norm = math.sqrt(sum(value ** 2 for value in vector)) or 1e-9
        question_vectors[asked_question] = (vector, norm)

    best_filtered_q, best_filtered_score = None, -1.0
    best_any_q, best_any_score = None, -1.0
    early_candidates = []

    for q in range(len(engine.questions)):
        if q in asked or q in engine.disabled_questions:
            continue
        p_yes = sum(weighted_probs[f] * engine._prob(f, q) for f in range(nf))
        p_no = 1.0 - p_yes
        if p_yes < 0.01 or p_no < 0.01:
            continue
        yes_probs = [weighted_probs[f] * engine._prob(f, q) for f in range(nf)]
        yes_total = sum(yes_probs)
        yes_probs = [value / yes_total for value in yes_probs]
        no_probs = [weighted_probs[f] * (1 - engine._prob(f, q)) for f in range(nf)]
        no_total = sum(no_probs)
        no_probs = [value / no_total for value in no_probs]
        score = h0 - (p_yes * engine._entropy(yes_probs) + p_no * engine._entropy(no_probs))
        if asked_list:
            vector_q = [engine._prob(f, q) - 0.5 for f in range(nf)]
            norm_q = math.sqrt(sum(value ** 2 for value in vector_q)) or 1e-9
            max_similarity = 0.0
            for vector_asked, norm_asked in question_vectors.values():
                similarity = sum(a * b for a, b in zip(vector_q, vector_asked)) / (norm_q * norm_asked)
                if similarity > max_similarity:
                    max_similarity = similarity
            score *= (1.0 - 0.4 * max_similarity)
        ask_count = sum(engine.matrix['total'][f][q] for f in range(nf))
        score += ucb_c / math.sqrt(ask_count / max(nf, 1) + 1)
        axis_name = engine._question_axis(q)
        category = engine._question_category(q)
        weighted = score * axis_indirect_bonus.get(axis_name, 1.0)
        if engine.questions[q].get('early_penalty') and len(asked_list) < 5:
            weighted *= 0.35
        if category in recent_categories:
            weighted *= 0.72
        if len(asked_list) < 5 and category in {'relation', 'attachment'} and category in asked_category_set:
            weighted *= 0.50
        if early_game and category in {'attribute', 'world', 'tone', 'value', 'aesthetic', 'role'} and category not in asked_category_set:
            weighted *= 1.08
        if (early_game and heavy_relation_top) or (len(asked_list) < 6 and heavy_relation_cluster):
            if category in DIVERSIFYING_EARLY_CATEGORIES and category not in asked_category_set:
                weighted *= 1.50
            elif category in HEAVY_EMOTION_CATEGORIES:
                weighted *= 0.42
        if len(asked_list) >= 2 and recent_categories.count(category) >= 2:
            weighted *= 0.48
        if axis_filter is None or axis_name in axis_filter:
            if weighted > best_filtered_score:
                best_filtered_score = weighted
                best_filtered_q = q
            if early_game:
                early_candidates.append((weighted, q))
        if weighted > best_any_score:
            best_any_score = weighted
            best_any_q = q

    if early_game and early_candidates:
        early_candidates.sort(reverse=True)
        pool = [q for _, q in early_candidates[:early_random_top_k]]
        return random.choice(pool)

    return best_filtered_q if best_filtered_q is not None else best_any_q


def best_disambiguating_question(engine, answers, asked, candidate_count=3, idk_streak=0):
    probs = engine.posteriors(answers)
    nf = len(engine.fetishes)
    asked_ints = set()
    for q in asked:
        try:
            asked_ints.add(int(q))
        except (ValueError, TypeError):
            pass

    ranked = sorted(range(nf), key=lambda i: probs[i], reverse=True)
    top = ranked[:max(2, min(candidate_count, nf))]
    if len(top) < 2:
        return engine.best_question(answers, asked_ints, idk_streak=idk_streak)

    top_total = sum(probs[f] for f in top) or 1e-9
    top_weights = {f: probs[f] / top_total for f in top}
    best_q, best_score = None, 0.0

    for q in range(len(engine.questions)):
        if q in asked_ints or q in engine.disabled_questions:
            continue
        p_yes = sum(top_weights[f] * engine._prob(f, q) for f in top)
        p_no = 1.0 - p_yes
        if p_yes < 0.01 or p_no < 0.01:
            continue

        separation = 0.0
        for pos, fa in enumerate(top):
            for fb in top[pos + 1:]:
                pair_weight = top_weights[fa] * top_weights[fb]
                separation += pair_weight * abs(engine._prob(fa, q) - engine._prob(fb, q))
        balance = 1.0 - abs(0.5 - p_yes) * 2.0
        score = separation * (0.5 + 0.5 * balance)
        if score > best_score:
            best_score = score
            best_q = q

    if best_q is None:
        return engine.best_question(answers, asked_ints, idk_streak=idk_streak)
    return best_q
