# QA Execution Log

最終更新: 2026-05-23

## Automated Checks

| Area | Command / Check | Status | Notes |
| --- | --- | --- | --- |
| Python/API smoke | `pytest` | Passed locally | Flask smoke, service tests, API regression paths |
| Static JS syntax | `node --check static/*.js` equivalent list | Passed locally | No browser runtime dependency added |
| Whitespace/diff safety | `git diff --check` | Passed locally | Commit-by-commit refactor checks |
| Context builder services | `pytest tests/test_services.py` via full `pytest` | Passed locally | Admin/system/game/SEO builders and context flattener covered |
| Flask runtime bundle | Full `pytest` | Passed locally | Rate limit, confirm, CSRF, and admin guard bundle covered |
| Filesystem bundle | Full `pytest` | Passed locally | Matrix backup, admin, and system context path dependencies covered |
| Bootstrap/config wiring | Full `pytest` | Passed locally | App bootstrap bundle and factory rename covered by route smoke tests |

## QA Run - 2026-05-23 Local Route/API Smoke

| Area | Item | Status | Environment | Notes |
| --- | --- | --- | --- | --- |
| OGP | `/ogp.png?f=QA&p=88` | Passed | Flask test client | Status 200, `image/png`, valid PNG signature |
| PWA | `/manifest.json` | Passed | Flask test client | Status 200, manifest JSON includes `start_url` |
| PWA | `/sw.js` | Passed | Flask test client | Status 200, service worker markers present |
| PWA | `/offline` | Passed | Flask test client | Status 200, offline page body present |
| Result Share | `/r?f=QA&p=88&d=desc` | Passed | Flask test client | Result page includes PNG OGP URL and share/feedback markers |
| Resume | `/api/start` then `/api/resume` | Passed | Flask test client session | Resume accepted a recorded answer without API error |
| Feedback | `/api/confirm` | Passed | Flask test client session | Feedback API returned a status payload after simulated result session |
| Mobile CTA | Touch target and wrapping | Blocked | Requires iOS Safari / Android Chrome | TODO: run real-device tap and long-name wrapping procedure below |
| Native Share | Web Share sheet | Blocked | Requires iOS Safari / Android Chrome | TODO: verify native share sheet and fallback behavior on devices |
| OGP Preview | X / LINE / Discord unfurl | Blocked | Requires deployed public URL and external crawlers | TODO: paste deployed `/r?...` URL into each preview surface and confirm PNG card |
| PWA | Install/update lifecycle | Blocked | Requires real browser profile / installed PWA | TODO: verify install prompt and service worker update behavior on mobile browsers |

### QA Run Notes

No critical bug was found in the locally verifiable route/API checks. The remaining blocked items require a real mobile browser, installed PWA lifecycle, or public URL crawled by X/LINE/Discord, so they were not marked as passed in this environment.

## Manual QA Remaining After Engine Planning

| Area | Status | Next Action |
| --- | --- | --- |
| Mobile CTA | Still blocked | Run iOS Safari and Android Chrome tap/wrapping procedure on real devices |
| Native Share | Still blocked | Verify Web Share sheet and fallback behavior on real devices |
| OGP Preview | Still blocked | Use a deployed public URL in X, LINE, and Discord preview surfaces |
| PWA install/update | Still blocked | Verify install and service worker update lifecycle in real browser profiles |

Engine package planning did not change runtime behavior, so no additional manual QA category is required for this documentation-only step.

## Manual QA Backlog

| Area | Item | Status | Required Environment | Notes |
| --- | --- | --- | --- | --- |
| Mobile CTA | Result CTA tap target and long-name wrapping | Not run | iOS Safari / Android Chrome | Requires real viewport/touch validation |
| Native Share | Share sheet behavior | Not run | iOS Safari / Android Chrome | Cannot be verified by Flask smoke tests |
| OGP Preview | X card preview | Not run | Deployed public URL | Local test verifies metadata route only |
| OGP Preview | LINE preview | Not run | Deployed public URL | External crawler behavior remains manual |
| OGP Preview | Discord unfurl | Not run | Deployed public URL | External crawler behavior remains manual |
| PWA | Install prompt/banner | Not run | Android Chrome / iOS Safari | Browser-specific behavior |
| PWA | Service worker update prompt | Not run | Installed PWA or real browser profile | Needs browser lifecycle validation |

## Decision

Heavy browser automation such as Playwright/Selenium remains intentionally out of scope for refactor PRs. Add it only in a dedicated QA PR after manual gaps justify the dependency.


## Manual QA Procedure

Use a deployed public URL for OGP checks and real mobile browsers for touch/PWA checks. Record each run by changing the relevant backlog row status from `Not run` to `Passed`, `Failed`, or `Blocked`, and add the device/browser/date in Notes.

### Mobile CTA

1. Open the app on iOS Safari and Android Chrome.
2. Complete a diagnosis until the result view appears.
3. Confirm the primary share CTA is visible without scrolling past the result summary.
4. Tap share, retry, continue, quick feedback, and detail feedback controls.
5. Repeat with a long result name and confirm buttons/cards do not overflow.

### Native Share

1. On iOS Safari, tap the primary share CTA and confirm the native share sheet opens.
2. On Android Chrome, repeat the same action.
3. If native share is unavailable, confirm the fallback copy/share behavior is understandable and reachable.

### OGP Preview

1. Open `/r?f=テスト&p=88&d=説明` on the deployed URL.
2. Confirm page source has a PNG `og:image` URL.
3. Paste the URL into X, LINE, and Discord preview surfaces.
4. Confirm title, description, and image render without stale SVG metadata.
5. Repeat with an empty result name and a long Japanese result name.

### PWA

1. Open Android Chrome and confirm install prompt/banner behavior where supported.
2. Open iOS Safari and confirm add-to-home-screen guidance or acceptable fallback.
3. Install the PWA or use an existing install, then deploy a service worker version change.
4. Confirm update prompt/reload behavior does not trap the user on a stale screen.
