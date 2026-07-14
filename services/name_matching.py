import re
import unicodedata
from typing import Any


def normalize_name(value: str) -> str:
    value = unicodedata.normalize('NFKC', value)
    value = value.lower()
    return re.sub(r'[\s　・･（）()「」『』【】〔〕\-_～~、。×]', '', value)


def levenshtein(left: str, right: str) -> int:
    if len(left) < len(right):
        left, right = right, left
    if not right:
        return len(left)
    previous = list(range(len(right) + 1))
    for left_char in left:
        current = [previous[0] + 1]
        for index, right_char in enumerate(right):
            current.append(
                min(
                    previous[index] + (left_char != right_char),
                    current[-1] + 1,
                    previous[index + 1] + 1,
                )
            )
        previous = current
    return previous[-1]


def find_similar(name: str, fetishes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized_name = normalize_name(name)
    results = []
    for fetish in fetishes:
        normalized_fetish = normalize_name(fetish['name'])
        if normalized_name == normalized_fetish:
            continue
        if normalized_name in normalized_fetish or normalized_fetish in normalized_name:
            results.append(fetish)
            continue
        if (
            len(normalized_name) <= 12
            and len(normalized_fetish) <= 12
            and levenshtein(normalized_name, normalized_fetish) <= 2
        ):
            results.append(fetish)
    return results[:5]
