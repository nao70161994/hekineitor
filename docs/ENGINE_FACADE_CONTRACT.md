# Engine Facade Contract

This document defines the public contract that must stay stable after `engine.py` was converted into an `engine/` package. The package conversion is an atomic compatibility step; public imports continue to resolve through the `engine` package facade.

## Public Module Contract

These imports must keep working until a dedicated migration PR updates every caller:

```python
import engine
from engine import Engine
from engine import PLAYER_FETISH_BASE_ID, FOCUS_THRESHOLD, FOCUS_TOP_N
from engine import UCB_EXPLORE_C, EARLY_RANDOM_DEPTH, EARLY_RANDOM_TOP_K
from engine import AXIS_INDIRECT_BONUS, PSEUDO
from engine import QUESTION_AXES, DOMAIN_PRIORS, FETISH_RELATIONS, FETISH_PRIOR_WEIGHTS
from engine import get_compound_works, list_compound_works, set_compound_works, delete_compound_works
from engine import parse_works_list
```

The module may delegate to helper modules, but callers must not be required to import those helpers directly.

## Engine-Owned State

`Engine` owns mutable runtime state and synchronization. These fields must remain initialized on `Engine()` with the same names and shapes:

- `questions`: list of question dictionaries loaded from `questions.json`.
- `fetishes`: list of fetish dictionaries loaded from JSON or DB.
- `matrix`: dictionary with `yes` and `total` 2D arrays.
- `config`: dictionary of numeric tuning values.
- `_lock`: re-entrant mutation lock for matrix/fetish writes.
- `_disc_cache`, `_disc_cache_time`: discrimination scaling cache.
- `_corr_cache`, `_corr_cache_time`: correlation cache.
- `_last_db_load`: DB matrix reload timestamp when DB mode is active.

Helper modules may receive `Engine` as a dependency, but they must not become the owner of these fields until the package facade is explicitly migrated.

## Stateful Orchestration That Stays On Engine

These methods coordinate state, locks, persistence side effects, or public API response shapes and should stay as facade/orchestration methods through the package migration:

- Construction and persistence setup: `__init__`, `_ensure_db`, `_load_fetishes_from_db`, `_load_from_db`, `_load_config`.
- Matrix and config persistence: `_save_async`, `_save_to_db`, `_import_to_db`, `set_config`, `import_matrix`. Engine keeps state assignment/save orchestration; local matrix shape/init/load helpers may live outside the facade.
- Stats and logs: `_increment_stat`, `_record_daily_stat`, `get_stats`, `get_stats_history`, `get_recent_fetish_ranking`, `get_fetish_history`, `get_quality_event_summary`, `log_guessed`, `log_correct`, `log_wrong`, `get_fetish_log`. Engine keeps public orchestration and local-file branches; DB SQL is delegated to `engine_db.py`.
- Mutation workflows: `add_fetish`, `edit_fetish`, `delete_fetish`, `merge_fetishes`, `promote_fetish`, `boost_learn_new`, `edit_question`, `toggle_question_disabled`.
- Runtime caches: `_reload_matrix_if_stale`, `_get_disc_scales`, `get_correlation_stats`, `detect_contradictions`.

## Helper-Owned Behavior

These behaviors are already safe to live outside `engine.py` as long as facade tests keep parity:

- Inference math: `engine_inference.py`.
- Question selection: `engine_question_selection.py`.
- Learning row updates: `engine_learning.py`.
- Large constants/data: `engine/constants.py`, `engine/data.py` with legacy top-level shims.
- Compound works helpers: `engine/compound_works.py` with a legacy top-level shim.
- Local JSON stats/flags/log helpers: `engine_stats.py`.
- Read-only reports: `engine_reporting.py`, `engine_admin_reports.py`.
- Correlation helpers: `engine_correlation.py`.
- DB schema/load/config/mutation/stats adapters: `engine_db.py`.
- Local matrix persistence shape/init/load helpers: `engine/persistence.py` with a legacy top-level shim.
- Memory-only mutation helpers: `engine_mutations.py`.

## Public Method Contract

The following public `Engine` methods are route/script contract. Their names, call signatures, and return shapes must remain stable unless a migration PR updates all callers and tests:

- `increment_play_count()` -> updates play count side effect.
- `get_stats()` -> `dict` with at least `learn_count` and `play_count`.
- `get_stats_history(days=30)` -> list/dict report shape used by admin routes.
- `get_recent_fetish_ranking(days=7, top_n=10)` -> list ranking report.
- `get_fetish_history(fetish_db_id, days=30)` -> history report for one fetish id.
- `get_quality_event_summary(days=30)` -> quality report summary.
- `toggle_question_disabled(q_id)` -> bool-like mutation result.
- `log_guessed(fetish_db_id)`, `log_correct(fetish_db_id)`, `log_wrong(fetish_db_id)` -> side effects only.
- `get_fetish_log()` -> `{fetish_id: {guessed, correct, wrong}}`.
- `set_config(key, value)` -> validates key, stores float value, raises `ValueError` for unknown keys.
- `get_top_questions_per_fetish(top_n=5)` -> report list.
- `posteriors(answers)` -> posterior probability list; order and values are behavior critical.
- `best_question(answers, asked, idk_streak=0)` -> question index or `None`; behavior critical.
- `best_disambiguating_question(answers, asked, candidate_count=3, idk_streak=0)` -> question index or `None`.
- `get_matrix_heatmap(n_fetishes=20, n_questions=20)` -> heatmap report.
- `get_learning_stats()`, `get_question_stats()`, `get_axis_stats()` -> admin report shapes.
- `fetish_similarity(id_a, id_b)` -> similarity report.
- `get_correlation_stats(top_n=30)` -> correlation report.
- `get_quality_report()` -> quality report dictionary.
- `top_guess(answers, n=1)` -> ranked guesses.
- `get_answer_contributions(answers, fetish_idx, top_n=3)` -> contribution list.
- `detect_contradictions(answers)` -> contradiction list.
- `learn(answers, fetish_idx, strength_factor=1.0)` -> matrix mutation side effects.
- `learn_cooccurrence(answers, idx_a, idx_b, factor=0.25)` -> co-occurrence matrix mutation side effects.
- `learn_near_miss(answers, fetish_idx, strength_factor=1.0)` -> near-miss matrix mutation side effects.
- `learn_negative(answers, fetish_idx, strength_factor=1.0)` -> negative learning matrix mutation side effects.
- `add_fetish(name, desc, answers)` -> `(array_idx, db_id)`.
- `boost_learn_new(fetish_idx, answers)` -> learning side effects.
- `index_of(db_id)` -> array index or `None`.
- `merge_fetishes(id_keep, id_remove, new_name=None, new_desc=None)` -> bool.
- `edit_question(q_idx, text)` -> bool.
- `validate_matrix_rows(matrix_rows)` -> validation report.
- `import_matrix(matrix_rows)` -> count of imported rows.
- `edit_fetish(fetish_id, name=None, desc=None, works=None)` -> bool.
- `delete_fetish(fetish_id)` -> bool.
- `promote_fetish(old_id)` -> new id or `None`.
- `capture_learned_priors()` -> snapshot side effect.
- `get_related(fetish_id)` -> related fetish ids/names.

## Package Conversion Rules

- Do not reintroduce a top-level `engine.py` beside the `engine/` package.
- The first package PR must keep `import engine` and `from engine import Engine` working.
- The package facade should re-export the same constants, data, helper functions, and `Engine` class.
- Any method body moved out of `Engine` must keep tests proving signature and representative behavior parity.
- Do not change inference ordering, question selection, learning deltas, DB schema, session keys, or localStorage keys during package conversion.
