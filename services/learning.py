import math
import os

from services import result_exposure


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


def make_learn_factor(engine, posteriors_fn, default_guess_threshold):
    def _learn_factor(answers, total_n=1):
        threshold = engine.config.get('guess_threshold', default_guess_threshold)
        return learn_factor(engine, posteriors_fn, answers, threshold, total_n)

    return _learn_factor


BROAD_RESULT_NAMES = {'共依存', '激重感情', '共生関係', '執着'}
POSITIVE_SCALE = 0.7
BROAD_RESULT_POSITIVE_SCALE = 0.45
NEGATIVE_SCALE = 1.3
BROAD_RESULT_NEGATIVE_SCALE = 1.7
NEAR_MISS_SCALE = 1.6
BROAD_NEAR_MISS_SCALE = 1.15
EXPOSURE_POSITIVE_MIN_SCALE = 0.2
EXPOSURE_NEGATIVE_MAX_SCALE = 2.5


def _fetish_name(engine, fetish_idx):
    try:
        return engine.fetishes[fetish_idx].get('name', '')
    except (IndexError, AttributeError, TypeError):
        return ''


def _fetish_id(engine, fetish_idx):
    try:
        return engine.fetishes[fetish_idx].get('id')
    except (IndexError, AttributeError, TypeError):
        return None


def _load_exposure_factors(engine, environ=None):
    try:
        return result_exposure.exposure_factors(engine.fetishes, environ=environ or os.environ)
    except Exception:
        return {}


def _exposure_feedback_scale(engine, fetish_idx, factors=None):
    fetish_id = _fetish_id(engine, fetish_idx)
    if fetish_id is None:
        return 1.0
    try:
        if factors is None:
            factors = _load_exposure_factors(engine)
        factor = float(factors.get(fetish_id, 1.0))
    except Exception:
        return 1.0
    if not math.isfinite(factor) or factor <= 0:
        return 1.0
    return factor


def _positive_exposure_feedback_scale(engine, fetish_idx, factors=None):
    factor = _exposure_feedback_scale(engine, fetish_idx, factors=factors)
    return max(EXPOSURE_POSITIVE_MIN_SCALE, min(1.0, factor))


def _negative_exposure_feedback_scale(engine, fetish_idx, factors=None):
    factor = _exposure_feedback_scale(engine, fetish_idx, factors=factors)
    return max(1.0, min(EXPOSURE_NEGATIVE_MAX_SCALE, 1.0 / factor))


def positive_feedback_factor(engine, fetish_idx, *, exposure_factors=None):
    base = BROAD_RESULT_POSITIVE_SCALE if _fetish_name(engine, fetish_idx) in BROAD_RESULT_NAMES else POSITIVE_SCALE
    return base * _positive_exposure_feedback_scale(engine, fetish_idx, factors=exposure_factors)


def negative_feedback_factor(engine, fetish_idx, *, exposure_factors=None):
    base = BROAD_RESULT_NEGATIVE_SCALE if _fetish_name(engine, fetish_idx) in BROAD_RESULT_NAMES else NEGATIVE_SCALE
    return base * _negative_exposure_feedback_scale(engine, fetish_idx, factors=exposure_factors)


def make_feedback_factor_provider(engine, environ=None):
    exposure_factors_cache = None

    def factors():
        nonlocal exposure_factors_cache
        if exposure_factors_cache is None:
            exposure_factors_cache = _load_exposure_factors(engine, environ=environ)
        return exposure_factors_cache

    return {
        'positive': lambda _engine, fetish_idx: positive_feedback_factor(
            _engine, fetish_idx, exposure_factors=factors()
        ),
        'negative': lambda _engine, fetish_idx: negative_feedback_factor(
            _engine, fetish_idx, exposure_factors=factors()
        ),
    }


def near_miss_feedback_factor(engine, fetish_idx):
    return BROAD_NEAR_MISS_SCALE if _fetish_name(engine, fetish_idx) in BROAD_RESULT_NAMES else NEAR_MISS_SCALE
