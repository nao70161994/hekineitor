def pair_key(id_a: int, id_b: int) -> str:
    return f"{min(id_a, id_b)},{max(id_a, id_b)}"


def load_cache(*, loaded: bool, load_fn):
    if loaded:
        return None
    return load_fn('compound_works.json', default={})


def save_cache(path, compound_works: dict, write_fn):
    write_fn(path, compound_works, ensure_ascii=False, indent=2)


def get_works(compound_works: dict, id_a: int, id_b: int) -> list:
    return list(compound_works.get(pair_key(id_a, id_b), []))


def set_works(compound_works: dict, id_a: int, id_b: int, works: list) -> str:
    key = pair_key(id_a, id_b)
    compound_works[key] = works
    return key


def delete_works(compound_works: dict, id_a: int, id_b: int) -> bool:
    key = pair_key(id_a, id_b)
    if key not in compound_works:
        return False
    del compound_works[key]
    return True


def serialize_compound_works(compound_works: dict) -> list:
    result = []
    for key, works in sorted(compound_works.items()):
        parts = key.split(',')
        if len(parts) == 2:
            result.append({'key': key, 'id_a': int(parts[0]), 'id_b': int(parts[1]), 'works': works})
    return result
