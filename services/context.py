from types import SimpleNamespace


def build_seo_context(**kwargs):
    return SimpleNamespace(**kwargs)


def build_game_context(**kwargs):
    return SimpleNamespace(**kwargs)


def build_inference_context(**kwargs):
    return SimpleNamespace(**kwargs)


def build_admin_context(**kwargs):
    return SimpleNamespace(**kwargs)


def build_system_context(**kwargs):
    return SimpleNamespace(**kwargs)
