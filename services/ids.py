def parse_id_list(value: object) -> set[int]:
    if not isinstance(value, list):
        return set()
    parsed: set[int] = set()
    for item in value:
        try:
            parsed.add(int(item))
        except (ValueError, TypeError):
            continue
    return parsed
