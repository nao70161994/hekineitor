# Refactor Status

## Completed

- OGP PNG endpoint added while keeping the legacy SVG endpoint.
- Result share CTA and simplified feedback flow are in place.
- Backend route handlers are split into `routes/`.
- Business helpers are split into `services/`.
- `engine.py` keeps the public facade while inference, learning, and question selection helpers are separated.
- Client code is split into focused modules under `static/`.
- Commit history has been split into reviewable units.
- Public, game, admin, and system routes are registered through Blueprints.
- `static/app.js` is reduced to a bootstrap stub.
- Most client compatibility exports now live beside their owning modules; `static/compat.js` only retains the last result-name compatibility state.
- Route context object construction is delegated through `services/context.py`, keeping `app.py` closer to dependency wiring only.
- Context dependencies are grouped by route domain before being flattened for existing route handlers.
- Admin maintenance assembly now lives in `services/admin_helpers.py`.
- Lightweight E2E strategy is documented in `docs/LIGHTWEIGHT_E2E.md`.

## Still Open

- Continue thinning the context/facade objects passed from `app.py` by grouping dependencies per route domain.
- Package `engine.py` as a directory while preserving import compatibility.
- Decide whether to keep `static/compat.js` as a permanent one-line compatibility shim or move the final `lastFetishName` state behind `HekiState`.
- Expand browser-oriented E2E coverage beyond Flask smoke paths when a lightweight browser runner is available.
- Complete manual QA for mobile CTA, OGP previews, and install/update behavior.

## Guardrails

- Do not change question selection behavior or diagnosis thresholds during refactor PRs.
- Keep public API response shapes compatible unless a migration PR explicitly says otherwise.
- Prefer moving code behind adapters before deleting compatibility wrappers.
- Run `git diff --check`, full `node --check` for static JS, and `pytest` after each refactor unit.
