import math


def collect_matrix_updates(fetishes, questions, matrix_rows):
    if not isinstance(matrix_rows, list):
        raise ValueError('matrix_rows はリストで指定してください')
    idx_map = {f['id']: i for i, f in enumerate(fetishes)}
    nq = len(questions)
    updates = {}
    seen_pairs = set()
    skipped = 0
    for row in matrix_rows:
        if not isinstance(row, dict):
            raise ValueError('matrix_rows の各要素はオブジェクトで指定してください')
        if 'yes' not in row or 'total' not in row:
            raise ValueError('matrix_rows の各要素に yes と total が必要です')
        fid = row.get('fetish_id')
        qi = row.get('question_id')
        try:
            fid = int(fid)
            qi = int(qi)
            y = float(row['yes'])
            t = float(row['total'])
        except (TypeError, ValueError):
            raise ValueError('matrix_rows に不正な数値があります')
        if not (math.isfinite(y) and math.isfinite(t)):
            raise ValueError('matrix_rows に非有限値があります')
        if y < 0 or t < 0 or y > t:
            raise ValueError('matrix_rows は 0 <= yes <= total を満たす必要があります')
        pair = (fid, qi)
        if pair in seen_pairs:
            raise ValueError('matrix_rows に重複した fetish_id/question_id があります')
        seen_pairs.add(pair)
        fi = idx_map.get(fid)
        if fi is None or not (0 <= qi < nq):
            skipped += 1
            continue
        updates.setdefault(fi, []).append((qi, y, t))
    return updates, {'skipped_rows': skipped, 'input_rows': len(matrix_rows)}


def matrix_validation_report(fetishes, questions, matrix_rows):
    updates, meta = collect_matrix_updates(fetishes, questions, matrix_rows)
    return {
        'valid_rows': sum(len(v) for v in updates.values()),
        'skipped_rows': meta['skipped_rows'],
        'input_rows': meta['input_rows'],
    }
