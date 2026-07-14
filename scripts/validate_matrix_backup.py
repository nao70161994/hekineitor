#!/usr/bin/env python3
import argparse
from datetime import datetime, timezone
import json
import math


def _integer(value, label):
    if isinstance(value, bool):
        raise ValueError(f'{label} must be an integer')
    if isinstance(value, float) and (not math.isfinite(value) or not value.is_integer()):
        raise ValueError(f'{label} must be an integer')
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ValueError(f'{label} must be an integer')
    if parsed < 0:
        raise ValueError(f'{label} must be non-negative')
    return parsed


def validate(payload, max_age_days=None):
    if not isinstance(payload, dict):
        raise ValueError('backup root must be an object')
    metadata = payload.get('metadata')
    if 'metadata' in payload and not isinstance(metadata, dict):
        raise ValueError('metadata must be an object')
    version = metadata.get('backup_format_version') if isinstance(metadata, dict) else None
    if version is not None and type(version) is not int:
        raise ValueError('invalid backup_format_version')
    if 'questions' in payload:
        questions = payload['questions']
        if not isinstance(questions, list) or not questions:
            raise ValueError('questions must be a non-empty list')
        if version != 2:
            raise ValueError('question schema requires backup_format_version=2')
        has_questions = True
    else:
        questions = None
        has_questions = False
        if version not in (None, 1):
            raise ValueError('unsupported backup_format_version')

    fetishes = payload.get('fetishes')
    rows = payload.get('matrix_rows')
    if not isinstance(fetishes, list) or not fetishes:
        raise ValueError('fetishes must be a non-empty list')
    if not isinstance(rows, list) or not rows:
        raise ValueError('matrix_rows must be a non-empty list')

    fetish_ids = set()
    for fetish in fetishes:
        if not isinstance(fetish, dict) or 'id' not in fetish:
            raise ValueError('each fetish must have an id')
        name = fetish.get('name')
        if not isinstance(name, str) or not name.strip():
            raise ValueError('each fetish must have a non-empty name')
        fetish_id = _integer(fetish['id'], 'fetish id')
        if fetish_id in fetish_ids:
            raise ValueError('duplicate fetish id')
        fetish_ids.add(fetish_id)

    question_indexes = set()
    stable_ids = set()
    if has_questions:
        for question in questions:
            if not isinstance(question, dict) or 'id' not in question or 'matrix_index' not in question:
                raise ValueError('each question must have id and matrix_index')
            stable_id = _integer(question['id'], 'question id')
            matrix_index = _integer(question['matrix_index'], 'matrix_index')
            if stable_id in stable_ids or matrix_index in question_indexes:
                raise ValueError('duplicate question id or matrix_index')
            stable_ids.add(stable_id)
            question_indexes.add(matrix_index)

    pairs = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('each matrix row must be an object')
        required = {'fetish_id', 'question_id', 'yes', 'total'}
        if not required.issubset(row):
            raise ValueError('matrix row is missing required fields')
        pair = (_integer(row['fetish_id'], 'fetish_id'), _integer(row['question_id'], 'question_id'))
        if pair in pairs:
            raise ValueError('duplicate matrix pair')
        pairs.add(pair)
        try:
            yes = float(row['yes'])
            total = float(row['total'])
        except (TypeError, ValueError):
            raise ValueError('invalid matrix value')
        if not math.isfinite(yes) or not math.isfinite(total) or yes < 0 or total < 0 or yes > total:
            raise ValueError('matrix values must satisfy 0 <= yes <= total')
        if not has_questions:
            question_indexes.add(pair[1])

    expected = {(fetish_id, question_index) for fetish_id in fetish_ids for question_index in question_indexes}
    if not question_indexes or pairs != expected:
        raise ValueError('matrix_rows is not the complete fetish/question product')

    if max_age_days is not None:
        exported_at = payload.get('exported_at') or (metadata.get('exported_at') if isinstance(metadata, dict) else None)
        if not isinstance(exported_at, str):
            raise ValueError('exported_at is required')
        try:
            exported = datetime.fromisoformat(exported_at.replace('Z', '+00:00'))
        except ValueError:
            raise ValueError('invalid exported_at')
        if exported.tzinfo is None:
            exported = exported.replace(tzinfo=timezone.utc)
        age_seconds = (datetime.now(timezone.utc) - exported.astimezone(timezone.utc)).total_seconds()
        if age_seconds < -300 or age_seconds > max_age_days * 86400:
            raise ValueError('backup is outside the allowed age')

    return {'version': 2 if has_questions else 1, 'fetishes': len(fetish_ids), 'questions': len(question_indexes), 'rows': len(rows)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('path')
    parser.add_argument('--max-age-days', type=int)
    args = parser.parse_args()
    with open(args.path, encoding='utf-8') as source:
        payload = json.load(source)
    report = validate(payload, args.max_age_days)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
