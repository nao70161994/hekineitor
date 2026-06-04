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
    """Return the public origin for SEO/share URLs.

    Set SITE_BASE_URL in production. Without it, production uses the known
    Render origin instead of trusting the request Host header.
    """
    environ = environ or {}
    configured = str(environ.get('SITE_BASE_URL') or '').strip().rstrip('/')
    if configured:
        return configured
    app_env = str(environ.get('APP_ENV') or '').strip().lower()
    if app_env in ('production', 'prod') or environ.get('RENDER'):
        render_url = str(environ.get('RENDER_EXTERNAL_URL') or '').strip().rstrip('/')
        return render_url or 'https://hekineitor.onrender.com'
    return str(getattr(request, 'host_url', '') or '').rstrip('/')
