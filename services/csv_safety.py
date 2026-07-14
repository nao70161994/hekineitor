import csv
import io
from collections.abc import Iterable, Mapping, Sequence

DANGEROUS_PREFIXES = ('=', '+', '-', '@')


def safe_csv_cell(value: object) -> str:
    if value is None:
        return ''
    text = str(value)
    stripped = text.lstrip()
    if stripped.startswith(DANGEROUS_PREFIXES):
        return "'" + text
    return text


def safe_csv_row(row: Mapping[str, object]) -> dict[str, str]:
    return {key: safe_csv_cell(value) for key, value in row.items()}


def csv_text(rows: Iterable[Mapping[str, object]], fieldnames: Sequence[str]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, extrasaction='ignore', lineterminator='\n')
    writer.writeheader()
    for row in rows:
        writer.writerow(safe_csv_row(row))
    return buffer.getvalue()
