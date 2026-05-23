# Engine Package Rehearsal Commands

Run these commands immediately before the future atomic `engine.py` to `engine/` package switch. This document is command evidence only; preparatory PRs must not create an `engine/` package.

## Import Target Preflight

```sh
git status --short
python3 -c "import engine, os; print(os.path.abspath(engine.__file__))"
python3 -c "import importlib.util; spec = importlib.util.find_spec('engine'); print(spec.origin, spec.submodule_search_locations)"
test ! -d engine
```

Expected before the switch:

- `git status --short` is empty.
- Both Python commands point to `engine.py`.
- `submodule_search_locations` is `None`.
- `test ! -d engine` exits successfully.

## Focused Contract Tests

```sh
python3 -m pytest \
  tests/test_engine_package_switch_guard.py \
  tests/test_engine_public_api_contract.py \
  tests/test_engine_facade_contract.py
```

## Behavior Lock Tests

```sh
python3 -m pytest \
  tests/test_engine_inference_regression.py \
  tests/test_engine_question_selection_regression.py \
  tests/test_engine_persistence_regression.py \
  tests/test_engine_mutations.py \
  tests/test_engine_db.py
```

## Full Verification

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
wc -l engine.py app.py
```

## Switch PR Evidence

Paste the command summaries into the PR created from `docs/ENGINE_PACKAGE_PR_TEMPLATE.md`. If any focused contract or behavior lock fails, stop before opening the switch PR.
