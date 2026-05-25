import csv
import io


DANGEROUS_PREFIXES = ('=', '+', '-', '@')


def safe_csv_cell(value):
    if value is None:
        return ''
    text = str(value)
    stripped = text.lstrip()
    if stripped.startswith(DANGEROUS_PREFIXES):
        return "'" + text
    return text


def safe_csv_row(row):
    return {key: safe_csv_cell(value) for key, value in row.items()}


def csv_text(rows, fieldnames):
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, extrasaction='ignore', lineterminator='\n')
    writer.writeheader()
    for row in rows:
        writer.writerow(safe_csv_row(row))
    return buffer.getvalue()
