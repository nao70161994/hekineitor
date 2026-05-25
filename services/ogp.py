import html as _html
import io
import os
import zlib
from services import share as _share

OGP_WIDTH = 1200
OGP_HEIGHT = 630
_OGP_FONT_CACHE = {}

_NAME_FALLBACKS = {
    '眼鏡': 'Megane',
    '白衣': 'Lab Coat',
    '敬語': 'Polite Speech',
    '共依存': 'Codependency',
    '執着': 'Obsession',
    '百合': 'Yuri',
    '触手': 'Tentacles',
    'ケモノ': 'Kemono',
    '吸血鬼': 'Vampire',
    '幼馴染': 'Childhood Friend',
    '溺愛': 'Doting Love',
}


def _ogp_font_candidates():
    env_path = os.environ.get('OGP_FONT_PATH')
    if env_path:
        yield env_path
    for path in (
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc',
        '/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc',
        '/usr/share/fonts/truetype/noto/NotoSansJP-Regular.otf',
        '/usr/share/fonts/opentype/ipafont-gothic/ipagp.ttf',
        '/usr/share/fonts/truetype/fonts-japanese-gothic.ttf',
        '/usr/share/fonts/truetype/vlgothic/VL-Gothic-Regular.ttf',
        '/usr/local/share/fonts/NotoSansCJK-Regular.ttc',
        '/system/fonts/NotoSansCJK-Regular.ttc',
        'static/fonts/NotoSansCJK-Regular.ttc',
        'data/fonts/NotoSansCJK-Regular.ttc',
        'data/fonts/NotoSansCJKjp-Regular.otf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
    ):
        yield path


def _ordered_ogp_font_candidates(bold=False):
    candidates = list(_ogp_font_candidates())
    if not bold:
        return candidates
    ordered = []
    for path in candidates:
        bold_path = path.replace('Regular', 'Bold').replace('DejaVuSans.ttf', 'DejaVuSans-Bold.ttf')
        for candidate in (bold_path, path):
            if candidate not in ordered:
                ordered.append(candidate)
    return ordered


def _load_ogp_font(size, bold=False):
    try:
        from PIL import ImageFont
    except ImportError:
        return None
    key = (size, bold, os.environ.get('OGP_FONT_PATH', ''))
    if key in _OGP_FONT_CACHE:
        return _OGP_FONT_CACHE[key]
    candidates = _ordered_ogp_font_candidates(bold=bold)
    for path in candidates:
        if not path or not os.path.exists(path):
            continue
        try:
            font = ImageFont.truetype(path, size=size)
            _OGP_FONT_CACHE[key] = font
            return font
        except OSError:
            continue
    font = ImageFont.load_default()
    _OGP_FONT_CACHE[key] = font
    return font


def _draw_text_safe(draw, xy, text, **kwargs):
    try:
        draw.text(xy, text, **kwargs)
    except UnicodeEncodeError:
        safe = text.encode('latin-1', 'replace').decode('latin-1')
        draw.text(xy, safe, **kwargs)


def _text_bbox(draw, text, font):
    try:
        return draw.textbbox((0, 0), text, font=font)
    except UnicodeEncodeError:
        safe = text.encode('latin-1', 'replace').decode('latin-1')
        return draw.textbbox((0, 0), safe, font=font)


def _center_text(draw, x, y, text, font, fill):
    bbox = _text_bbox(draw, text, font)
    width = bbox[2] - bbox[0]
    _draw_text_safe(draw, (x - width / 2, y), text, font=font, fill=fill)


def _mask_signature(font, text):
    mask = font.getmask(text)
    return (mask.size, mask.getbbox(), bytes(mask))


def _font_supports_text(font, text):
    if not text or all(ord(char) < 128 for char in text):
        return True
    if font is None or not hasattr(font, 'getmask'):
        return False
    chars = [char for char in str(text) if ord(char) >= 128]
    sample = list(dict.fromkeys(chars[:2] + ['眼', '鏡']))
    if len(sample) < 2:
        sample.append('鏡' if sample != ['鏡'] else '眼')
    try:
        signatures = [_mask_signature(font, char) for char in sample[:2]]
    except Exception:
        return False
    return signatures[0] != signatures[1]


def _font_source(font):
    return getattr(font, 'path', '') or getattr(font, 'font', None) and getattr(font.font, 'family', '') or ''


def cjk_font_status():
    font = _load_ogp_font(32)
    available = _font_supports_text(font, 'へきネイター眼鏡')
    source = _font_source(font)
    if available:
        detail = f'CJK-capable font available: {source or "unknown source"}'
    else:
        detail = 'CJK-capable font not found; run scripts/ensure_ogp_font.py during build or set OGP_FONT_PATH to a Japanese font'
    return {'available': available, 'source': source, 'detail': detail}


def _ascii_name_fallback(name):
    name = str(name or '').strip()
    if not name:
        return 'Unknown'
    if all(ord(char) < 128 for char in name):
        return name
    return _NAME_FALLBACKS.get(name, 'Heki Result')


def _ogp_texts(name, prob, cjk_supported=True):
    if cjk_supported:
        return {
            'label': "あなたの『癖』は……",
            'name': name or '???',
            'prob': f'AI精度 {prob}%' if prob else '',
            'title': '',
            'side': '次はあなたの番です……',
            'mark': 'AI',
            'mark_sub': '観測ログ',
            'tagline': '',
        }
    return {
        'label': 'Your observed pattern is...',
        'name': _ascii_name_fallback(name),
        'prob': f'AI Precision {prob}%' if prob else '',
        'title': '',
        'side': 'Next observation: you.',
        'mark': 'AI',
        'mark_sub': 'LOG',
        'tagline': '',
    }


def _split_ogp_name(name):
    if len(name) > 12:
        line1, line2 = name[:12], name[12:24]
        if len(name) > 24:
            line2 = name[12:23] + '...'
        return [line1, line2]
    return [name]


def _png_chunk(kind, data):
    body = kind + data
    return len(data).to_bytes(4, 'big') + body + zlib.crc32(body).to_bytes(4, 'big')


def _minimal_png(width=OGP_WIDTH, height=OGP_HEIGHT):
    row = b'\x00' + b'\x0d\x1b\x2a' * width
    raw = row * height
    return (
        b'\x89PNG\r\n\x1a\n'
        + _png_chunk(b'IHDR', width.to_bytes(4, 'big') + height.to_bytes(4, 'big') + b'\x08\x02\x00\x00\x00')
        + _png_chunk(b'IDAT', zlib.compress(raw, 6))
        + _png_chunk(b'IEND', b'')
    )


def generate_png(name, prob):
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return _minimal_png()

    try:
        prob_val = max(0, min(float(prob), 100)) if prob else 0
    except ValueError:
        prob_val = 0
    bar_color = (185, 202, 224)

    img = Image.new('RGB', (OGP_WIDTH, OGP_HEIGHT), (9, 16, 27))
    draw = ImageDraw.Draw(img)
    for y in range(OGP_HEIGHT):
        mix = y / OGP_HEIGHT
        color = (
            int(9 + (15 - 9) * mix),
            int(16 + (24 - 16) * mix),
            int(27 + (42 - 27) * mix),
        )
        draw.line((0, y, OGP_WIDTH, y), fill=color)

    label_font = _load_ogp_font(38)
    name_font_size = 86 if len(name) <= 8 else 70
    name_font = _load_ogp_font(name_font_size, bold=True)
    prob_font = _load_ogp_font(42)
    side_font = _load_ogp_font(28)
    small_font = _load_ogp_font(18)

    cjk_supported = _font_supports_text(name_font, '眼鏡') and _font_supports_text(label_font, 'へきネイター')
    texts = _ogp_texts(name, prob, cjk_supported=cjk_supported)

    _center_text(draw, 600, 105, texts['label'], label_font, (164, 176, 194))
    lines = _split_ogp_name(texts['name'])
    y1 = 245 if len(lines) > 1 else 278
    for i, line in enumerate(lines):
        _center_text(draw, 600, y1 + i * (name_font_size + 12), line, name_font, (238, 242, 247))
    if prob:
        prob_y = y1 + len(lines) * (name_font_size + 12) + 26
        _center_text(draw, 600, prob_y, texts['prob'], prob_font, bar_color)
    _center_text(draw, 600, 520, texts['side'], side_font, (96, 108, 128))
    _center_text(draw, 600, 565, 'hekineitor.onrender.com', small_font, (58, 69, 86))

    buf = io.BytesIO()
    img.save(buf, format='PNG', optimize=True)
    return buf.getvalue()


def render_svg(name, prob):
    """診断結果のOGP画像をSVGで動的生成する（1200×630 Twitter推奨サイズ）。"""
    name = (name or '???')[:30]
    prob = (prob or '')[:5]
    try:
        bar_w = max(8, min(int(float(prob) * 5.6), 560)) if prob else 0
        prob_val = float(prob) if prob else 0
    except ValueError:
        bar_w = 0
        prob_val = 0
    # 名前の折り返し（12文字で改行）
    if len(name) > 12:
        line1, line2 = name[:12], name[12:24]
        if len(name) > 24:
            line2 = name[12:23] + '…'
    else:
        line1, line2 = name, ''
    line1 = _html.escape(line1, quote=False)
    line2 = _html.escape(line2, quote=False)
    prob_text = _html.escape(prob, quote=False)
    fs_name = 72 if len(line1) <= 8 else 60
    y1 = 260 if line2 else 290
    y2 = y1 + fs_name + 12
    bar_color = '#f5a623' if prob_val >= 75 else ('#e94560' if prob_val >= 50 else '#5b8dd9')
    svg = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#09101b"/>
      <stop offset="100%" stop-color="#0f182a"/>
    </linearGradient>
  </defs>
  <rect width="1200" height="630" fill="url(#bg)"/>
  <text x="600" y="120" text-anchor="middle" font-family="sans-serif" font-size="38" fill="#a4b0c2">あなたの『癖』は……</text>
  <text x="600" y="{y1}" text-anchor="middle" font-family="sans-serif" font-size="{fs_name}" font-weight="bold" fill="#eef2f7">{line1}</text>
  {'<text x="600" y="' + str(y2) + '" text-anchor="middle" font-family="sans-serif" font-size="' + str(fs_name) + '" font-weight="bold" fill="#eef2f7">' + line2 + '</text>' if line2 else ''}
  {'<text x="600" y="' + str((y2 if line2 else y1)+80) + '" text-anchor="middle" font-family="sans-serif" font-size="42" fill="#b9cae0">AI精度 ' + prob_text + '%</text>' if prob else ''}
  <text x="600" y="525" text-anchor="middle" font-family="sans-serif" font-size="28" fill="#607086">次はあなたの番です……</text>
  <text x="600" y="570" text-anchor="middle" font-family="sans-serif" font-size="18" fill="#3a4657">hekineitor.onrender.com</text>
</svg>'''
    return svg
