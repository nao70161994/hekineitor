import math


def correlation_stats(engine, top_n=30, *, now, ttl):
    if engine._corr_cache and now - engine._corr_cache_time < ttl:
        return engine._corr_cache[:top_n]
    nf = len(engine.fetishes)
    nq = len(engine.questions)
    vectors = []
    for question_idx in range(nq):
        vector = [engine._prob(fetish_idx, question_idx) - 0.5 for fetish_idx in range(nf)]
        norm = math.sqrt(sum(value * value for value in vector)) or 1e-9
        vectors.append((vector, norm))

    pairs = []
    for first_idx in range(nq):
        for second_idx in range(first_idx + 1, nq):
            first_vector, first_norm = vectors[first_idx]
            second_vector, second_norm = vectors[second_idx]
            cosine = sum(a * b for a, b in zip(first_vector, second_vector)) / (first_norm * second_norm)
            pairs.append(
                {
                    'q1_id': first_idx,
                    'q1_text': engine.questions[first_idx]['text'],
                    'q2_id': second_idx,
                    'q2_text': engine.questions[second_idx]['text'],
                    'cos': round(cosine, 3),
                }
            )
    pairs.sort(key=lambda item: -abs(item['cos']))
    engine._corr_cache = pairs
    engine._corr_cache_time = now
    return pairs[:top_n]


def detect_contradictions(engine, answers, *, top_n=60, threshold=0.75, limit=2):
    nq = len(engine.questions)
    answered = {}
    for question_key, answer in answers.items():
        try:
            question_idx = int(question_key)
        except (ValueError, TypeError):
            continue
        if answer != 0 and 0 <= question_idx < nq:
            answered[question_idx] = answer

    result = []
    for pair in engine.get_correlation_stats(top_n=top_n):
        if abs(pair['cos']) < threshold:
            break
        first_idx = pair['q1_id']
        second_idx = pair['q2_id']
        if first_idx in answered and second_idx in answered:
            first_answer = answered[first_idx]
            second_answer = answered[second_idx]
            if pair['cos'] > threshold and first_answer * second_answer < 0:
                result.append(
                    {
                        'q1': engine.questions[first_idx]['text'],
                        'a1': first_answer,
                        'q2': engine.questions[second_idx]['text'],
                        'a2': second_answer,
                    }
                )
                if len(result) >= limit:
                    break
    return result
