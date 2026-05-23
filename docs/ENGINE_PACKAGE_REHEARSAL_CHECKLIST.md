# Engine Package Rehearsal Checklist

Use this checklist immediately before the atomic `engine.py` -> `engine/` package switch. This file is a rehearsal guide only; prep PRs must not create `engine/`. Use `docs/ENGINE_PACKAGE_REHEARSAL_COMMANDS.md` for the exact command list to paste into switch PR evidence.

## Preflight

- Confirm the working tree is clean: `git status --short`.
- Confirm `engine.py` is still the active import target: `python3 -c "import engine; print(engine.__file__)"`.
- Confirm no `engine/` directory exists.
- Run the focused package guard tests: `python3 -m pytest tests/test_engine_package_switch_guard.py tests/test_engine_public_api_contract.py`.
- Run behavior locks: `python3 -m pytest tests/test_engine_inference_regression.py tests/test_engine_question_selection_regression.py tests/test_engine_facade_contract.py`.
- Run persistence/mutation locks: `python3 -m pytest tests/test_engine_persistence_regression.py tests/test_engine_mutations.py tests/test_engine_db.py`.

## Switch Commit Dry Run

- Create `engine/__init__.py` with the same public exports currently available from `engine.py`.
- Move the `Engine` facade without changing method signatures.
- Keep helper module imports stable first; rename helper modules only in later commits.
- Remove or rename `engine.py` in the same commit so Python cannot resolve two import targets.
- Run `python3 -m pytest tests/test_engine_public_api_contract.py tests/test_engine_package_switch_guard.py` before broader cleanup.

## Full Verification

- `git diff --check`
- JS syntax checks for every static module.
- `pytest`
- `git status --short`
- `wc -l engine.py app.py` or, after the switch, `wc -l engine/__init__.py engine/facade.py app.py`.

## Rollback

- If imports resolve inconsistently, revert the switch commit immediately.
- If public API contract tests fail, do not patch around the failure in follow-up commits; restore exports/signatures in the switch commit.
- If inference or question-selection snapshots change, revert and split the behavior change into a separate explicit migration PR.
- If circular imports force state ownership changes, revert and add another prep PR instead of continuing inside the switch commit.
