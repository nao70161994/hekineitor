def next_player_fetish_id(fetishes, player_base_id):
    player_ids = [fetish['id'] for fetish in fetishes if fetish['id'] >= player_base_id]
    return max(player_ids) + 1 if player_ids else player_base_id


def first_free_seed_id(fetishes, player_base_id):
    seed_ids = {fetish['id'] for fetish in fetishes if fetish['id'] < player_base_id}
    return next((candidate for candidate in range(player_base_id) if candidate not in seed_ids), None)


def append_fetish(fetishes, matrix, *, db_id, name, desc, yes_row, total_row):
    array_idx = len(fetishes)
    fetishes.append({'id': db_id, 'name': name, 'desc': desc})
    matrix['yes'].append(yes_row)
    matrix['total'].append(total_row)
    return array_idx


def apply_fetish_edits(fetish, *, name=None, desc=None, works=None):
    if name is not None:
        fetish['name'] = name
    if desc is not None:
        fetish['desc'] = desc
    if works is not None:
        fetish['works'] = works


def delete_fetish_at(fetishes, matrix, idx):
    fetishes.pop(idx)
    matrix['yes'].pop(idx)
    matrix['total'].pop(idx)


def merge_fetish_rows(fetishes, matrix, idx_keep, idx_remove, *, new_name=None, new_desc=None):
    for question_idx in range(len(matrix['yes'][idx_keep])):
        matrix['yes'][idx_keep][question_idx] += matrix['yes'][idx_remove][question_idx]
        matrix['total'][idx_keep][question_idx] += matrix['total'][idx_remove][question_idx]
    if new_name:
        fetishes[idx_keep]['name'] = new_name
    if new_desc:
        fetishes[idx_keep]['desc'] = new_desc
    keep_name = fetishes[idx_keep]['name']
    keep_desc = fetishes[idx_keep]['desc']
    delete_fetish_at(fetishes, matrix, idx_remove)
    return keep_name, keep_desc


def merge_log_entries(log, id_keep, id_remove):
    keep_key = str(id_keep)
    remove_key = str(id_remove)
    keep_entry = log.get(keep_key, {'guessed': 0, 'correct': 0, 'wrong': 0})
    remove_entry = log.get(remove_key, {'guessed': 0, 'correct': 0, 'wrong': 0})
    log[keep_key] = {key: keep_entry.get(key, 0) + remove_entry.get(key, 0) for key in ('guessed', 'correct', 'wrong')}
    log.pop(remove_key, None)
    return log
