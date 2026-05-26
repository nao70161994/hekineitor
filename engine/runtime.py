import math


def disc_scales(fetish_count, question_count, *, probability, mean_question_indexes=None):
    discs = [
        sum(abs(probability(fetish_idx, question_idx) - 0.5) for fetish_idx in range(fetish_count))
        / max(fetish_count, 1)
        for question_idx in range(question_count)
    ]
    if mean_question_indexes is None:
        mean_discs = discs
    else:
        mean_discs = [discs[index] for index in mean_question_indexes if 0 <= index < len(discs)]
    mean_disc = sum(mean_discs) / max(len(mean_discs), 1) or 1e-9
    return [max(0.5, min(2.0, disc / mean_disc)) for disc in discs]


def dynamic_prior_weights(fetishes, log, static_weights, *, alpha=2.0):
    weights = {}
    for fetish in fetishes:
        fetish_id = fetish['id']
        entry = log.get(fetish_id, {})
        correct = entry.get('correct', 0)
        guessed = entry.get('guessed', 0)
        empirical = (correct + alpha) / (guessed + alpha * 2)
        static = static_weights.get(fetish_id, 1.0)
        trust = min(guessed / 20.0, 1.0)
        blended = static * (1 - trust) + empirical * trust
        weights[fetish_id] = max(blended, 0.1)
    return weights


def entropy(probs):
    return -sum(prob * math.log2(prob) for prob in probs if prob > 1e-10)
