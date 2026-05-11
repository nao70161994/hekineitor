"""matrix_backup.json から learned_priors.json を再生成するスクリプト。"""
import json
import os
import sys
from datetime import datetime, timezone

from storage import atomic_write_json

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
BACKUP   = os.path.join(DATA_DIR, 'matrix_backup.json')
OUTPUT   = os.path.join(DATA_DIR, 'learned_priors.json')
MAX_BACKUP_AGE_HOURS = int(os.environ.get('MATRIX_BACKUP_MAX_AGE_HOURS', '48'))


def _load_questions_count():
    questions_path = os.path.join(DATA_DIR, 'questions.json')
    with open(questions_path, encoding='utf-8') as f:
        questions = json.load(f)
    if not isinstance(questions, list):
        raise ValueError('data/questions.json はリスト形式である必要があります')
    return len(questions)


def _load_fetish_ids(expected_count):
    fetishes_path = os.path.join(DATA_DIR, 'fetishes.json')
    try:
        with open(fetishes_path, encoding='utf-8') as f:
            fetishes = json.load(f)
    except FileNotFoundError:
        return [str(i) for i in range(expected_count)]
    if not isinstance(fetishes, list) or len(fetishes) < expected_count:
        return [str(i) for i in range(expected_count)]
    ids = []
    for i, fetish in enumerate(fetishes[:expected_count]):
        if not isinstance(fetish, dict) or 'id' not in fetish:
            return [str(i) for i in range(expected_count)]
        ids.append(str(fetish['id']))
    return ids


def _empty_priors(fetish_ids, question_count):
    return {str(fetish_id): {str(q): 0.5 for q in range(question_count)}
            for fetish_id in fetish_ids}


def _parse_exported_at(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as e:
        raise ValueError('exported_at は ISO 8601 形式である必要があります') from e
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def validate_backup_freshness(snapshot):
    metadata = snapshot.get('metadata') if isinstance(snapshot.get('metadata'), dict) else {}
    exported_at = _parse_exported_at(snapshot.get('exported_at') or metadata.get('exported_at'))
    if exported_at is None:
        raise ValueError('exported_at が見つかりません')
    age_seconds = (datetime.now(timezone.utc) - exported_at).total_seconds()
    if age_seconds < 0:
        raise ValueError('exported_at が未来日時です')
    max_age_seconds = MAX_BACKUP_AGE_HOURS * 60 * 60
    if age_seconds > max_age_seconds:
        raise ValueError(f'バックアップが古すぎます: exported_at={exported_at.isoformat()}')


def _priors_from_legacy_matrix(matrix):
    if not isinstance(matrix.get('yes'), list) or not isinstance(matrix.get('total'), list):
        raise ValueError('legacy backup requires yes and total lists')
    yes_m = matrix['yes']
    total_m = matrix['total']
    if len(yes_m) != len(total_m):
        raise ValueError('yes と total の行数が一致しません')

    question_count = None
    for i, yes_row in enumerate(yes_m):
        total_row = total_m[i]
        if not isinstance(yes_row, list) or not isinstance(total_row, list):
            raise ValueError('yes/total の各行はリストである必要があります')
        if len(yes_row) != len(total_row):
            raise ValueError(f'yes と total の列数が一致しません: row {i}')
        if question_count is None:
            question_count = len(yes_row)
        elif len(yes_row) != question_count:
            raise ValueError(f'yes/total の列数が行間で一致しません: row {i}')

    fetish_ids = _load_fetish_ids(len(yes_m))
    priors = _empty_priors(fetish_ids, question_count or 0)
    for i, yes_row in enumerate(yes_m):
        total_row = total_m[i]
        for q, y in enumerate(yes_row):
            t = total_row[q]
            if t < 0 or y < 0 or y > t:
                raise ValueError(f'不正な yes/total 値です: row {i}, question {q}')
            priors[fetish_ids[i]][str(q)] = round(y / t, 6) if t > 0 else 0.5
    return priors


def _priors_from_matrix_rows(snapshot):
    fetishes = snapshot.get('fetishes')
    rows = snapshot.get('matrix_rows')
    if not isinstance(fetishes, list) or not isinstance(rows, list):
        raise ValueError('current backup requires fetishes and matrix_rows lists')

    question_count = _load_questions_count()
    fetish_ids = []
    for i, fetish in enumerate(fetishes):
        if not isinstance(fetish, dict) or 'id' not in fetish:
            raise ValueError(f'fetishes[{i}] に id がありません')
        fetish_ids.append(str(fetish['id']))

    priors = _empty_priors(fetish_ids, question_count)
    id_to_index = {fetish_id: i for i, fetish_id in enumerate(fetish_ids)}

    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f'matrix_rows[{idx}] はオブジェクトである必要があります')
        try:
            fetish_id = str(row['fetish_id'])
            fi = id_to_index[fetish_id]
            qi = int(row['question_id'])
            y = float(row['yes'])
            t = float(row['total'])
        except KeyError as e:
            raise ValueError(f'matrix_rows[{idx}] に必要なキーまたはfetish_idがありません: {e}') from e
        except (TypeError, ValueError) as e:
            raise ValueError(f'matrix_rows[{idx}] に不正な数値があります') from e
        if qi < 0 or qi >= question_count:
            continue
        if t < 0 or y < 0 or y > t:
            raise ValueError(f'matrix_rows[{idx}] は 0 <= yes <= total を満たす必要があります')
        priors[fetish_ids[fi]][str(qi)] = round(y / t, 6) if t > 0 else 0.5

    return priors


def build_priors(snapshot):
    if not isinstance(snapshot, dict):
        raise ValueError('unsupported backup shape: JSON object expected')
    validate_backup_freshness(snapshot)
    if 'fetishes' in snapshot or 'matrix_rows' in snapshot:
        return _priors_from_matrix_rows(snapshot)
    if 'yes' in snapshot or 'total' in snapshot:
        return _priors_from_legacy_matrix(snapshot)
    raise ValueError('unsupported backup shape: expected {fetishes, matrix_rows} or {yes, total}')


def main():
    if not os.path.exists(BACKUP):
        print("data/matrix_backup.json が見つかりません")
        return 1

    with open(BACKUP, encoding='utf-8') as f:
        snapshot = json.load(f)

    try:
        priors = build_priors(snapshot)
    except ValueError as e:
        print(f"復元失敗: {e}")
        return 1

    atomic_write_json(OUTPUT, priors, ensure_ascii=False, indent=2)

    nf = len(priors)
    nq = max((len(row) for row in priors.values()), default=0)
    print(f"復元完了: {nf}性癖 × {nq}質問 → {OUTPUT}")
    return 0

if __name__ == '__main__':
    sys.exit(main())
