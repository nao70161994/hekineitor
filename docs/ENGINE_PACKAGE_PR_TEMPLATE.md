# Engine Package PR Template

Use this template only for the future atomic `engine.py` to `engine/` package switch PR. Preparatory refactor PRs should reference this document but must not create an `engine/` package.

## Summary

- Move the public import target from `engine.py` to an `engine/` package in one atomic commit.
- Preserve `import engine`, `from engine import Engine`, and every documented module-level export.
- Keep `Engine` as the owner of mutable runtime state during the switch.

## Non-Goals

- No inference probability, posterior ordering, or question-selection changes.
- No learning delta, matrix update order, or cold-start behavior changes.
- No DB schema, SQL conflict behavior, session key, localStorage key, route, API response, UI, or CSS changes.
- No broad helper-module rename mixed into the import-target switch.

## Public API Compatibility

Confirm these imports and signatures before review:

```python
import engine
from engine import Engine
from engine import PLAYER_FETISH_BASE_ID, FOCUS_THRESHOLD, FETISH_RELATIONS
from engine import get_compound_works, list_compound_works, set_compound_works, delete_compound_works
from engine import parse_works_list
```

Required evidence:

- `tests/test_engine_public_api_contract.py`
- `tests/test_engine_facade_contract.py`
- `tests/test_engine_package_switch_guard.py`

## Behavior Lock Evidence

Attach focused output for:

- `tests/test_engine_inference_regression.py`
- `tests/test_engine_question_selection_regression.py`
- `tests/test_engine_persistence_regression.py`
- `tests/test_engine_mutations.py`
- `tests/test_engine_db.py`

The PR description must explicitly state that `posteriors`, `best_question`, learning deltas, matrix update order, and DB schema are unchanged.

## Full Verification

Run and paste summary output:

```sh
git diff --check
node --check static/app.js
node --check static/utils.js
node --check static/network.js
node --check static/ui.js
node --check static/game_flow.js
node --check static/draft.js
node --check static/share.js
node --check static/pwa.js
node --check static/history.js
node --check static/teach.js
node --check static/feedback.js
node --check static/renderers.js
node --check static/events.js
node --check static/api_client.js
node --check static/game_state.js
node --check static/admin.js
node --check static/admin_ops.js
pytest
git status --short
```

## Rollback Plan

- Revert the single import-target switch commit if `import engine` resolves inconsistently or contract tests fail.
- Do not patch behavior in place while imports are ambiguous.
- Leave helper-module rename and facade-thinning follow-ups for later PRs after the import target is stable.

## Manual Review Notes

- Confirm route modules still import only the public `engine` facade.
- Confirm no Flask route, static asset, DB path, session key, or localStorage key changed.
- Confirm any package-internal imports are one-directional and do not move mutable state out of `Engine`.
