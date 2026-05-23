# Engine Package Switch Plan

This is the future atomic migration plan for replacing `engine.py` with an `engine/` package. Do not execute this plan in preparatory refactor PRs. Use `docs/ENGINE_PACKAGE_REHEARSAL_CHECKLIST.md` as the preflight checklist before the switch.

## Preconditions

- `tests/test_engine_public_api_contract.py` passes and covers all route-facing public methods.
- `docs/ENGINE_FACADE_CONTRACT.md` matches the implemented public exports and state ownership.
- `docs/ENGINE_PRIVATE_HELPER_MAP.md` has no unresolved helper moves that would be safer before the import-target switch.
- Full `pytest`, static JS syntax checks, and route smoke tests pass on the branch immediately before the switch.

## Atomic Switch Outline

1. Create a temporary staging package name, not `engine/`, if more rehearsal is needed.
2. In the actual switch commit, move the public facade into `engine/__init__.py` and `engine/facade.py` in one commit.
3. Keep every public export currently provided by `engine.py` re-exported from `engine/__init__.py`.
4. Move helper modules only by import-compatible aliases or after the facade import path is proven stable.
5. Delete or rename `engine.py` only in the same commit that creates the package facade.
6. Run the public API contract, inference regression, question-selection regression, mutation, persistence, app, and smoke tests before any follow-up refactor.

## Compatibility Requirements

These commands must keep working after the switch:

```python
import engine
from engine import Engine
from engine import PLAYER_FETISH_BASE_ID, FOCUS_THRESHOLD, FETISH_RELATIONS
from engine import get_compound_works, list_compound_works, set_compound_works, delete_compound_works
from engine import parse_works_list
```

The switch must not change:

- `posteriors` ordering or probabilities.
- `best_question` output for deterministic fixtures.
- Learning matrix deltas or update order.
- DB schema or persistence SQL semantics.
- Session keys, localStorage keys, routes, or UI/CSS.

## Stop Conditions

Stop and revert the switch commit if any of these happen:

- Python imports resolve to both `engine.py` and `engine/` depending on execution context.
- Public contract tests fail because exports or method signatures changed.
- Regression snapshots change without an explicit behavior migration.
- Circular imports require moving state ownership out of `Engine` during the switch.
