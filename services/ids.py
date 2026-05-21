def parse_id_list(value):
    if not isinstance(value, list):
        return set()
    parsed = set()
    for item in value:
        try:
            parsed.add(int(item))
        except (ValueError, TypeError):
            continue
    return parsed
