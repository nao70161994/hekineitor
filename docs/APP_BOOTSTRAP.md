# App Bootstrap Responsibilities

`app.py` is intentionally kept as the Flask composition root. It should wire framework globals to route blueprints, but should not contain route behavior, inference behavior, learning behavior, or UI behavior.

## Responsibilities Kept In `app.py`

- Create the Flask application and session interface.
- Register response hooks, blueprints, and error handlers through `_register_blueprints()` and `_register_error_handlers()`.
- Instantiate the shared `Engine` facade.
- Build request-scoped adapters that depend on Flask proxies:
  - `_flask_runtime()` for request/session/security/rate-limit helpers.
  - `_filesystem_context()` for filesystem/path/storage helpers.
  - `_matrix_operations()` for admin matrix backup operations built from filesystem helpers.
- Pass stable bootstrap configuration from `services/bootstrap.py` into context builders.

## Responsibilities Moved Out

- Route handlers live under `routes/`.
- Route context assembly lives under `services/*_context.py`.
- Runtime security and rate limiting live in `services/runtime.py`.
- Filesystem/path/storage helper grouping lives in `services/filesystem_context.py`.
- Matrix backup behavior lives in `services/matrix_backups.py`.
- Inference, learning, question selection, sharing, OGP, and admin helper logic live in owning service modules.

## Guardrails

- Keep `app.py` changes focused on wiring and bootstrap configuration.
- Do not move game rules, inference thresholds, session keys, localStorage keys, or DB schema through bootstrap refactors.
- Prefer small adapters over deleting compatibility layers when tests or routes still depend on a stable patch point.


## Current Factory Boundaries

- `_flask_runtime()` remains in `app.py` because it binds Flask request/session proxies for the current request.
- `_filesystem_context()` remains in `app.py` because it binds process-local filesystem modules and storage helpers.
- `_matrix_operations()` remains in `app.py` as a stable admin-test patch point and as the matrix backup adapter built from the current filesystem context.

## Config Bundle Decision

`services/bootstrap.py` currently owns only stable bootstrap values. No additional context-builder config bundle is being introduced until a dependency group has clear ownership outside Flask wiring. This avoids hiding route contracts behind opaque configuration objects.

## Review - 2026-05-23

Current `app.py` responsibilities match this document. The remaining factories are intentionally request/process adapters rather than business logic:

- `_flask_runtime()` binds Flask request/session proxies and should stay in the composition root.
- `_filesystem_context()` binds process-local modules and storage helpers and should stay until a real storage object owns those dependencies.
- `_matrix_operations()` is an admin adapter built from the filesystem context and remains a useful route-test patch point.
- `_seo_context()`, `_game_context()`, `_admin_context()`, and `_system_context()` are thin calls into owning service builders.

Do not extract more from `app.py` only to reduce line count. Backend responsibility changes should use explicit boundaries inside the `engine/` package or owning services, not hide Flask wiring behind opaque global objects.
