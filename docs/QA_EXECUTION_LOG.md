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


## QA Run - 2026-05-23 Engine Package Rehearsal

| Area | Command / Check | Status | Environment | Notes |
| --- | --- | --- | --- | --- |
| Import target | `git status --short` | Passed | Local shell | Working tree clean before rehearsal commands |
| Import target | `python3 -c "import engine, os; print(os.path.abspath(engine.__file__))"` | Passed | Local shell | Resolved to `/home/hekineitor/engine.py` |
| Import target | `python3 -c "import importlib.util; spec = importlib.util.find_spec('engine'); print(spec.origin, spec.submodule_search_locations)"` | Passed | Local shell | Resolved to `/home/hekineitor/engine.py None` |
| Import target | `test ! -d engine` | Passed | Local shell | No `engine/` package directory exists in prep state |
| Focused contract | `python3 -m pytest tests/test_engine_package_switch_guard.py tests/test_engine_public_api_contract.py tests/test_engine_facade_contract.py` | Passed | Local pytest | 28 passed |
| Behavior lock | `python3 -m pytest tests/test_engine_inference_regression.py tests/test_engine_question_selection_regression.py tests/test_engine_persistence_regression.py tests/test_engine_mutations.py tests/test_engine_db.py` | Passed | Local pytest | 42 passed |

### Engine Package Rehearsal Notes

The package switch itself was not performed. This run only confirms the current prep state: `engine` still resolves to `engine.py`, no `engine/` directory exists, public facade contracts pass, and inference/question-selection/persistence/mutation/DB behavior locks pass.


## QA Run - 2026-05-23 Engine Package Atomic Switch

| Area | Command / Check | Status | Environment | Notes |
| --- | --- | --- | --- | --- |
| Import target | `import engine` | Passed | Local shell | Resolved to `engine/__init__.py` |
| Public compatibility | `from engine import Engine, _use_db, parse_work_item` | Passed | Local shell | Historical import and patch points available through package facade |
| Focused contract | `python3 -m pytest tests/test_engine_package_switch_guard.py tests/test_engine_public_api_contract.py tests/test_engine_facade_contract.py` | Passed | Local pytest | 29 passed after package switch |
| Behavior lock | `python3 -m pytest tests/test_engine_inference_regression.py tests/test_engine_question_selection_regression.py tests/test_engine_persistence_regression.py tests/test_engine_mutations.py tests/test_engine_db.py` | Passed | Local pytest | 42 passed after package switch |

### Engine Package Atomic Switch Notes

The public `engine` import target is now the `engine/` package. `engine/facade.py` contains the migrated facade source, and `engine/__init__.py` executes that source in the package namespace so existing patch points such as `engine._use_db` and `engine.threading.Thread` continue to affect `Engine` method globals.

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

## Automated QA Run - 2026-05-25 Release Hardening

| Area | Command / Check | Status | Environment | Notes |
| --- | --- | --- | --- | --- |
| Feedback learning guards | `pytest tests/test_app.py -q` | Passed | Local pytest | Duplicate confirm/wrong, finalize ID limits, unverified resume learning skip, compound guessed logging, and public accuracy denominator covered. |
| Admin/export guards | `pytest tests/test_services.py tests/test_script_safety.py tests/test_app.py -q` | Passed | Local pytest | CSV formula escaping, config validation, health/preflight env fallback, audit redaction, restore workflow CSRF/artifact checks covered. |
| Client smoke guards | `pytest tests/test_smoke.py tests/test_script_safety.py -q` | Passed | Local pytest | Draft/back sync markers, X share action, safer PWA SW install/update, and CI JS check markers covered. |
| JS syntax | `for js in static/*.js; do node --check "$js"; done` | Passed | Local Node | Static JS syntax verified. |
| DB stale reload | `pytest tests/test_engine_facade_contract.py tests/test_engine_inference_regression.py -q` | Passed | Local pytest | Fetish list refresh before DB matrix reload covered. |

Manual mobile/OGP/PWA QA is still required on deployed devices/services because these fixes were validated with static/smoke tests only.

## Automated QA Run - 2026-05-25 OGP/Restore Follow-up

| Area | Command / Check | Status | Environment | Notes |
| --- | --- | --- | --- | --- |
| OGP font diagnostics | `pytest tests/test_app.py::TestAPI::test_preflight_includes_ogp_font_check tests/test_services.py::TestServices::test_ogp_cjk_font_status_shape_and_android_candidate -q` | Passed | Local pytest | Preflight exposes CJK font status and OGP candidate list includes additional CJK locations. |
| Matrix restore player fetish recovery | `pytest tests/test_app.py::TestAPI::test_import_matrix_dry_run_reports_missing_player_fetishes tests/test_app.py::TestAPI::test_restore_matrix_backup_restores_missing_player_fetishes tests/test_engine_facade_contract.py::TestEnginePersistenceFacadeContract::test_restore_player_fetishes_adds_missing_player_rows_only -q` | Passed | Local pytest | Import/dry-run/backup restore now validates exported player-added fetishes against the prospective restored set and restores missing player rows before matrix import. |

Manual verification is still required after setting `OGP_FONT_PATH` on Render to confirm `/ogp.png?f=眼鏡&p=88` renders Japanese instead of ASCII fallback.


## QA Run - 2026-05-26 Twitter/X Release Smoke

| Area | Command / Check | Status | Environment | Notes |
| --- | --- | --- | --- | --- |
| Health | `GET https://hekineitor.onrender.com/health` | Passed | Production public URL | `status=ok`, `storage=postgres`, `fetishes=132`, `questions=135`, `matrix.ok=true`, `rows=132`, `cols=135`. |
| Home | `GET /` | Passed | Production public URL | HTML loaded successfully. |
| Start API | `POST /api/start` | Passed | Production public URL | JSON response included `question_id` and `question`. |
| Fetish index | `GET /fetishes` | Passed | Production public URL | Page loaded and included `/fetish/` detail links. |
| Fetish detail | `GET /fetish/0` | Passed | Production public URL | Detail page loaded and included `おすすめ作品`. |
| Works restore spot check | Full public `/fetish/<id>` scan | Passed | Production public URL | 128 public detail pages have `おすすめ作品`; fallback-only pages: 0; recommendation links: 380; affiliate-tagged recommendation links: 380. |
| OGP PNG | `GET /ogp.png?f=眼鏡&p=88` | Passed | Production public URL | Returned PNG, `1200x630`, `image/png`. Manual visual inspection in X/LINE/Discord remains required. |
| Result share page | `GET /r?f=眼鏡&p=88&d=テスト` | Passed | Production public URL | Page loaded with `og:image` pointing to PNG OGP. |
| Manifest | `GET /manifest.json` | Passed | Production public URL | Manifest loaded; app name is `へきネイター`. |
| Service worker | `GET /sw.js` | Passed | Production public URL | JavaScript loaded successfully. Browser install/update lifecycle remains manual. |
| Offline page | `GET /offline` | Passed | Production public URL | Offline HTML loaded successfully. |
| Admin preflight auth guard | `GET /api/admin/preflight` without credentials | Passed | Production public URL | Returned `401 Unauthorized` as expected. Normal admin response requires credentials in browser. |
| Admin preflight normal path | Flask test client `GET /api/admin/preflight` | Passed with warning | Local test client | Route responded `200`; local shell reported `warning` because local QA env lacks production-equivalent settings. Production preflight should be checked in the admin browser before launch. |
| Test play start | Flask test client `POST /admin/test_play/start` with admin auth + CSRF | Passed | Local test client | Returned `302 /`; admin page showed `学習OFFテストプレイ中`; audit row appeared. |
| Test play stop | Flask test client `POST /admin/test_play/stop` with admin auth + CSRF | Passed | Local test client | Returned `302 /admin`; admin page returned to `通常モード`; audit row appeared. |
| Audit log display/API | Admin page and `GET /api/admin/audit_log` | Passed | Local test client | Start/stop events were present in page/audit API. |

### Release Smoke Notes

No critical bug was found in automated production smoke checks or local admin workflow checks. The production admin preflight normal path, external SNS unfurls, native share sheets, and PWA install/update lifecycle still require a logged-in administrator and real browser/device surfaces.

### Human Checks Before Twitter/X Announcement

| Area | Status | Required Human Check |
| --- | --- | --- |
| Admin preflight | Not run with production credentials by Codex | Open `/api/admin/preflight` from the production admin browser and confirm `status=ok`. |
| OGP Preview | Not run in external apps by Codex | Paste `/r?f=眼鏡&p=88&d=テスト` into X, LINE, and Discord and confirm the PNG card text/image. |
| Native Share | Not run by Codex | Complete a diagnosis on iOS Safari / Android Chrome and confirm native share or fallback copy works. |
| PWA install/update | Not run by Codex | Verify install/offline/update behavior in a real browser profile. |
| Mobile tap/wrapping | Not run by Codex | Confirm result CTA, works links, and long result names do not overflow on a physical phone. |
