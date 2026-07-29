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
        guessed = max(0, int(entry.get('guessed', 0) or 0))
        # Older logs may mix correction-screen selections into correct. Those
        # selections were not exposures, so clamp to the exposure population.
        correct = min(guessed, max(0, int(entry.get('correct', 0) or 0)))
        empirical = (correct + alpha) / (guessed + alpha * 2)
        static = static_weights.get(fetish_id, 1.0)
        trust = min(guessed / 20.0, 1.0)
        blended = static * (1 - trust) + empirical * trust
        weights[fetish_id] = max(blended, 0.1)
    return weights


def dynamic_prior_shadow_report(fetishes, log, static_weights, *, alpha=2.0):
    """Report legacy rows whose mixed populations inflated the prior."""
    current = dynamic_prior_weights(fetishes, log, static_weights, alpha=alpha)
    rows = []
    for fetish in fetishes:
        fetish_id = fetish['id']
        entry = log.get(fetish_id, {})
        guessed = max(0, int(entry.get('guessed', 0) or 0))
        correct = max(0, int(entry.get('correct', 0) or 0))
        if correct <= guessed:
            continue
        static = static_weights.get(fetish_id, 1.0)
        trust = min(guessed / 20.0, 1.0)
        legacy_empirical = (correct + alpha) / (guessed + alpha * 2)
        legacy = max(static * (1 - trust) + legacy_empirical * trust, 0.1)
        rows.append(
            {
                'fetish_id': fetish_id,
                'fetish_name': fetish.get('name', ''),
                'guessed': guessed,
                'correct': correct,
                'excess_correct': correct - guessed,
                'correction_selected': max(0, int(entry.get('correction_selected', 0) or 0)),
                'legacy_weight': legacy,
                'current_weight': current[fetish_id],
                'delta': current[fetish_id] - legacy,
            }
        )
    rows.sort(key=lambda row: (-row['excess_correct'], row['fetish_id']))
    return {
        'schema_version': 1,
        'mismatched_count': len(rows),
        'excess_correct_count': sum(row['excess_correct'] for row in rows),
        'rows': rows,
        'migration_policy': {
            'strategy': 'non_destructive_runtime_clamp',
            'irreversible_reclassification_performed': False,
            'reason': 'legacy correct events do not retain whether they came from exposure or correction selection',
        },
    }


def entropy(probs):
    return -sum(prob * math.log2(prob) for prob in probs if prob > 1e-10)
