def clean_probability(raw):
    try:
        value = max(0, min(float(str(raw)[:8]), 100))
    except (TypeError, ValueError):
        return ''
    return f"{value:.1f}".rstrip('0').rstrip('.')


def _probability_value(prob):
    try:
        return float(prob)
    except (TypeError, ValueError):
        return 0


def result_title(prob):
    return 'あなたの『癖』は……'


def result_rarity(prob):
    return 'AI観測ログ'


def result_share_text(name, prob):
    lines = [
        "あなたの『癖』は……",
        '',
        f"『{name or '???'}』",
    ]
    if prob:
        lines.extend(['', f'AI精度{prob}%'])
    lines.extend(['', '次はあなたの番です……'])
    return '\n'.join(lines)


def result_tagline(name, prob):
    if not name:
        return ''
    return f'AI精度{prob}%' if prob else '観測済み'



def public_base_url(environ, request):
    configured = environ.get('SITE_BASE_URL', '').strip().rstrip('/')
    if configured:
        return configured
    return request.host_url.rstrip('/')
