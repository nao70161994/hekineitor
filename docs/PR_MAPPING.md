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

- `fa1473f` - Last result-name state moved into `HekiState`; `compat.js` script tag removed; file kept as a deprecated shim.

## Next PRs

1. Move individual context dependency groups into typed service helpers where it reduces `app.py` noise.
2. Decide whether to delete the unused deprecated `static/compat.js` file after one more release window.
3. Manual mobile/OGP/PWA QA pass against a deployed URL.
4. Browser E2E runner decision after manual QA gaps are confirmed.
5. Engine package compatibility layer preparation only; no package conversion yet.
