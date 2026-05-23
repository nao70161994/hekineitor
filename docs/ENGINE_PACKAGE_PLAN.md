# Engine Package Plan

This plan prepares `engine.py` for package conversion without changing diagnosis behavior, question selection, learning strength, storage schema, or public imports. See `docs/ENGINE_FACADE_CONTRACT.md` for the state ownership and public API contract that package conversion must preserve. See `docs/ENGINE_PRIVATE_HELPER_MAP.md` for the remaining private-helper move map. See `docs/ENGINE_PACKAGE_SWITCH_PLAN.md` for the future atomic import-target switch plan and `docs/ENGINE_PACKAGE_REHEARSAL_CHECKLIST.md` for preflight/rollback steps.

## Current State

- `engine.py` is still the public module imported by routes, tests, and scripts.
- `Engine` remains the public facade and owns mutable runtime state: fetishes, questions, matrix, config, caches, locks, and persistence helpers. `docs/ENGINE_FACADE_CONTRACT.md` now lists this ownership explicitly.
- Pure-ish helper modules already exist beside the facade:
  - `engine_inference.py` for posterior probability, top guesses, and answer contribution helpers.
  - `engine_question_selection.py` for question axis lookup and question choice helpers.
  - `engine_learning.py` for positive, near-miss, cooccurrence, negative, and silent learning updates.
- `tests/test_engine_facade_contract.py` locks facade-to-helper parity for inference, question selection, positive learning, near-miss learning, negative learning, cooccurrence learning, silent learning, and current public module exports.
- `engine_compound_works.py` contains compound works key/list/cache/save helpers while `engine.py` still owns public compatibility functions and cache globals.
- `engine_constants.py` contains scalar package-prep constants while `engine.py` re-exports the same public names.
- `engine_data.py` contains large data constants (`QUESTION_AXES`, `DOMAIN_PRIORS`, `FETISH_RELATIONS`, `FETISH_PRIOR_WEIGHTS`) while `engine.py` re-exports the same public names.
- `engine_stats.py` contains local JSON stats, question flag, and fetish-log helpers while DB branches remain in `engine.py`.
- `engine_reporting.py` contains read-only stats-history aggregation helpers for recent ranking, fetish history, and quality event summaries.
- `engine_admin_reports.py` contains read-only admin matrix/question/fetish report helpers delegated by the `Engine` facade.
- `engine_correlation.py` contains correlation-cache and contradiction helpers behind `Engine` facade delegates.
- `engine_db.py` contains DB schema creation, fetish/matrix/config load helpers, DB matrix save/import SQL adapters, DB seed adapters, DB mutation adapters, and DB stats/log adapters used by `Engine` facade methods.
- `engine_mutations.py` contains memory-only add/edit/delete/merge/promote helpers used by `Engine` mutation facade methods.
- `engine_persistence.py` contains local matrix shape/init/load/save helpers while `Engine` keeps state assignment, locked snapshots, and save orchestration.
- `engine_runtime.py` contains runtime cache calculations for disc scales, dynamic prior weights, and entropy while `Engine` keeps cache ownership/timestamps and compatibility wrappers.
- `tests/test_engine_inference_regression.py` snapshots representative top-guess IDs and probabilities before further package moves.
- `tests/test_engine_question_selection_regression.py` snapshots deterministic question selection and disambiguation cases.
- `tests/test_engine_persistence_regression.py` locks matrix snapshot, validation, local import/save, and DB overwrite-import contracts.

## Non-Negotiable Compatibility Contract

Keep these imports working until a dedicated migration PR removes them with explicit downstream changes:

```python
import engine
from engine import Engine
from engine import PLAYER_FETISH_BASE_ID, FOCUS_THRESHOLD, FETISH_RELATIONS
from engine import get_compound_works, list_compound_works, set_compound_works, delete_compound_works
from engine import parse_works_list
```

`Engine` method names and return shapes must remain stable for route handlers and tests. In particular, do not change the meaning of:

- `posteriors`, `top_guess`, `best_question`, `best_disambiguating_question`
- `learn`, `learn_near_miss`, `learn_negative`, `learn_cooccurrence`, `boost_learn_new`
- `add_fetish`, `edit_fetish`, `delete_fetish`, `merge_fetishes`, `promote_fetish`
- stats, matrix import/export validation, and fetish log methods

## Target Package Shape

Use a package only after the compatibility facade is ready:

```text
engine/
  __init__.py          # public compatibility facade exports
  facade.py            # Engine class, thin delegation, state ownership
  constants.py         # PLAYER_FETISH_BASE_ID, priors, relations, thresholds
  inference.py         # current engine_inference.py behavior
  question_selection.py# current engine_question_selection.py behavior
  learning.py          # current engine_learning.py behavior
  persistence.py       # JSON/DB matrix/fetish/stat persistence
  admin_ops.py         # matrix import/export, stats, maintenance helpers
  compound_works.py    # compound works helpers
```

Because Python cannot safely keep both `engine.py` and an `engine/` package as the same import target in the same directory, the conversion must be one atomic compatibility step after preparatory moves are done. Until then, keep helper modules at top level or use a non-conflicting staging name.

## Safe Preparation Steps

1. Keep adding behavior-lock tests around public `Engine` methods before moving code.
2. Move only pure constants or helper functions when tests prove no behavior change.
3. Keep `engine.py` as the facade and re-export source during each move.
4. Prefer helper function delegation over inheritance or monkeypatch-heavy adapters.
5. Keep persistence code in `engine.py` until DB and JSON behavior has narrow tests.
6. Run full `pytest` after each move; run route smoke tests after any public export changes.

## Recommended Move Order

1. Scalar and large data constants are staged in `engine_constants.py` and `engine_data.py`; `engine.py` keeps import-compatible re-exports.
2. `compound_works.py`: cache/load/save helpers are staged in `engine_compound_works.py`; a later PR can move cache globals only if public `engine` patch points stay compatible.
3. Existing helper module rename only after tests: `engine_inference.py` -> package `inference.py`, `engine_question_selection.py` -> `question_selection.py`, `engine_learning.py` -> `learning.py`.
4. Read-only stats-history and admin report helpers are staged in `engine_reporting.py` and `engine_admin_reports.py`; keep route-facing `Engine` methods as facade delegates until package conversion.
5. Local JSON stats/flag/log helpers are staged in `engine_stats.py`; DB schema/load/config helpers, matrix save/import adapters, DB mutation adapters, and DB stats/log adapters are staged in `engine_db.py` while object mutation orchestration remains behind the `Engine` facade.

## Facade Thinning Rules

The final facade should own state and expose public methods, but method bodies should mostly delegate. A method is safe to thin when:

- It can be expressed as `return helper(self, ...)` or a small lock/persistence wrapper.
- The helper receives all dependencies explicitly instead of importing Flask or route modules.
- A parity test compares facade output to helper output for representative inputs.
- The move does not change matrix update order, floating point weights, randomness, or cache invalidation timing.

## Regression Tests To Add Before Package Conversion

- Public import and method-signature contract for `engine` exports, including scalar constants, large data constants, module helper functions, and public `Engine` methods.
- Representative top-guess ID/probability snapshots for empty, strong-signal, and mixed-answer cases.
- Deterministic question selection snapshots for empty, idk streak, and focused-answer cases.
- Facade/helper parity for inference, question selection, positive learning, near-miss learning, negative learning, cooccurrence learning, and silent learning.
- Compound works helper behavior for ID order normalization, cache load-once behavior, save options, copy-on-read, and delete/list results.
- Matrix import/export validation without writes.
- Persistence smoke tests for snapshot copies, local save behavior, DB import delegation, and duplicate rejection before moving JSON/DB code.
- Mutation helper parity for add/edit/delete/merge/promote memory updates and `_learn_silent` contract behavior.
- DB schema/load/config helper contracts for `_ensure_db`, `_load_fetishes_from_db`, `_load_from_db`, and config persistence facades.
- DB mutation adapter contracts for add/edit/delete/merge/promote SQL branches while memory mutation order remains facade-owned.
- DB stats, disabled-question, and fetish-log adapter contracts while Engine keeps route-facing orchestration and local-file branches.
- DB seed matrix row-order and insert-SQL contracts while `_seed_db` remains a facade wrapper.
- Local matrix persistence helper contracts for matrix shape validation, learned-prior application, invalid-shape backup, reinitialization, atomic write arguments, question save arguments, and learned-prior snapshot output.
- Runtime calculation contracts for disc scale normalization/clamping, dynamic-prior blending/flooring, entropy behavior, plus facade cache ownership/timestamp behavior.
- Facade contracts for async DB/local save branching and stale DB matrix reload TTL/timestamp behavior.
- A deterministic `best_question` test with patched randomness for early-game selection.

## Stop Conditions

Stop and revert the current commit if any of these happen:

- `posteriors` ordering changes for representative answer sets.
- `best_question` changes with patched deterministic randomness.
- Learning deltas differ for yes/total matrix rows.
- Public imports from `engine` fail.
- DB and JSON modes need different code paths that cannot be covered in the same PR.

## Current Recommendation

Do not convert `engine.py` into an `engine/` package yet. The safe next implementation PR is to design the eventual `engine/` package compatibility facade and decide which remaining stateful methods must stay on `Engine` until the atomic import-target switch.
