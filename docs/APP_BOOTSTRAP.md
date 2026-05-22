# App Bootstrap Responsibilities

`app.py` is intentionally kept as the Flask composition root. It should wire framework globals to route blueprints, but should not contain route behavior, inference behavior, learning behavior, or UI behavior.

## Responsibilities Kept In `app.py`

- Create the Flask application and session interface.
- Register response hooks, blueprints, and error handlers.
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
