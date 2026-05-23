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
- Client compatibility exports now live beside their owning modules; the deprecated `static/compat.js` shim has been removed.
- Route context object construction is delegated through `services/context.py`, keeping `app.py` closer to dependency wiring only.
- Context dependencies are grouped by route domain before being flattened for existing route handlers.
- Admin maintenance assembly now lives in `services/admin_helpers.py`.
- Server session storage and admin security helpers are split into services.
- Runtime rate limiting and trusted proxy client IP handling are split into a service.
- Response hooks and matrix import backup helpers are split into services.
- Guess quality stats and ID list parsing are split into small services.
- Redundant share/progress wrappers have been removed from `app.py`.
- Guess orchestration is now handled by `services/inference.py`.
- Flask secret key setup is isolated in `services/app_meta.py` with direct regression coverage.
- Runtime guard policy for CSRF and rate limiting is isolated in `services/runtime_guards.py`.
- Public base URL resolution for SEO/share routes lives in `services/share.py`.
- Stale app-level test helper wrappers were removed; tests now target owning services directly.
- Game flow question/learning closures are provided by owning services instead of app-level wrappers.
- Legacy OGP SVG response assembly now lives in the SEO route while keeping `/ogp` behavior intact.
- Guess quality feedback recording is bound through `services/quality_stats.py` instead of an app-level wrapper.
- Matrix import backup operations are grouped behind `services/matrix_backups.py` adapter methods.
- Admin matrix routes now receive matrix backup operations through the adapter instead of individual app wrappers.
- Stale app-level client IP and matrix backup wrappers were removed after service coverage was added.
- Redundant app helper wrappers for name matching and admin paging were removed.
- App versioning and name matching helpers are pure service modules with direct regression tests.
- Lightweight E2E strategy is documented in `docs/LIGHTWEIGHT_E2E.md`.
- QA execution status is tracked in `docs/QA_EXECUTION_LOG.md` with manual mobile/OGP/PWA gaps marked explicitly.
- Game context construction now lives in `services/game_context.py`.
- SEO context construction now lives in `services/seo_context.py`.
- `services/context.py` is retained as a behavior-free compatibility flattener for route contexts.
- Flask runtime/security helpers are grouped behind `services/runtime.py`.
- Game and admin context builders receive the Flask runtime bundle instead of individual security/rate-limit wrappers.
- Filesystem/path/storage helpers are grouped behind `services/filesystem_context.py`.
- Matrix backup operations can now be built from the filesystem bundle instead of app-level path arguments.
- Admin and system context builders receive filesystem bundles instead of individual path/storage helpers.
- Bootstrap configuration is grouped in `services/bootstrap.py`.
- App composition-root responsibilities are documented in `docs/APP_BOOTSTRAP.md`.
- App-level factories were renamed to clarify their roles: `_flask_runtime`, `_filesystem_context`, and `_matrix_operations`.
- Blueprint and error-handler registration is grouped in app-root helper functions for scanability.
- Additional context-builder config bundles were reviewed and deferred until a clearer ownership boundary appears.
- Engine facade/helper parity is covered by direct contract tests.
- Engine facade contract now covers all staged learning helper delegations.
- `_learn_silent` is delegated through `engine_learning.learn_silent` with facade parity coverage.
- Engine package conversion is documented in `docs/ENGINE_PACKAGE_PLAN.md`; implementation is deferred until compatibility moves are narrower.
- Compound works key/list helpers are split from `engine.py` while public functions and cache patch points stay compatible.
- Compound works cache/load/save helper behavior is covered directly while public `engine` functions stay compatible.
- Scalar engine constants are split into `engine_constants.py` with `engine` re-export compatibility covered by tests.
- Large engine data constants are split into `engine_data.py` with `engine` re-export compatibility covered by tests.
- Representative inference snapshots now lock top-guess IDs and probabilities before engine package work continues.
- Deterministic question-selection snapshots now lock representative best-question and disambiguation outputs.
- Matrix import and persistence contracts are covered before persistence code is moved out of `engine.py`.
- Local JSON stats, question flag, and fetish-log helpers are split into `engine_stats.py` with direct tests.
- Read-only stats-history reporting helpers are split into `engine_reporting.py` with output-shape tests.
- Read-only admin report helpers are split into `engine_admin_reports.py` behind facade delegates.
- Correlation-cache and contradiction helpers are split into `engine_correlation.py` behind facade delegates.
- DB matrix save/import adapters are split into `engine_db.py` with SQL and row-builder tests.
- Memory-only mutation helpers are split into `engine_mutations.py` behind Engine facade methods.
- DB schema/load/config persistence helpers are split into `engine_db.py` behind Engine facade methods.
- DB mutation adapters for add/edit/delete/merge/promote are split into `engine_db.py` while Engine keeps mutation orchestration.
- Engine facade state ownership and public API contracts are documented in `docs/ENGINE_FACADE_CONTRACT.md` and covered by signature/import tests.
- Engine DB stats, disabled-question, and fetish-log adapters are split into `engine_db.py` while Engine keeps public orchestration.
- Local matrix shape/init/load helpers are split into `engine_persistence.py` while Engine keeps state assignment and save orchestration.
- App composition-root responsibilities were reviewed against `docs/APP_BOOTSTRAP.md` after engine package planning.

## Still Open

- Keep remaining `app.py` factories as explicit composition-root adapters; only extract when ownership is clearer than Flask wiring.
- Package `engine.py` as a directory while preserving import compatibility.
- Design the engine package compatibility facade before moving the import target from `engine.py` to an `engine/` package.
- Expand browser-oriented E2E coverage beyond Flask smoke paths when a lightweight browser runner is available.
- Execute the manual QA backlog in `docs/QA_EXECUTION_LOG.md` for mobile CTA, OGP previews, and PWA install/update behavior.

## Guardrails

- Do not change question selection behavior or diagnosis thresholds during refactor PRs.
- Keep public API response shapes compatible unless a migration PR explicitly says otherwise.
- Prefer moving code behind adapters before deleting compatibility wrappers.
- Run `git diff --check`, full `node --check` for static JS, and `pytest` after each refactor unit.
