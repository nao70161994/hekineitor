# OGP Japanese Font Setup

`/ogp.png` uses Pillow. If the runtime does not have a Japanese/CJK capable font,
the PNG generator intentionally falls back to ASCII labels such as `Megane` to avoid mojibake.

## How To Verify

1. Open the admin preflight page or call `/api/admin/preflight`.
2. Check `ogp_cjk_font_available`.
3. If it is `false`, `/ogp.png?f=眼鏡&p=88` will use ASCII fallback text.

## Recommended Production Fix

Provide a CJK font and point `OGP_FONT_PATH` at it. Recommended fonts:

- `NotoSansCJK-Regular.ttc`
- `NotoSansJP-Regular.otf`
- `VL-Gothic-Regular.ttf`
- `fonts-japanese-gothic.ttf`

Example environment variable:

```text
OGP_FONT_PATH=/opt/render/project/src/data/fonts/NotoSansCJK-Regular.ttc
```

The app also searches common Linux/Android paths automatically, but Render's default image may not include CJK fonts.

## Render Build Option

Use the bundled build helper when you want the deploy to fetch a font automatically:

```text
Build Command: DOWNLOAD_OGP_FONT=1 sh scripts/render_build.sh
```

The script stores the downloaded font at `data/fonts/NotoSansCJKjp-Regular.otf`, which is included in the OGP font search path.

If you already provide a font as a secret file or persistent disk file, keep the normal build command and set:

```text
OGP_FONT_PATH=/path/to/NotoSansCJKjp-Regular.otf
```
