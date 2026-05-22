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
