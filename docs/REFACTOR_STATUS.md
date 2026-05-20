# Refactor Status

## Completed

- OGP PNG endpoint added while keeping the legacy SVG endpoint.
- Result share CTA and simplified feedback flow are in place.
- Backend route handlers are split into `routes/`.
- Business helpers are split into `services/`.
- `engine.py` keeps the public facade while inference, learning, and question selection helpers are separated.
- Client code is split into focused modules under `static/`.
- Commit history has been split into reviewable units.

## Still Open

- Move `app.py` route decorators to Blueprint registration.
- Thin the context/facade objects passed from `app.py`.
- Package `engine.py` as a directory while preserving import compatibility.
- Reduce the remaining compatibility wrappers in `static/app.js`.
- Add browser-oriented E2E coverage for share, feedback, resume, and PWA flows.
- Complete manual QA for mobile CTA, OGP previews, and install/update behavior.

## Guardrails

- Do not change question selection behavior or diagnosis thresholds during refactor PRs.
- Keep public API response shapes compatible unless a migration PR explicitly says otherwise.
- Prefer moving code behind adapters before deleting compatibility wrappers.
- Run `git diff --check`, `node --check static/app.js`, and `pytest` after each refactor unit.
