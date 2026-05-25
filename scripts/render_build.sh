#!/bin/sh
set -eu

# Optional but recommended for Japanese PNG OGP rendering on Render.
# Set DOWNLOAD_OGP_FONT=1 in the Render build environment to fetch Noto Sans CJK.
python scripts/ensure_ogp_font.py || true
pip install -r requirements.txt
