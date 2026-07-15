# OGP QA

## Routes

- `/ogp.png?f=テスト&p=88`
- `/ogp?f=テスト&p=88`
- `/r?f=テスト&p=88&d=説明`
- `/fetish/<id>`

## Expected Behavior

- `/ogp.png` returns `image/png`.
- `/ogp` continues returning `image/svg+xml`.
- Shared result pages use the PNG URL in `og:image`.
- Japanese text rendering does not crash even without Japanese fonts.
- If the deployed runtime has no CJK-capable font, `/ogp.png` may fall back to ASCII labels such as `Megane` to avoid mojibake.
- Long names are truncated or wrapped without breaking the image.

## External Preview Checks

- X card validator or manual post preview.
- LINE share preview.
- Discord URL preview.

## Failure Cases

- Empty `f` value.
- Invalid `p` value.
- Very long Japanese name.
- Environment without Pillow.
- Environment without Noto CJK fonts.

## Open Follow-up

- Add a CJK-capable font to the deployment, either by bundling a lightweight Japanese font in the repo or by installing one in the Render build image and setting `OGP_FONT_PATH`. The current ASCII fallback is acceptable for release safety, but Japanese OGP text is still the desired final state.

## Current Automation

- Smoke tests verify `/ogp.png` returns PNG, `/ogp` still returns SVG, and result share pages use PNG `og:image`.
- External X / LINE / Discord preview rendering still requires a deployed URL and manual verification.

## Execution Log

See [`QA.md`](QA.md) for the current automation boundary. Record X / LINE / Discord checks against the deployed URL in the PR or release record.
