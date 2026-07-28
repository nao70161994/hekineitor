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


def question_yes_balance_multiplier(row, *, min_answers=20, max_penalty=0.6):
    try:
        answered = int(row.get('answered') or 0)
        yes_rate = float(row.get('yes_rate') or 0)
    except (AttributeError, TypeError, ValueError):
        return 1.0
    if answered < int(min_answers or 0):
        return 1.0
    penalty = max(0.0, min(float(max_penalty or 0), 0.9))
    distance = min(abs(yes_rate - 50.0) / 50.0, 1.0)
    return 1.0 - penalty * distance


def _exclude_and_normalize(engine, probs, exclude_ids):
    excluded = {int(value) for value in (exclude_ids or ())}
    kept = [prob if engine.fetishes[index].get('id') not in excluded else 0.0 for index, prob in enumerate(probs)]
    total = sum(kept)
    return [prob / total for prob in kept] if total > 0 else probs


def best_question(
    engine,
    answers,
    asked,
    idk_streak=0,
    *,
    question_axes,
    focus_threshold_default,
    ucb_explore_c,
    focus_top_n,
    early_random_depth,
    early_random_top_k,
    axis_indirect_bonus,
    question_balance_stats=None,
    exclude_ids=None,
):
    probs = _exclude_and_normalize(engine, engine.posteriors(answers), exclude_ids)
    nf = len(engine.fetishes)
    asked_list = list(asked)

    focus_threshold = engine.config.get('focus_threshold', focus_threshold_default)
    ucb_c = engine.config.get('ucb_explore_c', ucb_explore_c)
    balance_min_answers = engine.config.get('question_yes_balance_min_answers', 20)
    balance_max_penalty = engine.config.get('question_yes_balance_max_penalty', 0.6)
    question_balance_stats = (
        engine._question_balance_stats()
        if question_balance_stats is None and hasattr(engine, "_question_balance_stats")
        else question_balance_stats
    ) or {}
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
        norm = math.sqrt(sum(value**2 for value in vector)) or 1e-9
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
            norm_q = math.sqrt(sum(value**2 for value in vector_q)) or 1e-9
            max_similarity = 0.0
            for vector_asked, norm_asked in question_vectors.values():
                similarity = sum(a * b for a, b in zip(vector_q, vector_asked)) / (norm_q * norm_asked)
                if similarity > max_similarity:
                    max_similarity = similarity
            score *= 1.0 - 0.4 * max_similarity
        ask_count = sum(engine.matrix['total'][f][q] for f in range(nf))
        score += ucb_c / math.sqrt(ask_count / max(nf, 1) + 1)
        axis_name = engine._question_axis(q)
        category = engine._question_category(q)
        weighted = score * axis_indirect_bonus.get(axis_name, 1.0)
        balance_row = question_balance_stats.get(q) if isinstance(question_balance_stats, dict) else None
        if balance_row:
            weighted *= question_yes_balance_multiplier(
                balance_row,
                min_answers=balance_min_answers,
                max_penalty=balance_max_penalty,
            )
        if engine.questions[q].get('early_penalty') and len(asked_list) < 5:
            weighted *= 0.35
        if category in recent_categories:
            weighted *= 0.72
        if len(asked_list) < 5 and category in {'relation', 'attachment'} and category in asked_category_set:
            weighted *= 0.50
        if (
            early_game
            and category in {'attribute', 'world', 'tone', 'value', 'aesthetic', 'role'}
            and category not in asked_category_set
        ):
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


def _fallback_best_question(engine, answers, asked, *, idk_streak=0, exclude_ids=None):
    if exclude_ids and hasattr(engine, "_best_question_with_exclusions"):
        return engine._best_question_with_exclusions(answers, asked, idk_streak=idk_streak, exclude_ids=exclude_ids)
    return engine.best_question(answers, asked, idk_streak=idk_streak)


def best_disambiguating_question(
    engine,
    answers,
    asked,
    candidate_count=3,
    idk_streak=0,
    *,
    exclude_ids=None,
    question_balance_stats=None,
):
    probs = _exclude_and_normalize(engine, engine.posteriors(answers), exclude_ids)
    nf = len(engine.fetishes)
    asked_ints = set()
    asked_list = []
    for q in asked:
        try:
            question_id = int(q)
            if question_id not in asked_ints:
                asked_ints.add(question_id)
                asked_list.append(question_id)
        except (ValueError, TypeError):
            pass

    ranked = sorted(range(nf), key=lambda i: probs[i], reverse=True)
    top = ranked[: max(2, min(candidate_count, nf))]
    if len(top) < 2:
        return _fallback_best_question(engine, answers, asked, idk_streak=idk_streak, exclude_ids=exclude_ids)

    top_total = sum(probs[f] for f in top) or 1e-9
    top_weights = {f: probs[f] / top_total for f in top}
    best_q, best_score = None, 0.0
    recent_categories = [engine._question_category(q) for q in asked_list[-3:]]
    recent_idk_axes = {engine._question_axis(q) for q in asked_list[-max(2, idk_streak) :] if answers.get(str(q)) == 0}
    vectors = {}
    for old_q in asked_list:
        vector = [engine._prob(fetish_idx, old_q) - 0.5 for fetish_idx in top]
        vectors[old_q] = (vector, math.sqrt(sum(value * value for value in vector)) or 1e-9)
    question_balance_stats = (
        engine._question_balance_stats()
        if question_balance_stats is None and hasattr(engine, "_question_balance_stats")
        else question_balance_stats
    ) or {}

    for q in range(len(engine.questions)):
        if q in asked_ints or q in engine.disabled_questions:
            continue
        p_yes = sum(top_weights[f] * engine._prob(f, q) for f in top)
        p_no = 1.0 - p_yes
        if p_yes < 0.01 or p_no < 0.01:
            continue

        separation = 0.0
        for pos, fa in enumerate(top):
            for fb in top[pos + 1 :]:
                pair_weight = top_weights[fa] * top_weights[fb]
                separation += pair_weight * abs(engine._prob(fa, q) - engine._prob(fb, q))
        balance = 1.0 - abs(0.5 - p_yes) * 2.0
        score = separation * (0.5 + 0.5 * balance)
        vector_q = [engine._prob(fetish_idx, q) - 0.5 for fetish_idx in top]
        norm_q = math.sqrt(sum(value * value for value in vector_q)) or 1e-9
        if vectors:
            similarity = max(
                0.0,
                max(
                    sum(left * right for left, right in zip(vector_q, old_vector)) / (norm_q * old_norm)
                    for old_vector, old_norm in vectors.values()
                ),
            )
            score *= 1.0 - 0.4 * similarity
        category = engine._question_category(q)
        if category in recent_categories:
            score *= 0.72
        if recent_categories.count(category) >= 2:
            score *= 0.48
        if idk_streak >= 2 and engine._question_axis(q) in recent_idk_axes:
            score *= 0.55
        balance_row = question_balance_stats.get(q) if isinstance(question_balance_stats, dict) else None
        if balance_row:
            score *= question_yes_balance_multiplier(balance_row)
        if score > best_score:
            best_score = score
            best_q = q

    if best_q is None:
        return _fallback_best_question(engine, answers, asked, idk_streak=idk_streak, exclude_ids=exclude_ids)
    return best_q
