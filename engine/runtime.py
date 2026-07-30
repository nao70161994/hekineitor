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


def _blended_prior_weight(static, guessed, correct, *, alpha=2.0, clamp_correct=True):
    guessed = max(0, int(guessed or 0))
    correct = max(0, int(correct or 0))
    if clamp_correct:
        correct = min(guessed, correct)
    empirical = (correct + alpha) / (guessed + alpha * 2)
    trust = min(guessed / 20.0, 1.0)
    return max(static * (1 - trust) + empirical * trust, 0.1)


def dynamic_prior_weights(fetishes, log, static_weights, *, alpha=2.0):
    """Use only provenance-safe exposure counters for feedback-derived priors."""
    weights = {}
    for fetish in fetishes:
        fetish_id = fetish['id']
        entry = log.get(fetish_id, {})
        weights[fetish_id] = _blended_prior_weight(
            static_weights.get(fetish_id, 1.0),
            entry.get('exposure_guessed', 0),
            entry.get('exposure_correct', 0),
            alpha=alpha,
        )
    return weights


def dynamic_prior_shadow_report(fetishes, log, static_weights, *, alpha=2.0):
    """Compare isolated priors with both historical legacy calculations."""
    current = dynamic_prior_weights(fetishes, log, static_weights, alpha=alpha)
    rows = []
    for fetish in fetishes:
        fetish_id = fetish['id']
        entry = log.get(fetish_id, {})
        guessed = max(0, int(entry.get('guessed', 0) or 0))
        correct = max(0, int(entry.get('correct', 0) or 0))
        exposure_guessed = max(0, int(entry.get('exposure_guessed', 0) or 0))
        exposure_correct = max(0, int(entry.get('exposure_correct', 0) or 0))
        correction_selected = max(0, int(entry.get('correction_selected', 0) or 0))
        if not any((guessed, correct, exposure_guessed, exposure_correct, correction_selected)):
            continue
        static = static_weights.get(fetish_id, 1.0)
        legacy_unclamped = _blended_prior_weight(static, guessed, correct, alpha=alpha, clamp_correct=False)
        legacy_clamped = _blended_prior_weight(static, guessed, correct, alpha=alpha)
        current_weight = current[fetish_id]
        rows.append(
            {
                'fetish_id': fetish_id,
                'fetish_name': fetish.get('name', ''),
                'guessed': guessed,
                'correct': correct,
                'excess_correct': max(0, correct - guessed),
                'correction_selected': correction_selected,
                'exposure_guessed': exposure_guessed,
                'exposure_correct': exposure_correct,
                'legacy_weight': legacy_unclamped,
                'legacy_unclamped_weight': legacy_unclamped,
                'legacy_clamped_weight': legacy_clamped,
                'current_weight': current_weight,
                'delta': current_weight - legacy_unclamped,
                'delta_from_legacy_clamp': current_weight - legacy_clamped,
            }
        )
    rows.sort(key=lambda row: (-row['excess_correct'], row['fetish_id']))
    return {
        'schema_version': 2,
        'mismatched_count': sum(row['correct'] > row['guessed'] for row in rows),
        'excess_correct_count': sum(row['excess_correct'] for row in rows),
        'legacy_row_count': sum(bool(row['guessed'] or row['correct']) for row in rows),
        'exposure_guessed_count': sum(row['exposure_guessed'] for row in rows),
        'exposure_correct_count': sum(row['exposure_correct'] for row in rows),
        'rows': rows,
        'migration_policy': {
            'strategy': 'non_destructive_exposure_counter_isolation',
            'irreversible_reclassification_performed': False,
            'reason': (
                'legacy event provenance is unknown; old counters remain unchanged and isolated exposure counters '
                'start at zero'
            ),
        },
    }


def entropy(probs):
    return -sum(prob * math.log2(prob) for prob in probs if prob > 1e-10)
