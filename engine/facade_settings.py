"""Settings and runtime-cache orchestration for the engine facade."""

import copy
import math
from collections.abc import Callable, Mapping
from typing import Any

from . import db as engine_db
from . import runtime as engine_runtime
from . import stats as engine_stats


def load_config(
    owner: Any,
    *,
    use_db: Callable[[], bool],
    get_conn: Callable[[], Any],
    put_conn: Callable[[Any], None],
    config_path: str,
) -> dict[str, float]:
    """Load persisted inference settings through the selected backend."""
    return engine_db.load_config(
        owner._CONFIG_DEFAULTS,
        use_db=use_db,
        get_conn=get_conn,
        put_conn=put_conn,
        config_path=config_path,
        read_json=engine_stats.read_json_path,
    )


def set_config(
    owner: Any,
    key: str,
    value: Any,
    *,
    use_db: Callable[[], bool],
    get_conn: Callable[[], Any],
    put_conn: Callable[[Any], None],
    config_path: str,
    file_lock: Callable[..., Any],
    monotonic: Callable[[], float],
) -> None:
    """Validate, persist, and publish one inference setting."""
    if key not in owner._CONFIG_DEFAULTS:
        raise ValueError(f'未知のパラメータ: {key}')
    fval = float(value)
    if not math.isfinite(fval):
        raise ValueError(f'不正なパラメータ値: {key}')
    min_value, max_value = owner._CONFIG_RANGES[key]
    if fval < min_value or fval > max_value:
        raise ValueError(f'{key} は {min_value}〜{max_value} の範囲で指定してください')
    engine_db.save_config_value(
        key,
        fval,
        use_db=use_db,
        get_conn=get_conn,
        put_conn=put_conn,
        config_path=config_path,
        read_json=engine_stats.read_json_path,
        atomic_write=owner._atomic_write,
        file_lock=file_lock,
    )
    with owner._lock:
        owner.config[key] = fval
        owner._settings_config_snapshot = copy.deepcopy(owner.config)
        owner._settings_last_loaded = monotonic()


def disc_scales(owner: Any, *, monotonic: Callable[[], float]) -> list[float]:
    """Return cached question discrimination scales, rebuilding after TTL."""
    now = monotonic()
    if owner._disc_cache and now - owner._disc_cache_time < owner._DISC_CACHE_TTL:
        return owner._disc_cache
    mean_question_indexes = [
        index for index, question in enumerate(owner.questions) if not question.get('learning_scale_neutral')
    ]
    scales = engine_runtime.disc_scales(
        len(owner.fetishes),
        len(owner.questions),
        probability=owner._prob,
        mean_question_indexes=mean_question_indexes,
    )
    owner._disc_cache = scales
    owner._disc_cache_time = now
    return scales


def reload_settings_if_stale(
    owner: Any,
    *,
    force: bool,
    acquire_process_lock: Callable[[], None],
    reload_interval: float,
    monotonic: Callable[[], float],
) -> None:
    """Refresh mutable settings while preserving intentional local overrides."""
    acquire_process_lock()
    now = monotonic()
    if not force and now - owner._settings_last_loaded < reload_interval:
        return
    with owner._lock:
        if not force and monotonic() - owner._settings_last_loaded < reload_interval:
            return
        try:
            disabled_questions = owner._load_disabled_questions()
            config = owner._load_config()
        except Exception:
            owner._settings_last_loaded = monotonic()
            return
        owner.disabled_questions = disabled_questions
        # Preserve an intentional in-process override until its owner restores
        # the last persisted snapshot.
        if owner.config == owner._settings_config_snapshot:
            owner.config = config
            owner._settings_config_snapshot = copy.deepcopy(config)
        owner._settings_last_loaded = monotonic()


def dynamic_prior_weights(
    owner: Any,
    *,
    monotonic: Callable[[], float],
    refresh_interval: float,
    base_weights: Mapping[int, float],
) -> dict[int, float]:
    """Return cached feedback-derived prior weights, refreshing after TTL."""
    now = monotonic()
    if now - owner._dynamic_prior_time < refresh_interval:
        return owner._dynamic_prior_cache
    log = owner.get_fetish_log()
    if not log:
        owner._dynamic_prior_time = now
        return owner._dynamic_prior_cache
    weights = engine_runtime.dynamic_prior_weights(owner.fetishes, log, base_weights)
    owner._dynamic_prior_cache = weights
    owner._dynamic_prior_time = now
    return weights
