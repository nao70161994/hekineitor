from collections import Counter

from services.result_exposure import HEAVY_RESULT_NAMES


def _compact_question(row):
    return {
        'question_id': row.get('question_id'),
        'question_text': row.get('question_text', ''),
        'category': row.get('category', ''),
        'shown': int(row.get('shown', 0) or 0),
        'answered': int(row.get('answered', 0) or 0),
        'yes_rate': float(row.get('yes_rate', 0) or 0),
        'no_rate': float(row.get('no_rate', 0) or 0),
        'dropoff_rate': float(row.get('dropoff_rate', 0) or 0),
        'contribution': int(row.get('contribution', 0) or 0),
        'top_results': row.get('top_results', [])[:3],
    }


def _top(rows, key, *, limit):
    return [_compact_question(row) for row in sorted(rows, key=key)[:limit]]


def _heavy_contribution_count(row):
    total = 0
    for item in row.get('top_results', []):
        if item.get('result_name') in HEAVY_RESULT_NAMES:
            total += int(item.get('count', 0) or 0)
    return total


def result_diversity_candidate(exposure_events):
    counts = Counter()
    for event in exposure_events or []:
        try:
            if int(event.get('rank') or 1) != 1:
                continue
        except (TypeError, ValueError):
            continue
        name = str(event.get('fetish_name') or '').strip()
        if name:
            counts[name] += 1
    total = sum(counts.values())
    if total < 30 or not counts:
        return {'status': 'insufficient_data', 'sample_count': total, 'top_share': 0, 'top_results': []}
    top = [{'result_name': name, 'count': count, 'share': round(count / total * 100, 1)} for name, count in counts.most_common(5)]
    top_share = top[0]['share'] if top else 0
    status = 'needs_review' if top_share >= 60 else 'ok'
    return {'status': status, 'sample_count': total, 'top_share': top_share, 'top_results': top}


def build_candidates(question_report, *, exposure_events=None, min_answers=5, limit=5):
    questions = list(question_report.get('questions', []))
    answered_rows = [row for row in questions if int(row.get('answered', 0) or 0) >= min_answers]
    shown_rows = [row for row in questions if int(row.get('shown', 0) or 0) >= min_answers]
    heavy_rows = [row for row in questions if _heavy_contribution_count(row) > 0]

    return {
        'yes_rate_high': _top(
            [row for row in answered_rows if float(row.get('yes_rate', 0) or 0) > 90],
            lambda row: (-float(row.get('yes_rate', 0) or 0), -int(row.get('answered', 0) or 0), row.get('question_id', 0)),
            limit=limit,
        ),
        'yes_rate_low': _top(
            [row for row in answered_rows if float(row.get('yes_rate', 0) or 0) < 10],
            lambda row: (float(row.get('yes_rate', 0) or 0), -int(row.get('answered', 0) or 0), row.get('question_id', 0)),
            limit=limit,
        ),
        'dropoff_top': _top(
            shown_rows,
            lambda row: (-float(row.get('dropoff_rate', 0) or 0), -int(row.get('dropoff', 0) or 0), row.get('question_id', 0)),
            limit=limit,
        ),
        'heavy_result_contributors': _top(
            heavy_rows,
            lambda row: (-_heavy_contribution_count(row), -int(row.get('contribution', 0) or 0), row.get('question_id', 0)),
            limit=limit,
        ),
        'result_diversity': result_diversity_candidate(exposure_events or []),
    }
