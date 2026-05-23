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
- Inference helper now lives in `engine/inference.py` with `engine_inference.py` kept as a compatibility shim.
- Question-selection helper now lives in `engine/question_selection.py` with `engine_question_selection.py` kept as a compatibility shim.
- Learning helper now lives in `engine/learning.py` with `engine_learning.py` kept as a compatibility shim.
- Engine facade contract now covers all staged learning helper delegations.
- `_learn_silent` is delegated through `engine_learning.learn_silent` with facade parity coverage.
- Engine package conversion is documented in `docs/ENGINE_PACKAGE_PLAN.md`; implementation is deferred until compatibility moves are narrower.
- Compound works key/list helpers are split from `engine.py` while public functions and cache patch points stay compatible.
- Compound works cache/load/save helper behavior is covered directly while public `engine` functions stay compatible.
- Scalar engine constants now live in `engine/constants.py` with `engine_constants.py` kept as an import-compatibility shim.
- Large engine data constants now live in `engine/data.py` with `engine_data.py` kept as an import-compatibility shim.
- Representative inference snapshots now lock top-guess IDs and probabilities before engine package work continues.
- Deterministic question-selection snapshots now lock representative best-question and disambiguation outputs.
- Matrix import and persistence contracts are covered before persistence code is moved out of `engine.py`.
- Local JSON stats, question flag, and fetish-log helpers now live in `engine/stats.py` with `engine_stats.py` kept as a compatibility shim.
- Read-only stats-history reporting helpers now live in `engine/reporting.py` with `engine_reporting.py` kept as a compatibility shim.
- Read-only admin report helpers now live in `engine/admin_reports.py` with `engine_admin_reports.py` kept as a compatibility shim.
- Correlation-cache and contradiction helpers now live in `engine/correlation.py` with `engine_correlation.py` kept as a compatibility shim.
- DB matrix save/import adapters now live in `engine/db.py` with `engine_db.py` kept as a compatibility shim.
- Memory-only mutation helpers now live in `engine/mutations.py` with `engine_mutations.py` kept as a compatibility shim.
- DB schema/load/config persistence helpers now live in `engine/db.py` behind Engine facade methods.
- DB mutation adapters for add/edit/delete/merge/promote now live in `engine/db.py` while Engine keeps mutation orchestration.
- Engine facade state ownership and public API contracts are documented in `docs/ENGINE_FACADE_CONTRACT.md` and covered by signature/import tests.
- Engine DB stats, disabled-question, and fetish-log adapters now live in `engine/db.py` while Engine keeps public orchestration.
- Local matrix shape/init/load/save helpers now live in `engine/persistence.py` while Engine keeps state assignment, locked snapshots, and save orchestration.
- Remaining local JSON reads in engine mutation/reporting flows now use `engine_stats.read_json_path`, removing direct `json` usage from `engine.py`.
- Question save writes are delegated through `engine/persistence.py` while Engine keeps validation and state mutation.
- Async save and stale DB reload behavior are covered by facade contract tests.
- DB seed matrix row building/writing now lives in `engine/db.py` behind the `_seed_db` compatibility wrapper.
- Disc-scale, dynamic-prior, and entropy calculations now live in `engine/runtime.py` while Engine keeps cache state/timing and compatibility wrappers, covered by facade contract tests.
- The atomic `engine.py` to `engine/` package switch is complete; guard tests now ensure `engine` resolves to `engine/__init__.py`.
- Importlib guard coverage now confirms `engine` has package search locations under `engine/`.
- Engine package rehearsal and rollback steps are documented in `docs/ENGINE_PACKAGE_REHEARSAL_CHECKLIST.md`.
- Engine package rehearsal command evidence is documented in `docs/ENGINE_PACKAGE_REHEARSAL_COMMANDS.md`.
- Engine package switch PR review criteria are documented in `docs/ENGINE_PACKAGE_PR_REVIEW.md`.
- Engine package switch PR description requirements are documented in `docs/ENGINE_PACKAGE_PR_TEMPLATE.md`.
- Remaining engine facade private helpers are classified in `docs/ENGINE_PRIVATE_HELPER_MAP.md` for package-prep review.
- Engine helper modules are covered by dependency tests that prevent imports back into the public `engine` facade.
- Engine helper modules are covered by standalone import tests before package conversion.
- App composition-root responsibilities were reviewed against `docs/APP_BOOTSTRAP.md` after engine package planning.

- Lightweight share event tracking now records non-PII share/result/OGP events to environment-separated JSONL logs with an admin summary endpoint.
- Admin now renders a lightweight share analytics card backed by `/api/admin/share_events` daily/channel/KPI summaries.
- Share analytics now includes result-name ranking summaries for admin review without adding identifiers or new storage schema.

## Still Open

- Keep remaining `app.py` factories as explicit composition-root adapters; only extract when ownership is clearer than Flask wiring.
- Expand browser-oriented E2E coverage beyond Flask smoke paths when a lightweight browser runner is available.
- Execute the manual QA backlog in `docs/QA_EXECUTION_LOG.md` for mobile CTA, OGP previews, and PWA install/update behavior.

## Guardrails

- Do not change question selection behavior or diagnosis thresholds during refactor PRs.
- Keep public API response shapes compatible unless a migration PR explicitly says otherwise.
- Prefer moving code behind adapters before deleting compatibility wrappers.
- Run `git diff --check`, full `node --check` for static JS, and `pytest` after each refactor unit.
