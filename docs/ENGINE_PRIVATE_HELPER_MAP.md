# Engine Private Helper Map

This map classifies the remaining private helpers in `engine.py` before any `engine/` package conversion. It is intentionally conservative: helpers that coordinate locks, state assignment, persistence side effects, or cache invalidation stay on the `Engine` facade until a dedicated migration PR proves parity.

## Keep On Engine For Now

- `__init__`: owns state initialization order and DB/local branch selection.
- `_save_async`: chooses DB thread vs local file write and preserves non-blocking save behavior; covered by facade contract tests.
- `_save_matrix_file`: compatibility wrapper; Engine still creates a locked snapshot, file write arguments live in `engine_persistence.py`.
- `_save_fetishes_file`: compatibility wrapper; file write arguments live in `engine_persistence.py`.
- `_seed_db`: compatibility wrapper for DB seed insert; row building/write lives in `engine_db.py`.
- `_increment_stat`, `_record_daily_stat`: public stats workflows delegate DB/local details but keep route-facing side effects grouped.
- `_increment_learn_count`, `increment_play_count`: public counters plus daily stats.
- `_load_disabled_questions`, `_save_disabled_questions`: branch between DB and local flag persistence.
- `_increment_fetish_log`: validates column names and branches between DB and local log persistence.
- `_save_to_db`, `_import_to_db`: DB matrix writes need current facade patch points and psycopg compatibility.
- `_get_disc_scales`, `_get_dynamic_prior_weights`: Engine owns cache timing/state while pure calculations live in `engine_runtime.py`. `_reload_matrix_if_stale` stays on Engine and is covered by TTL/timestamp facade contract tests.
- `_prob`, `_question_axis`: tiny helpers used in hot paths; move only if package facade is already in place. `_entropy` remains a facade wrapper over `engine_runtime.py`.

## Already Split Behind Facade

- Inference and ranking math: `engine_inference.py`.
- Question selection: `engine_question_selection.py`.
- Learning row updates: `engine_learning.py`.
- Large constants/data: `engine_constants.py`, `engine_data.py`.
- Compound works helpers: `engine_compound_works.py`.
- Local stats/flags/log file helpers: `engine_stats.py`.
- DB schema/load/config/mutation/stats adapters: `engine_db.py`.
- Local matrix shape/init/load helpers: `engine_persistence.py`.
- Memory-only mutation helpers: `engine_mutations.py`.
- Admin/read-only reports: `engine_admin_reports.py`, `engine_reporting.py`, `engine_correlation.py`.

## Possible Later Moves

- `_save_matrix_file` and `_save_fetishes_file` internals are split; keep wrappers because mutation workflows call them directly.
- `_seed_db` internals are split; keep the facade wrapper until package conversion because `ensure_schema` still calls it.
- `_get_dynamic_prior_weights` and `_get_disc_scales` calculations are split; keep cache ownership and timestamp updates on Engine.
- `edit_question` save internals are split; keep public validation and state mutation on Engine.
- `_entropy` internals are split; keep the wrapper because question selection helpers call it through Engine.
- `_prob` and `_question_axis` should probably move during the package conversion itself, not before.

## Do Not Move In Prep PRs

- `posteriors`, `best_question`, and learning methods are behavior-critical public facade methods. Their helpers are already split; avoid changing wrapper signatures or call arguments.
- `add_fetish`, `merge_fetishes`, `delete_fetish`, `promote_fetish`, and `import_matrix` preserve mutation order and lock timing. Only move additional internals with direct parity tests.
- Package import target changes belong to the atomic `engine/` package migration PR only.
