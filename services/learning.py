import math


def learn_positive(engine, answers, fetish_idx, *, strength_factor=1.0):
    return engine.learn(answers, fetish_idx, strength_factor=strength_factor)


def learn_cooccurrence(engine, answers, idx_a, idx_b, factor=0.25):
    return engine.learn_cooccurrence(answers, idx_a, idx_b, factor)


def learn_near_miss(engine, answers, fetish_idx, *, strength_factor=1.0):
    return engine.learn_near_miss(answers, fetish_idx, strength_factor=strength_factor)


def learn_negative(engine, answers, fetish_idx, *, strength_factor=1.0):
    return engine.learn_negative(answers, fetish_idx, strength_factor=strength_factor)



def learn_factor(engine, posteriors_fn, answers, guess_threshold, total_n=1):
    """確信度スケーリング x sqrt(n) 分散。"""
    probs = posteriors_fn(engine, answers)
    top_p = max(probs) if probs else guess_threshold
    if top_p >= guess_threshold:
        conf = max(0.5, 1.0 - 0.5 * (top_p - guess_threshold) / max(1.0 - guess_threshold, 1e-9))
    else:
        conf = min(2.0, guess_threshold / max(top_p, 0.1))
    n_scale = 1.0 / math.sqrt(max(total_n, 1))
    return max(0.3, min(2.0, conf * n_scale))
