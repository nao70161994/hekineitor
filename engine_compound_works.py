def pair_key(id_a: int, id_b: int) -> str:
    return f"{min(id_a, id_b)},{max(id_a, id_b)}"


def serialize_compound_works(compound_works: dict) -> list:
    result = []
    for key, works in sorted(compound_works.items()):
        parts = key.split(',')
        if len(parts) == 2:
            result.append({'key': key, 'id_a': int(parts[0]), 'id_b': int(parts[1]), 'works': works})
    return result
