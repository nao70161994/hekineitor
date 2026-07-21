import copy


def snapshot_current_matrix(engine, reason, *, data_path, atomic_write_json, time_module, prune_fn, os_module):
    rows = []
    fetishes = copy.deepcopy(engine.fetishes)
    for fetish_index, fetish in enumerate(engine.fetishes):
        for question_index, question in enumerate(engine.questions):
            rows.append(
                {
                    'fetish_id': fetish['id'],
                    'fetish_name': fetish['name'],
                    'question_id': question_index,
                    'question_text': question['text'],
                    'yes': round(engine.matrix['yes'][fetish_index][question_index], 4),
                    'total': round(engine.matrix['total'][fetish_index][question_index], 4),
                }
            )
    created_at = int(time_module.time())
    snapshot = {
        'created_at': created_at,
        'reason': reason,
        'metadata': {
            'backup_format_version': 3,
            'created_at': created_at,
            'fetish_count': len(fetishes),
            'question_count': len(engine.questions),
            'matrix_row_count': len(rows),
        },
        'fetishes': fetishes,
        'questions': [dict(question, matrix_index=index) for index, question in enumerate(engine.questions)],
        'matrix_rows': rows,
        'work_catalog': engine._work_catalog_snapshot(),
    }
    backup_dir = data_path('matrix_import_backups')
    os_module.makedirs(backup_dir, exist_ok=True)
    path = os_module.path.join(backup_dir, f'matrix_before_{time_module.time_ns()}.json')
    atomic_write_json(path, snapshot, ensure_ascii=False, indent=2)
    prune_fn()
    return path


def expected_rows(engine):
    return len(engine.fetishes) * len(engine.questions)


def completeness_error(report, expected_row_count, jsonify):
    if report.get('skipped_rows') != 0 or report.get('valid_rows') != expected_row_count:
        return (
            jsonify(
                {
                    'status': 'error',
                    'message': 'matrix_rows は現在の全 fetish/question 組み合わせを含む必要があります',
                    **report,
                    'expected_rows': expected_row_count,
                }
            ),
            400,
        )
    return None


def list_backups(*, data_path, os_module, limit=50):
    backup_dir = data_path('matrix_import_backups')
    if not os_module.path.isdir(backup_dir):
        return []
    rows = []
    for name in sorted(os_module.listdir(backup_dir), reverse=True):
        if not name.endswith('.json'):
            continue
        path = os_module.path.join(backup_dir, name)
        try:
            stat = os_module.stat(path)
        except OSError:
            continue
        rows.append({'name': name, 'mtime': int(stat.st_mtime), 'size': stat.st_size})
    return rows if limit is None else rows[:limit]


def prune_backups(*, environ, data_path, os_module, list_fn):
    try:
        keep = int(environ.get('MATRIX_IMPORT_BACKUP_KEEP', '20'))
    except ValueError:
        keep = 20
    keep = max(1, min(keep, 200))
    backups = list_fn(limit=None)
    for row in backups[keep:]:
        try:
            os_module.remove(os_module.path.join(data_path('matrix_import_backups'), row['name']))
        except OSError:
            pass


class MatrixBackupOperations:
    def __init__(self, *, engine, data_path, atomic_write_json, time_module, os_module, jsonify, environ):
        self.engine = engine
        self.data_path = data_path
        self.atomic_write_json = atomic_write_json
        self.time_module = time_module
        self.os_module = os_module
        self.jsonify = jsonify
        self.environ = environ

    def snapshot_current_matrix(self, reason):
        return snapshot_current_matrix(
            self.engine,
            reason,
            data_path=self.data_path,
            atomic_write_json=self.atomic_write_json,
            time_module=self.time_module,
            prune_fn=self.prune_backups,
            os_module=self.os_module,
        )

    def expected_rows(self):
        return expected_rows(self.engine)

    def completeness_error(self, report):
        return completeness_error(report, self.expected_rows(), self.jsonify)

    def list_backups(self, limit=50):
        return list_backups(data_path=self.data_path, os_module=self.os_module, limit=limit)

    def prune_backups(self):
        return prune_backups(
            environ=self.environ,
            data_path=self.data_path,
            os_module=self.os_module,
            list_fn=self.list_backups,
        )


def operations(**kwargs):
    return MatrixBackupOperations(**kwargs)


def operations_for_filesystem(*, engine, filesystem, time_module, jsonify, environ):
    return operations(
        engine=engine,
        data_path=filesystem.data_path,
        atomic_write_json=filesystem.atomic_write_json,
        time_module=time_module,
        os_module=filesystem.os,
        jsonify=jsonify,
        environ=environ,
    )
