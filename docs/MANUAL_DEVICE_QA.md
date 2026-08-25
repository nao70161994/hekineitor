# Manual Device QA

This checklist is only for items that cannot be fully verified by HTTP smoke tests. Automated production checks cover `/health`, `/`, `/api/start`, `/fetishes`, `/fetish/<id>`, `/r`, `/ogp.png`, `/manifest.json`, `/sw.js`, `/offline`, and unauthenticated admin guards.

Production base URL: `https://hekineitor.onrender.com`

## Automated boundary (2026-08-26)

`PYTHONPATH=. python scripts/public_experience_check.py`で、公開health、UI・privacy契約、通常UA・Twitterbot・Discordbotのmeta一致、HTTPS PNG参照、1200×630 PNG、manifest、service worker、offline、Web Vitals scriptを検査します。Linux Chromiumではaxe、keyboard、320px、400%文字拡大、offline/resume/share fallbackと開始・質問・結果のvisual baselineを検査します。PNGは`眼鏡`を含む日本語が読めることも目視済みです。以下には、外部アプリの実描画、OSのshare sheet、実browser profileのinstall/update状態、物理端末のscreen readerなど、自動HTTP・Chromium検証で代替できない項目だけを記録します。

## X OGP Card

- Confirmation URL: `https://hekineitor.onrender.com/r?f=%E7%9C%BC%E9%8F%A1&p=88&d=%E3%83%86%E3%82%B9%E3%83%88`
- Steps:
  1. Open X compose or DM on a logged-in account.
  2. Paste the confirmation URL.
  3. Wait for the card preview to render.
  4. Confirm the image, title, and description before posting.
- Expected result:
  - A large summary card appears.
  - The card image is a PNG result image.
  - Japanese text, including `眼鏡`, is readable and not mojibake.
  - The card title is result-oriented, not a generic home-page title.
- Possible causes if NG:
  - X cache still has stale metadata.
  - OGP crawler has not refreshed the URL.
  - `og:image` URL is blocked or slow.
  - Render instance was cold-starting during the crawl.
  - CJK font path is missing in production.
- Fix candidates:
  - Retry with a cache-busting result URL or a different `d=` value.
  - Confirm `/r?...` source contains `og:image` pointing to `/ogp.png`.
  - Confirm `/ogp.png?f=眼鏡&p=88` returns a readable PNG in browser.
  - Check `/api/admin/preflight` for `ogp_cjk_font_available`.
- Record:
  - Date/time:
  - Device/browser/app:
  - Result: Passed / Failed / Blocked
  - Notes:

## LINE OGP Card

- Confirmation URL: `https://hekineitor.onrender.com/r?f=%E7%9C%BC%E9%8F%A1&p=88&d=%E3%83%86%E3%82%B9%E3%83%88`
- Steps:
  1. Open LINE on iPhone or Android.
  2. Paste the URL into a private chat or Keep memo.
  3. Wait for the preview card.
  4. Do not send publicly unless the preview is correct.
- Expected result:
  - LINE shows a card with title, description, and PNG image.
  - Japanese text is readable.
  - Tapping the card opens the result share page.
- Possible causes if NG:
  - LINE crawler cache is stale.
  - LINE delays preview generation.
  - Image fetch timed out during Render cold start.
  - OGP image is too large or temporarily unavailable.
- Fix candidates:
  - Open `/ogp.png?f=眼鏡&p=88` once in browser to warm Render.
  - Retry with a fresh `/r?...` URL.
  - Confirm `og:image:width=1200` and `og:image:height=630` are present.
- Record:
  - Date/time:
  - Device/browser/app:
  - Result: Passed / Failed / Blocked
  - Notes:

## Discord OGP Card

- Confirmation URL: `https://hekineitor.onrender.com/r?f=%E7%9C%BC%E9%8F%A1&p=88&d=%E3%83%86%E3%82%B9%E3%83%88`
- Steps:
  1. Paste the URL into a private Discord channel or self-test server.
  2. Wait for the embed preview.
  3. Confirm image and text rendering.
- Expected result:
  - Discord embed contains the result title and PNG image.
  - Japanese text is readable.
  - No stale SVG image appears.
- Possible causes if NG:
  - Discord cached a previous card.
  - `og:image` fetch failed due to transient Render latency.
  - Metadata changed but crawler has not refreshed.
- Fix candidates:
  - Retry with a unique query string on `/r`.
  - Confirm `/r?...` page source and `/ogp.png?...` response.
- Record:
  - Date/time:
  - Device/browser/app:
  - Result: Passed / Failed / Blocked
  - Notes:

## iPhone Web Share

- Confirmation URL: `https://hekineitor.onrender.com/`
- Steps:
  1. Open the app in iOS Safari.
  2. Complete a diagnosis until the result screen.
  3. Tap the primary share CTA.
  4. Confirm the native share sheet opens.
  5. Cancel once, then try the fallback copy/share option if shown.
- Expected result:
  - The share button is visible and easy to tap.
  - The iOS share sheet opens with result text and URL.
  - Cancelling share does not break the result screen.
- Possible causes if NG:
  - Browser does not expose `navigator.share` for the context.
  - The page is not HTTPS or share payload is invalid.
  - The button is covered by another element or too close to viewport edge.
- Fix candidates:
  - Verify HTTPS URL.
  - Fall back to copy URL/text path.
  - Adjust only CTA spacing/tap target if needed.
- Record:
  - Date/time:
  - Device/browser:
  - Result: Passed / Failed / Blocked
  - Notes:

## Android Web Share

- Confirmation URL: `https://hekineitor.onrender.com/`
- Steps:
  1. Open the app in Android Chrome.
  2. Complete a diagnosis.
  3. Tap the primary share CTA.
  4. Confirm Android's share sheet opens.
  5. Cancel and confirm fallback behavior still works.
- Expected result:
  - Native share opens.
  - Result text and URL are present.
  - The result screen remains usable after cancel.
- Possible causes if NG:
  - `navigator.share` unavailable in the browser/profile.
  - Share payload too long or invalid.
  - A JS error interrupted the CTA handler.
- Fix candidates:
  - Check browser console if available.
  - Use fallback copy path.
  - Keep share text concise.
- Record:
  - Date/time:
  - Device/browser:
  - Result: Passed / Failed / Blocked
  - Notes:

## Result Screenshot Appeal

- Confirmation URL: `https://hekineitor.onrender.com/`
- Steps:
  1. Complete a diagnosis on iPhone and Android.
  2. Stop on the result screen.
  3. 初期表示で結果名、短い説明、一致度、quick feedback、共有、再プレイが読み取れることを確認する。
  4. 「結果を詳しく見る」を開き、根拠、候補比較、関連ジャンル、おすすめ作品、詳細評価を確認する。
  5. 「もう一度遊ぶ」を開き、追加質問、当て直し、タイトルへ戻るを確認する。
- Expected result:
  - 初期表示だけで結果を理解・評価でき、詳細情報は閉じている。
  - 展開ボタンはkeyboardで操作でき、`aria-expanded`と表示状態が一致する。
  - 共有CTAは1つだけで、詳細を開かなくても見つかる。
  - 320〜375px幅で文字や操作が重ならない。
- Possible causes if NG:
  - Result name is too long.
  - Viewport-specific spacing pushes CTA too low.
  - Dynamic text overflows a fixed-width area.
- Fix candidates:
  - Add responsive wrapping for long names.
  - Reduce result card vertical spacing only if needed.
  - Keep visual changes small and scoped.
- Record:
  - Date/time:
  - Device/browser:
  - Result: Passed / Failed / Blocked
  - Screenshot saved: Yes / No
  - Notes:

## Works Link Tap Targets

- Confirmation URLs:
  - `https://hekineitor.onrender.com/fetishes`
  - `https://hekineitor.onrender.com/fetish/0`
  - `https://hekineitor.onrender.com/fetish/126`
- Steps:
  1. Open the fetish index on a phone.
  2. Tap a fetish card and confirm it navigates to detail.
  3. On detail pages, tap each `おすすめ作品` tag.
  4. Confirm Amazon opens and the URL contains `tag=hekinator-22`.
- Expected result:
  - Cards remain tappable.
  - Work tags are easy to tap without hitting the card behind them.
  - Amazon links include affiliate tag.
- Possible causes if NG:
  - Nested click handlers conflict between card and work link.
  - Tap target is too small on mobile.
  - Work URL was stored without affiliate tag and normalization failed.
- Fix candidates:
  - Stop event propagation only on nested work links.
  - Increase tag padding slightly.
  - Re-run works link normalization/backfill.
- Record:
  - Date/time:
  - Device/browser:
  - Result: Passed / Failed / Blocked
  - Notes:

## PWA Install / Update / Offline

- Confirmation URLs:
  - `https://hekineitor.onrender.com/manifest.json`
  - `https://hekineitor.onrender.com/sw.js`
  - `https://hekineitor.onrender.com/offline`
  - `https://hekineitor.onrender.com/`
- Steps:
  1. Open the app in Android Chrome or iOS Safari.
  2. 初回開始前にアプリ内install bannerが表示されないことを確認する。
  3. 診断を完走し、その後にinstall案内が表示されることを確認する。
  4. Install the PWA where possible, then enable airplane mode.
  5. Navigate or reload and confirm the offline page or cached app behavior is acceptable.
  6. After a deploy, reopen and confirm update/reload behavior does not trap the old version.
- Expected result:
  - Manifest is accepted and the service worker registers.
  - Install案内はゲーム開始を妨げず、完走後だけ現れる。
  - Service workerの更新通知は完走前でも安全に表示される。
  - Offline route is usable and update does not leave a mixed-version state.
- Possible causes if NG:
  - Browser does not meet install criteria yet.
  - Service worker cache did not update.
  - Offline fallback path is not cached as expected.
  - iOS PWA behavior differs from Android Chrome.
- Fix candidates:
  - Check service worker registration in browser devtools.
  - Bump service worker cache/version if stale.
  - Keep offline route minimal and cacheable.
  - Document iOS-specific fallback if needed.
- Record:
  - Date/time:
  - Device/browser:
  - Result: Passed / Failed / Blocked
  - Installed: Yes / No
  - Notes:
