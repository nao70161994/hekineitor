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
    p = _probability_value(prob)
    if p >= 90:
        return 'AIに完全看破された人'
    if p >= 75:
        return '濃厚反応タイプ'
    if p >= 50:
        return '否定しきれない人'
    return '未確認レアタイプ'


def result_rarity(prob):
    p = _probability_value(prob)
    if p >= 90:
        return 'SSR'
    if p >= 75:
        return 'SR'
    if p >= 50:
        return 'R'
    return 'SECRET'


def result_share_text(name, prob):
    p = _probability_value(prob)
    title = result_title(prob)
    rarity = result_rarity(prob)
    if p >= 90:
        return f'へきネイターに性癖を完全看破された。称号「{title}」/ レア度{rarity}: {name} {prob}%'
    if p >= 75:
        return f'へきネイターの診断結果は「{name}」。称号「{title}」/ AI一致率{prob}%。これ当たってる？'
    if p >= 50:
        return f'へきネイターに「{name}」の気配を検出された。称号「{title}」/ AI一致率{prob}%'
    return f'へきネイターに「{name}」って言われた。称号「{title}」。これは当たってる？'


def result_tagline(name, prob):
    if not name:
        return ''
    p = _probability_value(prob)
    title = result_title(prob)
    rarity = result_rarity(prob)
    if p >= 90:
        return f'AI一致率{prob}%、レア度{rarity}。あなたは「{title}」。'
    if p >= 75:
        return f'AIが強く反応。称号は「{title}」、レア度{rarity}。'
    if p >= 50:
        return f'否定しきれない反応あり。称号は「{title}」。'
    return f'AIが少し迷いながら「{name}」を検出。称号は「{title}」。'



def public_base_url(environ, request):
    configured = environ.get('SITE_BASE_URL', '').strip().rstrip('/')
    if configured:
        return configured
    return request.host_url.rstrip('/')
