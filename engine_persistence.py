import json
import logging
import os
import shutil


def valid_matrix_shape(matrix, nf, nq):
    if not isinstance(matrix, dict):
        return False
    yes = matrix.get('yes')
    total = matrix.get('total')
    return (
        isinstance(yes, list)
        and isinstance(total, list)
        and len(yes) == nf
        and len(total) == nf
        and all(isinstance(row, list) and len(row) == nq for row in yes)
        and all(isinstance(row, list) and len(row) == nq for row in total)
    )


def apply_learned_priors(yes, total, fetishes, questions, learned, *, pseudo):
    id_to_idx = {fetish['id']: idx for idx, fetish in enumerate(fetishes)}
    nq = len(questions)
    for fetish_id_text, row in learned.items():
        fetish_idx = id_to_idx.get(int(fetish_id_text))
        if fetish_idx is None:
            continue
        for question_id_text, probability in row.items():
            question_idx = int(question_id_text)
            if 0 <= question_idx < nq:
                yes[fetish_idx][question_idx] = float(probability) * pseudo
                total[fetish_idx][question_idx] = float(pseudo)


def initial_matrix(fetishes, questions, *, build_initial_matrix, learned_priors_path, pseudo):
    yes, total = build_initial_matrix(len(fetishes), len(questions))
    if os.path.exists(learned_priors_path):
        try:
            with open(learned_priors_path, encoding='utf-8') as file_obj:
                learned = json.load(file_obj)
            apply_learned_priors(yes, total, fetishes, questions, learned, pseudo=pseudo)
        except Exception:
            pass
    return {'yes': yes, 'total': total}


def load_matrix_file(path, fetishes, questions, *, init_matrix):
    if os.path.exists(path):
        with open(path, encoding='utf-8') as file_obj:
            matrix = json.load(file_obj)
        nf = len(fetishes)
        nq = len(questions)
        if valid_matrix_shape(matrix, nf, nq):
            return matrix
        backup = path + '.bak'
        try:
            shutil.copy2(path, backup)
        except OSError:
            pass
        logging.getLogger(__name__).warning(
            'matrix.json のサイズ不整合 (fetishes=%d, questions=%d) — 再初期化します。バックアップ: %s',
            nf, nq, backup,
        )
        os.remove(path)
    return init_matrix()


def save_matrix_file(path, matrix_snapshot, *, atomic_write):
    atomic_write(path, matrix_snapshot)


def save_fetishes_file(path, fetishes, *, atomic_write):
    atomic_write(path, fetishes, ensure_ascii=False, indent=2)


def learned_priors_snapshot(fetishes, questions, *, probability):
    snapshot = {}
    for fetish_idx, fetish in enumerate(fetishes):
        row = {}
        for question_idx in range(len(questions)):
            prob = probability(fetish_idx, question_idx)
            if abs(prob - 0.5) > 0.05:
                row[str(question_idx)] = round(prob, 4)
        if row:
            snapshot[str(fetish['id'])] = row
    return snapshot


def save_learned_priors(path, fetishes, questions, *, probability, atomic_write):
    atomic_write(path, learned_priors_snapshot(fetishes, questions, probability=probability), ensure_ascii=False)


def save_questions_file(path, questions, *, atomic_write):
    atomic_write(path, questions)
