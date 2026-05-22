# Lightweight E2E Strategy

## Scope

Use Flask test-client smoke tests and static JS contract checks as the default E2E layer. This keeps CI fast and avoids adding Playwright/Selenium until a real browser runner is explicitly approved.

## Covered Paths

- Start -> answer -> result API flow.
- Resume, back, and continue API paths.
- Quick feedback and detail feedback route contracts.
- Share page metadata and PNG OGP route.
- Legacy SVG OGP route.
- Manifest, service worker, and offline page.
- Client compatibility exports after wrapper reduction.

## Manual QA Still Required

- Native share sheet behavior on iOS Safari and Android Chrome.
- LINE, X, and Discord unfurl previews against a deployed URL.
- PWA install prompt and service worker update prompt on real devices.
- Tap target sizing and long result-name wrapping on narrow mobile viewports.

## When To Add Browser Automation

Add a real browser runner only when we need to verify DOM layout, native share availability, service worker lifecycle, or mobile viewport interaction. Keep that PR separate from refactors.

## Execution Log

Current automated coverage and manual backlog are tracked in `docs/QA_EXECUTION_LOG.md`.
