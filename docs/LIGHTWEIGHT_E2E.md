# Lightweight E2E Strategy

## Scope

Use layered checks: Flask test-client smoke for server contracts, Vitest for client state transitions, and one minimal Playwright path for browser integration. Keep browser coverage narrow so CI remains fast and deterministic.

## Covered Paths

- Start -> answer -> result API flow.
- Resume, back, and continue API paths.
- Quick feedback and detail feedback route contracts.
- Share page metadata and PNG OGP route.
- Legacy SVG OGP route.
- Manifest, service worker, and offline page.
- Client compatibility exports after wrapper reduction.
- Client state and error transitions under `tests/js/`.
- Start-page browser rendering and bootstrap under `tests/browser/`.

## Manual QA Still Required

- Native share sheet behavior on iOS Safari and Android Chrome.
- LINE, X, and Discord unfurl previews against a deployed URL.
- PWA install prompt and service worker update prompt on real devices.
- Tap target sizing and long result-name wrapping on narrow mobile viewports.

## Browser Automation Boundary

Playwright verifies only the high-value integration path that cannot be proven by isolated unit tests. Add browser cases for cross-module or browser-runtime contracts; keep pure state and error handling in Vitest. Native share sheets, third-party previews, and installed-PWA lifecycle remain manual because CI cannot reproduce those external environments faithfully.

## Execution Log

Current commands and the manual backlog are tracked in [`QA.md`](QA.md). Historical runs are archived and do not represent the current branch state.
