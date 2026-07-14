# Engine Package Review

作成日: 2026-05-23

このレビュー資料は、`engine.py` から `engine/` package への移行完了後に、レビュワーが public API 互換・shim 互換・挙動固定・rollback 方法を短時間で確認するためのものです。追加機能は含みません。

## Review Summary

- `engine.py` は `engine/facade.py` へ移動済み。
- `engine/__init__.py` が public package facade になり、`import engine` と `from engine import ...` を維持している。
- 既存の top-level `engine_*` helper import は shim として残し、実体は `engine/` 配下へ移動済み。
- `Engine` は引き続き mutable state owner: questions, fetishes, matrix, config, locks, runtime caches, persistence orchestration.
- 推論、質問選択、学習、DB schema、UI/CSS、session/localStorage key は変更対象外。

## Commit Classification

### Package Switch Preparation

- `21d2fb1` Document engine package PR template
- `75038f9` Strengthen engine import target guard
- `387fc38` Document engine package rehearsal commands
- `85c5c0d` Lock engine helper dependency direction
- `230b41c` Cover standalone engine helper imports
- `abdcb60` Record engine package rehearsal QA
- `32692fa` Lock engine facade docs against public API

### Atomic Import Target Switch

- `52bad8b` Switch engine facade to package

Review focus:

- `engine.py` is renamed to `engine/facade.py`.
- `engine/__init__.py` executes the facade source in the package namespace so patch points such as `engine._use_db` and `engine.threading.Thread` remain compatible.
- `import engine` resolves to `engine/__init__.py`.

### Helper Moves Into `engine/` With Shims

- `5c201c0` Move pure engine helpers into package
- `1723c7a` Move read-only engine helpers into package
- `1ed6ba2` Move DB mutation engine helpers into package
- `df72e8a` Move engine inference helper into package
- `25f1066` Move engine question selection helper into package
- `08c636a` Move engine learning helper into package
- `3621b19` Update engine package helper plan

Review focus:

- New implementation modules live under `engine/`.
- Legacy top-level modules such as `engine_inference.py`, `engine_db.py`, and `engine_learning.py` remain as import-compatibility shims.
- Shim modules alias the package module object, so monkeypatching and direct imports keep working.

### Behavior Lock Coverage

- `811ffe3` Add learning behavior regression snapshots

Review focus:

- Learning matrix deltas are snapshot-tested for positive, near-miss, negative, and cooccurrence learning.
- Existing inference and question-selection snapshots remain in place.

## Public API Compatibility

These imports must continue to work:

```python
import engine
from engine import Engine
from engine import PLAYER_FETISH_BASE_ID, FOCUS_THRESHOLD, FETISH_RELATIONS
from engine import QUESTION_AXES, DOMAIN_PRIORS, FETISH_PRIOR_WEIGHTS
from engine import get_compound_works, list_compound_works, set_compound_works, delete_compound_works
from engine import parse_works_list
```

Contract coverage:

- `tests/test_engine_public_api_contract.py`
- `tests/test_engine_facade_contract.py`
- `tests/test_engine_package_switch_guard.py`

## Shim Compatibility

Top-level helper imports are intentionally retained for compatibility:

```python
import engine_inference
import engine_question_selection
import engine_learning
import engine_db
import engine_mutations
import engine_stats
```

The shim contract is covered by `tests/test_engine_helper_dependencies.py`:

- helper modules import without `Engine` instance setup.
- moved top-level shims alias package modules.
- package helpers do not import back into the public `engine` facade.

## Behavior Locks

Behavior-critical checks:

- Inference: `tests/test_engine_inference_regression.py`
- Question selection: `tests/test_engine_question_selection_regression.py`
- Learning deltas: `tests/test_engine_learning_regression.py`
- Persistence/mutation/DB: `tests/test_engine_persistence_regression.py`, `tests/test_engine_mutations.py`, `tests/test_engine_db.py`

These tests protect:

- posterior ordering and representative probabilities.
- deterministic `best_question` and disambiguation outputs with patched randomness.
- learning yes/total deltas and matrix update order.
- DB import/save adapter behavior and schema-related contracts.

## Rebase Review

The branch was rebased onto `origin/main` and pushed after tests passed.

Current verification baseline:

- `pytest`: `361 passed`
- working tree clean after push
- `origin/main` updated from `1c286ed` to `3621b19`

## Rollback

Rollback only behavior-critical helper moves:

```sh
git revert 3621b19 08c636a 25f1066 df72e8a 811ffe3
```

Rollback all helper moves after package switch:

```sh
git revert 3621b19 08c636a 25f1066 df72e8a 811ffe3 1ed6ba2 1723c7a 5c201c0
```

Rollback package switch and all helper moves:

```sh
git revert 3621b19 08c636a 25f1066 df72e8a 811ffe3 1ed6ba2 1723c7a 5c201c0 52bad8b
```

Use revert rather than reset because the commits have been pushed.

## Remaining Issues

- Top-level `engine_*` compatibility shims are intentionally still present.
- `engine/facade.py` remains large and still owns stateful orchestration.
- Some docs still describe historical preparation context; they are useful as audit trail, but the review source of truth is this file plus `docs/ENGINE_FACADE_CONTRACT.md`.
- Manual mobile / OGP / PWA QA remains outside engine package scope.

## Next Safe PRs

1. Shim retention policy PR: decide which `engine_*` shims must stay for external scripts/tests and which can receive deprecation notes.
2. Facade thinning PR: move only non-behavioral orchestration helpers behind package-internal APIs with parity tests.
3. Docs cleanup PR: separate historical package-prep docs from current architecture docs.
4. QA PR: complete manual mobile / OGP / PWA checks recorded in `docs/QA_EXECUTION_LOG.md`.
