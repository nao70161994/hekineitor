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
            'label': 'へきネイター診断結果',
            'name': name or '???',
            'prob': f'AI一致率 {prob}%' if prob else '',
            'title': f'{_share.result_rarity(prob)} / {_share.result_title(prob)}' if prob else '',
            'side': '友達にも踏ませる？',
            'tagline': 'AIが性癖プロファイルを推定',
        }
    return {
        'label': 'Hekineitor Result',
        'name': _ascii_name_fallback(name),
        'prob': f'AI Match {prob}%' if prob else '',
        'title': _share.result_rarity(prob) if prob else '',
        'side': 'Share this result?',
        'tagline': 'AI profile diagnosis',
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
    bar_w = int(max(8, min(prob_val * 5.6, 560))) if prob else 0
    bar_color = (245, 166, 35) if prob_val >= 75 else ((233, 69, 96) if prob_val >= 50 else (91, 141, 217))

    img = Image.new('RGB', (OGP_WIDTH, OGP_HEIGHT), (13, 27, 42))
    draw = ImageDraw.Draw(img)
    for y in range(OGP_HEIGHT):
        mix = y / OGP_HEIGHT
        color = (
            int(13 + (22 - 13) * mix),
            int(27 + (33 - 27) * mix),
            int(42 + (62 - 42) * mix),
        )
        draw.line((0, y, OGP_WIDTH, y), fill=color)
    for x in range(OGP_WIDTH):
        mix = x / OGP_WIDTH
        color = (int(233 + (245 - 233) * mix), int(69 + (166 - 69) * mix), int(96 + (35 - 96) * mix))
        draw.line((x, 0, x, 7), fill=color)

    draw.rounded_rectangle((60, 60, 640, 570), radius=20, fill=(31, 30, 54), outline=(96, 40, 68), width=2)
    draw.rounded_rectangle((680, 60, 1140, 570), radius=20, fill=(10, 15, 30), outline=(32, 41, 65), width=2)

    label_font = _load_ogp_font(28)
    name_font_size = 72 if len(name) <= 8 else 60
    name_font = _load_ogp_font(name_font_size, bold=True)
    prob_font = _load_ogp_font(36)
    side_font = _load_ogp_font(24)
    small_font = _load_ogp_font(18)
    mark_font = _load_ogp_font(80, bold=True)

    cjk_supported = _font_supports_text(name_font, '眼鏡') and _font_supports_text(label_font, 'へきネイター')
    texts = _ogp_texts(name, prob, cjk_supported=cjk_supported)

    _center_text(draw, 350, 100, texts['label'], label_font, (170, 170, 180))
    lines = _split_ogp_name(texts['name'])
    y1 = 235 if len(lines) > 1 else 270
    for i, line in enumerate(lines):
        _center_text(draw, 350, y1 + i * (name_font_size + 12), line, name_font, (233, 69, 96))
    if prob:
        prob_y = y1 + len(lines) * (name_font_size + 12) + 20
        _center_text(draw, 350, prob_y, texts['prob'], prob_font, bar_color)
        _center_text(draw, 350, prob_y + 50, texts['title'], side_font, (230, 218, 190))
    draw.rounded_rectangle((130, 490, 570, 502), radius=6, fill=(26, 26, 62))
    if bar_w:
        draw.rounded_rectangle((130, 490, 130 + bar_w, 502), radius=6, fill=(233, 69, 96))

    _center_text(draw, 910, 145, texts['side'], side_font, (120, 130, 150))
    _center_text(draw, 910, 275, '?', mark_font, (80, 42, 65))
    _center_text(draw, 910, 430, 'hekineitor.onrender.com', small_font, (90, 93, 105))
    _center_text(draw, 910, 465, texts['tagline'], small_font, (75, 78, 90))

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
    <linearGradient id="bg" x1="0" y1="0" x2="0.6" y2="1">
      <stop offset="0%" stop-color="#0d1b2a"/>
      <stop offset="100%" stop-color="#16213e"/>
    </linearGradient>
    <linearGradient id="bar" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stop-color="#e94560"/>
      <stop offset="100%" stop-color="#f5a623"/>
    </linearGradient>
    <linearGradient id="accent" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stop-color="#e94560" stop-opacity="0.15"/>
      <stop offset="100%" stop-color="#f5a623" stop-opacity="0.05"/>
    </linearGradient>
  </defs>
  <rect width="1200" height="630" fill="url(#bg)"/>
  <rect x="0" y="0" width="1200" height="8" fill="url(#bar)"/>
  <rect x="60" y="60" width="580" height="510" rx="20" fill="url(#accent)"/>
  <rect x="60" y="60" width="580" height="510" rx="20" fill="none" stroke="#e94560" stroke-width="1" stroke-opacity="0.3"/>
  <text x="350" y="130" text-anchor="middle" font-family="sans-serif" font-size="28" fill="#888">🔮 へきネイター診断結果</text>
  <text x="350" y="{y1}" text-anchor="middle" font-family="sans-serif" font-size="{fs_name}" font-weight="bold" fill="#e94560">{line1}</text>
  {'<text x="350" y="' + str(y2) + '" text-anchor="middle" font-family="sans-serif" font-size="' + str(fs_name) + '" font-weight="bold" fill="#e94560">' + line2 + '</text>' if line2 else ''}
  {'<text x="350" y="' + str((y2 if line2 else y1)+70) + '" text-anchor="middle" font-family="sans-serif" font-size="36" fill="' + bar_color + '">AI一致率 ' + prob_text + '%</text>' if prob else ''}
  <rect x="130" y="490" width="440" height="12" rx="6" fill="#1a1a3e"/>
  <rect x="130" y="490" width="{bar_w}" height="12" rx="6" fill="url(#bar)"/>
  <rect x="680" y="60" width="460" height="510" rx="20" fill="#0a0f1e" fill-opacity="0.6"/>
  <text x="910" y="160" text-anchor="middle" font-family="sans-serif" font-size="24" fill="#555">友達にも踏ませる？</text>
  <text x="910" y="320" text-anchor="middle" font-family="sans-serif" font-size="80" fill="#e94560" opacity="0.15">?</text>
  <text x="910" y="440" text-anchor="middle" font-family="sans-serif" font-size="20" fill="#444">hekineitor.onrender.com</text>
  <text x="910" y="480" text-anchor="middle" font-family="sans-serif" font-size="16" fill="#333">AIが性癖プロファイルを推定</text>
</svg>'''
    return svg
