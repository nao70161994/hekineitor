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

## Current Automation

- Smoke tests verify `/ogp.png` returns PNG, `/ogp` still returns SVG, and result share pages use PNG `og:image`.
- External X / LINE / Discord preview rendering still requires a deployed URL and manual verification.
