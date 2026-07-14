# Engine Package PR Review Checklist

Use this checklist when reviewing the future atomic `engine.py` to `engine/` package PR. The PR description should follow `docs/ENGINE_PACKAGE_PR_TEMPLATE.md`. This checklist focuses on reviewer-visible risk, not implementation brainstorming.

## Must Be True In The Switch PR

- The PR has one import-target switch commit, not a sequence where both `engine.py` and `engine/` are live import targets.
- `import engine` resolves to one path consistently in tests, scripts, Flask routes, and interactive shell checks.
- `from engine import Engine` and all documented module exports still work.
- Public `Engine` method signatures match `tests/test_engine_public_api_contract.py`.
- `Engine` still owns mutable runtime state: questions, fetishes, matrix, config, locks, and runtime caches.
- Helper modules are not renamed in the same PR unless the compatibility facade already proves public imports are stable.

## Required Test Evidence

- `git diff --check`
- Full static JS syntax check list.
- `pytest`
- Focused contract set:
  - `tests/test_engine_public_api_contract.py`
  - `tests/test_engine_package_switch_guard.py`
  - `tests/test_engine_facade_contract.py`
  - `tests/test_engine_inference_regression.py`
  - `tests/test_engine_question_selection_regression.py`
  - `tests/test_engine_persistence_regression.py`
  - `tests/test_engine_mutations.py`

## Reviewer Red Flags

- Any change to inference probability math, posterior ordering, or question choice scoring.
- Any change to learning deltas, matrix update order, or cold-start learning strength.
- Any change to DB schema or SQL conflict semantics.
- Any change to session keys, localStorage keys, API response shape, or route paths.
- Any broad helper-module rename mixed into the import-target switch.
- Any circular import fixed by moving state ownership out of `Engine` during the switch.

## Rollback Review

Before approval, confirm the PR description states:

- The exact commit to revert if imports resolve incorrectly.
- Which focused tests demonstrate unchanged public API and behavior.
- Which follow-up PRs will handle helper renames or additional facade thinning.
