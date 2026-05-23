# PR Mapping

## Prepared Commits

- `8b1a2ad` - Backend routes and engine service split.
- `b6082c3` - Admin maintenance tooling.
- `6f34e6f` - Client game and UI module split.
- `8ce2e77` - Pillow dependency documentation.
- `3bc6d46` - Split module formatting cleanup.

## Suggested PRs

1. Backend route/service split.
2. Admin maintenance and ASIN backfill support.
3. Client module split and CTA/feedback UI wiring.
4. OGP PNG and share metadata validation.
5. QA checklist and review documentation.

## Additional Refactor Commits

- `36fc013` - Refactor review and QA checklists.
- `d56a921` - Client module and OGP smoke checks.
- `856c8a8` - Error page rendering moved into system routes.
- `8e04393` - Stale app import cleanup.
- `97b8023` - SEO routes registered through Blueprint.
- `7f36bd3` - Health route registered through Blueprint.
- `216d717` - Client compatibility wrappers moved out of `app.js`.
- `e5ef70d` - Game API routes registered through Blueprint.
- `d0630d8` - Admin routes registered through Blueprint.
- `4134089` - Public system routes registered through Blueprint.


- `04638c9` - Feedback, teach, history, and draft compatibility exports moved to owning client modules.
- `1d0bd1e` - Remaining client compatibility exports moved to owning modules; `compat.js` reduced to the result-name shim.
- `7214301` - Route context builders extracted into `services/context.py`.

- `bc44867` - Route context dependencies grouped by domain.
- `44db57e` - Admin maintenance assembly moved to helper service.
- `def4021` - Resume, feedback, share, OGP, and PWA static smoke coverage added.

- `fa1473f` - Last result-name state moved into `HekiState`.

- `bc21703` - Deprecated client compat shim removed from page loading.
- `d86326e` - Server session storage moved to service.
- `feab302` - Admin security helpers moved to service.
- `c9b2b6c` - App metadata and name matching helpers moved to services.
- `d69d5cb` - Direct service helper regression tests added.

- `72e84ef` - Runtime rate limiting moved to service.
- `f693d9f` - Rate limit service regression tests added.

- `ee9a1fd` - Deprecated client compat shim file removed.
- `2dea3fd` - Response hooks moved to service.
- `cb8dbf0` - Response hook service tests added.
- `2633e2e` - Matrix backup helpers moved to service.
- `b3a86fb` - Matrix backup service tests added.

- `75877f9` - Guess quality stats moved to service.
- `c01220c` - Quality stats service tests added.
- `7d78d97` - Low-confidence extension helper moved to question selection service.
- `f514923` - Low-confidence helper tests added.
- `9ebabe5` - Redundant share context wrappers removed.
- `f2a3f68` - ID list parsing moved to service.
- `21d9e55` - ID parsing service tests added.
- `afd21f0` - Progress message wrapper removed.

- `2d70754` - Guess orchestration moved to inference service.
- `7defadf` - Inference guess orchestration test added.
- `b4782e7` - Named SEO context builder introduced.
- `9c4189a` - Redundant app helper wrappers removed.
- `f925f84` - Secret key setup moved to app metadata service.
- `97bbaac` - Runtime guard policy moved to service.
- `9d13374` - Public base URL helper moved to share service.
- `76e5e20` - Stale app test helper wrappers removed.
- `aa7ba05` - Game flow closures moved to owning services.
- `351ca1d` - OGP SVG response assembly moved to SEO route.
- `687facf` - Quality feedback recorder moved to service.
- `41b8c66` - Matrix backup operations adapter added.
- `477cf55` - Admin context switched to matrix operations adapter.
- `fb22233` - Matrix backup app wrappers removed.
- `ed3abd0` - Stale client IP wrapper removed.
- `51b9513` - Admin context builder moved to service.
- `ad04076` - System context builder moved to service.
- `d55bf1d` - Context builder service tests added.
- `01ca4ab` - Game context builder moved to service.
- `ced6d3e` - SEO context builder moved to service.
- `afed0f9` - Route context facade role documented.
- `3e6cef7` - Flask runtime security bundle introduced.
- `e8de371` - Flask runtime bundle passed into game/admin contexts.
- `940a54f` - Filesystem dependency bundle added.
- `211326f` - Filesystem bundle passed into admin/system contexts.
- `cb659ee` - App bootstrap config bundle added.
- `c7ef15a` - App factory names clarified.
- `666c140` - Blueprint registration grouped in app root.
- `d401d19` - Engine facade contract tests added.
- Engine facade learning delegation contract expanded.
- Silent learning helper delegated through `engine_learning`.
- Engine package conversion plan documented in `docs/ENGINE_PACKAGE_PLAN.md`.
- Compound works pure helpers split from `engine.py`.
- Compound works cache/load/save helpers and tests added.
- Scalar engine constants split behind `engine` re-export compatibility.
- Large engine data constants split behind `engine` re-export compatibility.
- Engine inference regression snapshots added.
- Engine question-selection regression snapshots added.
- Engine matrix persistence regression tests added.
- Local engine stats persistence helpers split and tested.
- Engine stats-history reporting helpers split and tested.
- Engine admin report helpers split behind facade delegates.
- Engine correlation helpers split behind facade delegates.
- Engine DB matrix persistence adapters split and tested.
- Engine mutation helpers split behind facade methods.
- Engine DB schema/load/config persistence helpers split behind facade methods.
- Engine DB mutation adapters split behind facade methods.
- Engine facade state ownership and public API contract documented and tested.
- Engine DB stats and log adapters split behind facade methods.
- Engine local matrix persistence helpers split behind facade methods.
- Engine local save and learned-prior snapshot helpers split behind facade methods.
- Engine direct local JSON reads consolidated through stats helper.
- Engine question save helper split and async/reload facade contracts added.
- Engine DB seed matrix adapter split behind `_seed_db`.
- Engine runtime cache and entropy calculations split behind facade compatibility wrappers.
- Engine package atomic switch completed with import-target guard tests.
- Engine import-target guard tests updated for package resolution.
- Engine package rehearsal checklist and rollback steps documented.
- Engine package rehearsal command evidence documented.
- Engine package switch PR review checklist documented.
- Engine package switch PR description template documented.
- Engine private helper move map documented for package-prep review.
- Engine helper dependency direction locked with tests.
- Pure engine helper modules moved into `engine/` with legacy shims.
- Read-only engine helper modules moved into `engine/` with legacy shims.
- DB and mutation engine helper modules moved into `engine/` with legacy shims.
- Inference helper moved into `engine/` with a legacy shim.
- App composition-root review documented.

## Next PRs

1. Keep `app.py` as composition root; avoid further extraction unless a dependency group has clear ownership outside Flask wiring.
2. Execute `docs/QA_EXECUTION_LOG.md` manual mobile/OGP/PWA backlog against real devices and a deployed URL.
3. Browser E2E runner decision after manual QA gaps are confirmed.
4. Continue moving remaining inference/learning/question-selection helpers into `engine/` behind compatibility shims only after behavior locks stay green.
5. Keep DB and mutation behavior locked with tests while reducing remaining facade method bodies.
