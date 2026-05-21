from types import SimpleNamespace


def domain(**kwargs):
    return SimpleNamespace(**kwargs)


def _merge_domains(*domains, **kwargs):
    values = {}
    for item in domains:
        if item is None:
            continue
        values.update(vars(item))
    values.update(kwargs)
    return SimpleNamespace(**values)


def build_seo_context(*domains, **kwargs):
    return _merge_domains(*domains, **kwargs)


def game_runtime(**kwargs):
    return domain(**kwargs)


def game_question_flow(**kwargs):
    return domain(**kwargs)


def game_learning(**kwargs):
    return domain(**kwargs)


def game_admin_bridge(**kwargs):
    return domain(**kwargs)


def build_game_context(*domains, **kwargs):
    return _merge_domains(*domains, **kwargs)


def build_inference_context(*domains, **kwargs):
    return _merge_domains(*domains, **kwargs)


def admin_runtime(**kwargs):
    return domain(**kwargs)


def admin_reporting(**kwargs):
    return domain(**kwargs)


def admin_maintenance(**kwargs):
    return domain(**kwargs)


def admin_matrix_tools(**kwargs):
    return domain(**kwargs)


def build_admin_context(*domains, **kwargs):
    return _merge_domains(*domains, **kwargs)


def system_runtime(**kwargs):
    return domain(**kwargs)


def system_storage(**kwargs):
    return domain(**kwargs)


def build_system_context(*domains, **kwargs):
    return _merge_domains(*domains, **kwargs)
