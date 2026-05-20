def clean_probability(raw):
    try:
        value = max(0, min(float(str(raw)[:8]), 100))
    except (TypeError, ValueError):
        return ''
    return f"{value:.1f}".rstrip('0').rstrip('.')


def result_share_text(name, prob):
    try:
        p = float(prob)
    except (TypeError, ValueError):
        p = 0
    if p >= 90:
        return f"へきネイターに性癖を完全に見破られた: {name} {prob}%"
    if p >= 75:
        return f"へきネイターで診断したら「{name}」だった。これ当たってる？ {prob}%"
    if p >= 50:
        return f"へきネイターの診断結果は「{name}」。否定しきれない {prob}%"
    return f"へきネイターに「{name}」って言われた。これは当たってる？"


def result_tagline(name, prob):
    if not name:
        return ''
    try:
        p = float(prob)
    except (TypeError, ValueError):
        p = 0
    if p >= 90:
        return f"「{name}」がかなり濃く出ています。"
    if p >= 75:
        return f"「{name}」に強く反応するタイプです。"
    if p >= 50:
        return f"「{name}」の気配があります。"
    return f"「{name}」かもしれません。"
