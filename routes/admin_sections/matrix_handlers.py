"""Matrix import/export and backup handlers for the admin API."""

import math

from engine.work_catalog import validate_catalog, validate_catalog_fetish_references
from matrix_service import matrix_validation_report


def _export_player_fetishes_to_restore(ctx, exported_fetishes):
    if not isinstance(exported_fetishes, list):
        return []
    current_ids = {fetish['id'] for fetish in ctx.engine.fetishes}
    missing = []
    seen = set()
    for fetish in exported_fetishes:
        if not isinstance(fetish, dict):
            continue
        try:
            fetish_id = int(fetish.get('id'))
        except (TypeError, ValueError):
            continue
        if fetish_id < ctx.player_fetish_base_id or fetish_id in current_ids or fetish_id in seen:
            continue
        name = str(fetish.get('name') or '').strip()[:100]
        if not name:
            continue
        missing.append(
            {
                'id': fetish_id,
                'name': name,
                'desc': str(fetish.get('desc') or name).strip()[:500] or name,
                'works': fetish.get('works') if isinstance(fetish.get('works'), list) else [],
            }
        )
        seen.add(fetish_id)
    return missing


def _missing_export_player_fetishes(ctx, exported_fetishes):
    return [
        {'id': fetish['id'], 'name': fetish['name']}
        for fetish in _export_player_fetishes_to_restore(ctx, exported_fetishes)
    ]


def _backup_integer(value, label):
    if isinstance(value, bool):
        raise ValueError(f'{label} に不正な整数があります')
    if isinstance(value, float) and (not math.isfinite(value) or not value.is_integer()):
        raise ValueError(f'{label} に不正な整数があります')
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ValueError(f'{label} に不正な整数があります')
    if parsed < 0:
        raise ValueError(f'{label} に不正な整数があります')
    return parsed


def _matrix_backup_format_version(payload):
    if not isinstance(payload, dict):
        raise ValueError('バックアップはオブジェクトで指定してください')
    metadata = payload.get('metadata')
    if 'metadata' in payload and not isinstance(metadata, dict):
        raise ValueError('metadata はオブジェクトで指定してください')
    version = metadata.get('backup_format_version') if isinstance(metadata, dict) else None
    if version is not None and type(version) is not int:
        raise ValueError('backup_format_version が不正です')
    if 'questions' in payload:
        questions = payload['questions']
        if not isinstance(questions, list) or not questions:
            raise ValueError('questions は空でないリストで指定してください')
        if version not in (2, 3):
            raise ValueError('questions を含むバックアップは backup_format_version=2 または 3 が必要です')
        if 'fetishes' not in payload:
            raise ValueError('v2/v3バックアップには fetishes が必要です')
        if version == 3:
            catalog = payload.get('work_catalog')
            if not isinstance(catalog, dict):
                raise ValueError('v3バックアップには work_catalog が必要です')
            try:
                validate_catalog(catalog)
            except ValueError as exc:
                raise ValueError(f'work_catalog が不正です: {exc}')
        result = version
    else:
        if version not in (None, 1):
            raise ValueError('未対応の backup_format_version です')
        result = 1
    if 'fetishes' in payload:
        fetishes = payload['fetishes']
        if not isinstance(fetishes, list) or not fetishes:
            raise ValueError('fetishes は空でないリストで指定してください')
        seen = set()
        for fetish in fetishes:
            if not isinstance(fetish, dict) or 'id' not in fetish:
                raise ValueError('fetishes の各要素に id と name が必要です')
            try:
                if isinstance(fetish['id'], bool):
                    raise ValueError
                fetish_id = _backup_integer(fetish['id'], 'fetishes')
            except (TypeError, ValueError):
                raise ValueError('fetishes に不正なIDがあります')
            if fetish_id in seen:
                raise ValueError('fetishes に重複したIDがあります')
            name = fetish.get('name')
            if not isinstance(name, str) or not name.strip():
                raise ValueError('fetishes の各要素に空でない name が必要です')
            seen.add(fetish_id)
    if result == 3:
        try:
            validate_catalog_fetish_references(payload['work_catalog'], seen)
        except ValueError as exc:
            raise ValueError(f'work_catalog が不正です: {exc}')
    return result


def _adapt_matrix_rows_to_current_questions(ctx, rows, exported_questions, exported_fetishes, fetishes_to_restore):
    if not isinstance(rows, list):
        raise ValueError('matrix_rows はリストで指定してください')
    if not (isinstance(exported_questions, list) and exported_questions) and not isinstance(exported_fetishes, list):
        return rows, {
            'source_rows': len(rows),
            'restored_source_rows': len(rows),
            'ignored_source_rows': 0,
            'preserved_current_rows': 0,
        }
    exported_ids = []
    if isinstance(exported_fetishes, list):
        for fetish in exported_fetishes:
            try:
                exported_ids.append(_backup_integer(fetish.get('id'), 'fetishes'))
            except (AttributeError, TypeError, ValueError):
                raise ValueError('fetishes に不正なIDがあります')
    if len(set(exported_ids)) != len(exported_ids):
        raise ValueError('fetishes に重複したIDがあります')
    source_pairs = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('matrix_rows の各要素はオブジェクトで指定してください')
        if 'yes' not in row or 'total' not in row:
            raise ValueError('matrix_rows の各要素に yes と total が必要です')
        try:
            pair = (
                _backup_integer(row.get('fetish_id'), 'matrix_rows'),
                _backup_integer(row.get('question_id'), 'matrix_rows'),
            )
        except (TypeError, ValueError):
            raise ValueError('matrix_rows に不正なIDがあります')
        if pair in source_pairs:
            raise ValueError('matrix_rows に重複した fetish_id/question_id があります')
        try:
            yes = float(row['yes'])
            total = float(row['total'])
        except (TypeError, ValueError):
            raise ValueError('matrix_rows に不正な数値があります')
        if not (math.isfinite(yes) and math.isfinite(total)) or yes < 0 or total < 0 or yes > total:
            raise ValueError('matrix_rows は 0 <= yes <= total を満たす必要があります')
        source_pairs.add(pair)
    current_ids = [int(question.get('id', index)) for index, question in enumerate(ctx.engine.questions)]
    if len(set(current_ids)) != len(current_ids):
        raise ValueError('現在のquestionsに重複したIDがあります')
    current_id_to_index = {question_id: index for index, question_id in enumerate(current_ids)}
    current_text_to_indexes = {}
    for index, question in enumerate(ctx.engine.questions):
        current_text_to_indexes.setdefault(str(question.get('text') or ''), []).append(index)
    source_to_current = {}
    if isinstance(exported_questions, list) and exported_questions:
        source_indexes = set()
        source_stable_ids = set()
        for question in exported_questions:
            if not isinstance(question, dict):
                raise ValueError('questions の各要素はオブジェクトで指定してください')
            if 'matrix_index' not in question or 'id' not in question:
                raise ValueError('questions の各要素に id と matrix_index が必要です')
            try:
                if isinstance(question['matrix_index'], bool) or isinstance(question['id'], bool):
                    raise ValueError
                source_index = _backup_integer(question['matrix_index'], 'questions')
                stable_id = _backup_integer(question['id'], 'questions')
            except (TypeError, ValueError):
                raise ValueError('questions に不正なIDがあります')
            if source_index < 0 or stable_id < 0:
                raise ValueError('questions に不正なIDがあります')
            if source_index in source_indexes or stable_id in source_stable_ids:
                raise ValueError('questions に重複したIDがあります')
            source_indexes.add(source_index)
            source_stable_ids.add(stable_id)
            source_to_current[source_index] = current_id_to_index.get(stable_id)
        if exported_ids:
            expected_source = {
                (fetish_id, question_index) for fetish_id in exported_ids for question_index in source_indexes
            }
            if source_pairs != expected_source:
                raise ValueError('matrix_rows はバックアップ時点の全 fetish/question 組み合わせを含む必要があります')
    else:
        source_texts = {}
        for row in rows:
            source_index = int(row['question_id'])
            text = str(row.get('question_text') or '')
            if source_index in source_texts and source_texts[source_index] != text:
                raise ValueError('旧バックアップの同じquestion_idに異なる質問文があります')
            source_texts[source_index] = text
            matches = current_text_to_indexes.get(text, [])
            if len(matches) > 1:
                raise ValueError('旧バックアップの質問文が現在の複数質問に一致します')
            source_to_current[source_index] = matches[0] if matches else None
        if exported_ids:
            expected_source = {
                (fetish_id, question_index) for fetish_id in exported_ids for question_index in source_texts
            }
            if source_pairs != expected_source:
                raise ValueError('matrix_rows は旧バックアップ時点の全 fetish/question 組み合わせを含む必要があります')
    prospective = ctx.engine.fetishes + fetishes_to_restore
    prospective_ids = {int(fetish['id']) for fetish in prospective}
    if not any(current_index is not None for current_index in source_to_current.values()):
        raise ValueError('バックアップの質問を現在の質問に対応付けできません')
    transformed = {}
    restored_source_rows = 0
    ignored_source_rows = 0
    for row in rows:
        fetish_id = int(row['fetish_id'])
        current_index = source_to_current.get(int(row['question_id']))
        if fetish_id not in prospective_ids or current_index is None:
            ignored_source_rows += 1
            continue
        converted = dict(row)
        converted['question_id'] = current_index
        converted['question_text'] = ctx.engine.questions[current_index]['text']
        key = (fetish_id, current_index)
        if key in transformed:
            raise ValueError('質問スキーマ変換後に重複行が発生しました')
        transformed[key] = converted
        restored_source_rows += 1
    if restored_source_rows == 0:
        raise ValueError('バックアップのmatrix_rowsを現在のデータに対応付けできません')
    current_fetish_index = {int(fetish['id']): index for index, fetish in enumerate(ctx.engine.fetishes)}
    preserved_current_rows = 0
    for fetish in prospective:
        fetish_id = int(fetish['id'])
        for question_index, question in enumerate(ctx.engine.questions):
            key = (fetish_id, question_index)
            if key in transformed:
                continue
            preserved_current_rows += 1
            existing_index = current_fetish_index.get(fetish_id)
            if existing_index is None:
                yes, total = 2.0, 4.0
            else:
                yes = ctx.engine.matrix['yes'][existing_index][question_index]
                total = ctx.engine.matrix['total'][existing_index][question_index]
            transformed[key] = {
                'fetish_id': fetish_id,
                'fetish_name': fetish.get('name', ''),
                'question_id': question_index,
                'question_text': question.get('text', ''),
                'yes': yes,
                'total': total,
            }
    return list(transformed.values()), {
        'source_rows': len(rows),
        'restored_source_rows': restored_source_rows,
        'ignored_source_rows': ignored_source_rows,
        'preserved_current_rows': preserved_current_rows,
    }


def _import_validation_report(ctx, rows, fetishes_to_restore):
    if not fetishes_to_restore:
        report = ctx.engine.validate_matrix_rows(rows)
        expected_rows = ctx.matrix_import_expected_rows()
    else:
        prospective_fetishes = ctx.engine.fetishes + fetishes_to_restore
        report = matrix_validation_report(prospective_fetishes, ctx.engine.questions, rows)
        expected_rows = len(prospective_fetishes) * len(ctx.engine.questions)
    return report, expected_rows


def _matrix_import_completeness_error(ctx, report, expected_rows):
    if report.get('skipped_rows') != 0 or report.get('valid_rows') != expected_rows:
        return (
            ctx.jsonify(
                {
                    'status': 'error',
                    'message': 'matrix_rows は現在の全 fetish/question 組み合わせを含む必要があります',
                    **report,
                    'expected_rows': expected_rows,
                }
            ),
            400,
        )
    return None


def export_matrix(ctx):
    fetishes = ctx.engine.fetishes
    questions = ctx.engine.questions
    rows = []
    for fetish_idx, fetish in enumerate(fetishes):
        for question_idx, question in enumerate(questions):
            yes = ctx.engine.matrix['yes'][fetish_idx][question_idx]
            total = ctx.engine.matrix['total'][fetish_idx][question_idx]
            rows.append(
                {
                    'fetish_id': fetish['id'],
                    'fetish_name': fetish['name'],
                    'question_id': question_idx,
                    'question_text': question['text'],
                    'yes': round(yes, 4),
                    'total': round(total, 4),
                }
            )
    exported_at = ctx.strftime('%Y-%m-%dT%H:%M:%SZ', ctx.gmtime())
    payload = ctx.json_dumps(
        {
            'exported_at': exported_at,
            'metadata': {
                'exported_at': exported_at,
                'fetish_count': len(fetishes),
                'question_count': len(questions),
                'matrix_row_count': len(rows),
                'backup_format_version': 3,
            },
            'fetishes': fetishes,
            'questions': [dict(question, matrix_index=index) for index, question in enumerate(questions)],
            'matrix_rows': rows,
            'work_catalog': ctx.engine._work_catalog_snapshot(),
        },
        ensure_ascii=False,
        indent=2,
    )
    return ctx.Response(
        payload,
        mimetype='application/json',
        headers={'Content-Disposition': 'attachment; filename="matrix_export.json"'},
    )


def import_matrix(ctx):
    data = ctx.request.get_json(silent=True) or {}
    rows = data.get('matrix_rows', [])
    if not rows:
        return ctx.jsonify({'status': 'error', 'message': 'matrix_rows が空です'}), 400
    fetishes_to_restore = _export_player_fetishes_to_restore(ctx, data.get('fetishes'))
    try:
        backup_version = _matrix_backup_format_version(data)
        rows, adaptation = _adapt_matrix_rows_to_current_questions(
            ctx, rows, data.get('questions'), data.get('fetishes'), fetishes_to_restore
        )
        report, expected_rows = _import_validation_report(ctx, rows, fetishes_to_restore)
        complete_error = _matrix_import_completeness_error(ctx, report, expected_rows)
        if adaptation['ignored_source_rows'] and data.get('allow_ignored_source_rows') is not True:
            raise ValueError('対応できないバックアップ行があります。明示的な許可なしでは復元できません')
        if complete_error:
            return complete_error
        confirm_error = ctx.require_confirm('IMPORT')
        if confirm_error:
            return confirm_error
        backup_path = ctx.snapshot_current_matrix('before_import_matrix')
        count, restored_fetishes = ctx.engine.restore_matrix_snapshot(
            fetishes_to_restore,
            rows,
            work_catalog=data.get('work_catalog') if backup_version == 3 else None,
        )
    except ValueError as exc:
        ctx.write_audit('import_matrix', 'error', {'message': str(exc)}, ctx.request)
        return ctx.jsonify({'status': 'error', 'message': str(exc)}), 400
    backup_relpath = ctx.relpath(backup_path, ctx.app_dir)
    ctx.write_audit(
        'import_matrix',
        'ok',
        {
            'imported_rows': count,
            'input_rows': report['input_rows'],
            'skipped_rows': report['skipped_rows'],
            'backup_path': backup_relpath,
            **adaptation,
            'restored_player_fetish_count': len(restored_fetishes),
        },
        ctx.request,
    )
    return ctx.jsonify(
        {
            'status': 'ok',
            'imported_rows': count,
            'expected_rows': expected_rows,
            **adaptation,
            'backup_path': backup_relpath,
            'restored_player_fetishes': [{'id': fetish['id'], 'name': fetish['name']} for fetish in restored_fetishes],
            'restored_player_fetish_count': len(restored_fetishes),
        }
    )


def import_matrix_dry_run(ctx):
    data = ctx.request.get_json(silent=True) or {}
    rows = data.get('matrix_rows', [])
    if not rows:
        return ctx.jsonify({'status': 'error', 'message': 'matrix_rows が空です'}), 400
    fetishes_to_restore = _export_player_fetishes_to_restore(ctx, data.get('fetishes'))
    missing = [{'id': fetish['id'], 'name': fetish['name']} for fetish in fetishes_to_restore]
    try:
        _matrix_backup_format_version(data)
        rows, adaptation = _adapt_matrix_rows_to_current_questions(
            ctx, rows, data.get('questions'), data.get('fetishes'), fetishes_to_restore
        )
        report, expected_rows = _import_validation_report(ctx, rows, fetishes_to_restore)
    except ValueError as exc:
        ctx.write_audit('import_matrix_dry_run', 'error', {'message': str(exc)}, ctx.request)
        return ctx.jsonify({'status': 'error', 'message': str(exc)}), 400
    ctx.write_audit('import_matrix_dry_run', 'ok', report, ctx.request)
    return ctx.jsonify(
        {
            'status': 'ok',
            **report,
            **adaptation,
            'expected_rows': expected_rows,
            'complete': report['skipped_rows'] == 0
            and report['valid_rows'] == expected_rows
            and adaptation['ignored_source_rows'] == 0,
            'missing_player_fetishes': missing,
            'missing_player_fetish_count': len(missing),
            'restorable_player_fetish_count': len(fetishes_to_restore),
        }
    )


def matrix_backups(ctx):
    return ctx.jsonify({'status': 'ok', 'backups': ctx.list_matrix_import_backups()})


def restore_matrix_backup(ctx, name):
    safe_name = ctx.basename(name)
    if safe_name != name or not safe_name.endswith('.json'):
        return ctx.jsonify({'status': 'error', 'message': '不正なバックアップ名です'}), 400
    path = ctx.join_path(ctx.data_path('matrix_import_backups'), safe_name)
    if not ctx.path_exists(path):
        return ctx.jsonify({'status': 'error', 'message': 'バックアップが見つかりません'}), 404
    payload = ctx.load_json_file(ctx.join_path('matrix_import_backups', safe_name), default={})
    rows = payload.get('matrix_rows', []) if isinstance(payload, dict) else []
    if not rows:
        return ctx.jsonify({'status': 'error', 'message': 'matrix_rows が見つかりません'}), 400
    request_data = ctx.request.get_json(silent=True) or {}
    allow_ignored = (
        request_data.get('allow_ignored_source_rows') is True or payload.get('allow_ignored_source_rows') is True
    )
    fetishes_to_restore = _export_player_fetishes_to_restore(
        ctx, payload.get('fetishes') if isinstance(payload, dict) else []
    )
    try:
        backup_version = _matrix_backup_format_version(payload)
        rows, adaptation = _adapt_matrix_rows_to_current_questions(
            ctx,
            rows,
            payload.get('questions'),
            payload.get('fetishes'),
            fetishes_to_restore,
        )
        if adaptation['ignored_source_rows'] and not allow_ignored:
            raise ValueError('対応できないバックアップ行があります。明示的な許可なしでは復元できません')
        report, expected_rows = _import_validation_report(ctx, rows, fetishes_to_restore)
        complete_error = _matrix_import_completeness_error(ctx, report, expected_rows)
        if complete_error:
            return complete_error
        confirm_error = ctx.require_confirm('RESTORE')
        if confirm_error:
            return confirm_error
        snapshot = ctx.snapshot_current_matrix('before_restore_matrix_backup')
        count, restored_fetishes = ctx.engine.restore_matrix_snapshot(
            fetishes_to_restore,
            rows,
            work_catalog=payload.get('work_catalog') if backup_version == 3 else None,
        )
    except ValueError as exc:
        ctx.write_audit('restore_matrix_backup', 'error', {'name': safe_name, 'message': str(exc)}, ctx.request)
        return ctx.jsonify({'status': 'error', 'message': str(exc)}), 400
    snapshot_relpath = ctx.relpath(snapshot, ctx.app_dir)
    ctx.write_audit(
        'restore_matrix_backup',
        'ok',
        {
            'name': safe_name,
            'restored_rows': count,
            'input_rows': report['input_rows'],
            'skipped_rows': report['skipped_rows'],
            'pre_restore_backup': snapshot_relpath,
            **adaptation,
            'restored_player_fetish_count': len(restored_fetishes),
        },
        ctx.request,
    )
    return ctx.jsonify(
        {
            'status': 'ok',
            'restored_rows': count,
            **adaptation,
            'pre_restore_backup': snapshot_relpath,
            'restored_player_fetishes': [{'id': fetish['id'], 'name': fetish['name']} for fetish in restored_fetishes],
            'restored_player_fetish_count': len(restored_fetishes),
        }
    )
