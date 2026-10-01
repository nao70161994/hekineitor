import hashlib
import json
import urllib.parse

from flask import Blueprint

from routes.admin_sections import analytics as analytics_routes
from routes.admin_sections import matrix as matrix_routes
from routes.admin_sections import matrix_handlers, report_handlers
from routes.admin_sections import mutations as mutation_routes
from routes.admin_sections import operations as operations_routes
from routes.admin_sections import page as page_routes
from routes.admin_sections import works as works_routes
from services import improvement_candidates as improvement_candidates_service
from services import ogp as ogp_service
from services import result_exposure as result_exposure_service
from services import share_links as share_links_service
from services.csv_safety import csv_text
from services.works_links import build_work_catalog_report, collect_work_link_queue


def admin_page(ctx):
    stats = ctx.engine.get_learning_stats()
    app_stats = ctx.engine.get_stats()
    player_fetishes = [f for f in ctx.engine.fetishes if f['id'] >= ctx.player_fetish_base_id]
    question_stats = ctx.engine.get_question_stats()
    corr_stats = ctx.engine.get_correlation_stats(top_n=30)
    fetish_log_rows = ctx.build_fetish_log_rows()
    fetish_log_page = ctx.paged_fetish_log_rows(fetish_log_rows, ctx.request.args)
    domain_suggestions = ctx.engine.get_top_questions_per_fetish(top_n=5)
    stats_history = ctx.engine.get_stats_history(days=30)
    dropoff_summary = ctx.engine.get_dropoff_summary(days=30)
    completion_metrics = ctx.build_completion_metrics(app_stats, stats_history, dropoff_summary)
    matrix_heatmap = ctx.engine.get_matrix_heatmap(n_fetishes=20, n_questions=20)
    axis_stats = ctx.engine.get_axis_stats()
    quality = ctx.engine.get_quality_report()
    maintenance = ctx.build_admin_maintenance_checklist()
    share_event_filters = report_handlers.share_event_query(ctx, default_limit=1000)
    share_events = ctx.share_event_report(**share_event_filters)
    question_events = ctx.question_event_report(limit=1000)
    analysis_logs = report_handlers.analysis_log_status(
        ctx, stats_history=stats_history, share_events=share_events, question_events=question_events
    )
    share_notes = ctx.load_share_notes()
    audit_rows = ctx.recent_audit(50)
    return ctx.render_template(
        'admin.html',
        stats=stats,
        start_count=app_stats.get('start_count', 0),
        completion_count=app_stats.get('completion_count', 0),
        play_count=app_stats['play_count'],
        learn_count=app_stats['learn_count'],
        completion_metrics=completion_metrics,
        player_fetishes=player_fetishes,
        question_stats=question_stats,
        corr_stats=corr_stats,
        fetish_log_rows=fetish_log_rows,
        fetish_log_page=fetish_log_page,
        domain_suggestions=domain_suggestions,
        engine_config=ctx.engine.config,
        config_defaults=ctx.engine._CONFIG_DEFAULTS,
        stats_history=stats_history,
        matrix_heatmap=matrix_heatmap,
        axis_stats=axis_stats,
        quality_report=quality,
        maintenance_checklist=maintenance,
        share_events=share_events,
        question_events=question_events,
        analysis_logs=analysis_logs,
        share_notes=share_notes,
        share_event_filters=share_event_filters,
        share_event_query=report_handlers.share_event_query_string(share_event_filters),
        csrf_token=ctx.csrf_token(),
        csrf_expires_at=int(
            ctx.session.get('admin_csrf_issued_at', 0) + int(ctx.environ.get('ADMIN_CSRF_TTL_SECONDS', '7200'))
        ),
        audit_rows=audit_rows[:20],
        test_play_audit_rows=report_handlers.test_play_audit_rows(audit_rows),
        matrix_backups=ctx.list_matrix_import_backups(),
        test_play_active=ctx.is_test_play(),
    )


def start_test_play(ctx):
    ctx.enable_test_play()
    ctx.write_audit('test_play_start', 'ok', {'event_name': 'test_play_start', 'mode': 'learning_off'})
    return ctx.Response('', status=302, headers={'Location': '/'})


def stop_test_play(ctx):
    ctx.disable_test_play()
    ctx.write_audit('test_play_stop', 'ok', {'event_name': 'test_play_stop', 'mode': 'normal'})
    return ctx.Response('', status=302, headers={'Location': '/admin'})


def _fetishes_with_recommended_works(ctx):
    works_by_fetish = ctx.engine.recommended_works_snapshot()
    return [{**fetish, 'works': works_by_fetish.get(int(fetish['id']), [])} for fetish in ctx.engine.fetishes]


def works_link_queue_payload(ctx, *, sample_limit=20):
    return collect_work_link_queue(
        _fetishes_with_recommended_works(ctx),
        sample_limit=sample_limit,
        associate_id=ctx.amazon_associate_id,
    )


def _admin_work_url(ctx, work, title):
    raw_url = work.get('url', '') if isinstance(work, dict) else ''
    url = ctx.safe_work_url(raw_url)
    if raw_url and not url:
        return ''
    if not url and getattr(ctx, 'amazon_associate_id', '') and title:
        url = f'https://www.amazon.co.jp/s?k={urllib.parse.quote(str(title))}&tag={urllib.parse.quote(ctx.amazon_associate_id)}'
    elif url and getattr(ctx, 'amazon_associate_id', '') and 'tag=' not in url:
        separator = '&' if '?' in url else '?'
        url = url + f'{separator}tag={urllib.parse.quote(ctx.amazon_associate_id)}'
    return url


def works_health(ctx):
    maintenance = ctx.build_admin_maintenance_checklist().get('works', {})
    queue = works_link_queue_payload(ctx, sample_limit=50)
    compound_rows = ctx.list_compound_works()
    catalog = build_work_catalog_report(
        _fetishes_with_recommended_works(ctx),
        compound_rows=compound_rows,
        sample_limit=50,
    )
    migration = ctx.engine.work_catalog_migration_report()
    return ctx.jsonify(
        {
            'status': 'ok',
            'maintenance': maintenance,
            'link_queue': queue,
            'catalog': catalog,
            'migration': migration,
        }
    )


def matrix_health(ctx):
    yes_rows = ctx.engine.matrix.get('yes', [])
    total_rows = ctx.engine.matrix.get('total', [])
    expected_rows = len(ctx.engine.fetishes)
    expected_cols = len(ctx.engine.questions)
    row_lengths = [len(row) for row in yes_rows] + [len(row) for row in total_rows]
    ok = (
        len(yes_rows) == expected_rows
        and len(total_rows) == expected_rows
        and all(len(row) == expected_cols for row in yes_rows)
        and all(len(row) == expected_cols for row in total_rows)
    )
    return ctx.jsonify(
        {
            'status': 'ok' if ok else 'warning',
            'storage': 'postgres' if ctx.use_db() else 'local_json',
            'fetish_count': expected_rows,
            'question_count': expected_cols,
            'yes_rows': len(yes_rows),
            'total_rows': len(total_rows),
            'min_cols': min(row_lengths) if row_lengths else 0,
            'max_cols': max(row_lengths) if row_lengths else 0,
            'matrix_shape_ok': ok,
            'backups': ctx.list_matrix_import_backups(),
        }
    )


def funnel_metrics(ctx):
    include_details = str(ctx.request.args.get('include_details') or '').lower() in ('1', 'true', 'yes')
    app_stats = ctx.engine.get_stats()
    stats_history = ctx.engine.get_stats_history(days=30)
    dropoff_summary = ctx.engine.get_dropoff_summary(days=30)
    completion = ctx.build_completion_metrics(app_stats, stats_history, dropoff_summary)
    payload = {
        'status': 'ok',
        'completion': completion,
        'dropoff_summary': dropoff_summary,
        'stats_history': stats_history,
        'details_included': include_details,
    }
    if include_details:
        share_report = ctx.share_event_report(limit=1000)
        question_report = ctx.question_event_report(limit=1000)
        payload.update(
            {
                'share_metrics': share_report.get('metrics', {}),
                'question_summary': question_report.get('summary', {}),
            }
        )
    return ctx.jsonify(payload)


def player_fetishes(ctx):
    rows = [
        {
            'id': fetish.get('id'),
            'name': fetish.get('name', ''),
            'desc': fetish.get('desc', ''),
            'works_count': len(ctx.engine.get_recommended_works(fetish['id'])),
        }
        for fetish in ctx.engine.fetishes
        if fetish.get('id', 0) >= ctx.player_fetish_base_id
    ]
    return ctx.jsonify({'status': 'ok', 'total': len(rows), 'player_fetishes': rows})


def added_fetishes(ctx):
    seed_rows = ctx.load_json_file('fetishes.json', default=[])
    seed_ids = {row.get('id') for row in seed_rows if isinstance(row, dict)}
    seed_names = {str(row.get('name') or '') for row in seed_rows if isinstance(row, dict)}
    rows = []
    for fetish in ctx.engine.fetishes:
        fetish_id = fetish.get('id')
        name = str(fetish.get('name') or '')
        if fetish_id in seed_ids and name in seed_names:
            continue
        if fetish_id in seed_ids and name:
            source = 'seed_name_changed'
        elif isinstance(fetish_id, int) and fetish_id >= ctx.player_fetish_base_id:
            source = 'player_added'
        elif fetish_id not in seed_ids:
            source = 'promoted_or_db_added'
        else:
            source = 'unknown_added'
        rows.append(
            {
                'id': fetish_id,
                'name': name,
                'source': source,
                'player_id': bool(isinstance(fetish_id, int) and fetish_id >= ctx.player_fetish_base_id),
                'seed_id_present': fetish_id in seed_ids,
                'seed_name_present': name in seed_names,
                'works_count': len(ctx.engine.get_recommended_works(fetish_id)),
            }
        )
    rows.sort(key=lambda row: (0 if row['source'] == 'player_added' else 1, row.get('id') or 0, row.get('name') or ''))
    counts = {}
    for row in rows:
        counts[row['source']] = counts.get(row['source'], 0) + 1
    return ctx.jsonify({'status': 'ok', 'total': len(rows), 'counts': counts, 'added_fetishes': rows})


def promoted_fetish_history(ctx):
    rows = ctx.recent_audit(ctx.bounded_int(ctx.request.args.get('limit'), 100, 1, 500))
    promotions = []
    repairs = []
    for row in rows:
        action = row.get('action')
        detail = row.get('detail') if isinstance(row.get('detail'), dict) else {}
        if action == 'promote_fetish':
            promotions.append(
                {
                    'timestamp': row.get('ts', ''),
                    'old_id': detail.get('old_id'),
                    'new_id': detail.get('new_id'),
                    'status': row.get('status', ''),
                }
            )
        elif action in ('repair_promoted_stats_history', 'move_stats_history'):
            repairs.append(
                {
                    'timestamp': row.get('ts', ''),
                    'action': action,
                    'status': row.get('status', ''),
                    'detail': detail,
                }
            )
    return ctx.jsonify({'status': 'ok', 'promotions': promotions, 'repairs': repairs})


def _safe_engine_config(ctx):
    defaults = getattr(ctx.engine, '_CONFIG_DEFAULTS', {}) or {}
    config = getattr(ctx.engine, 'config', {}) or {}
    keys = sorted(set(defaults) | set(config))
    rows = []
    for key in keys:
        rows.append(
            {
                'key': str(key),
                'value': config.get(key),
                'default': defaults.get(key),
                'overridden': config.get(key) != defaults.get(key),
            }
        )
    return rows


def _question_admin_rows(ctx):
    stats_by_id = {row.get('id'): row for row in ctx.engine.get_question_stats()}
    rows = []
    for question_id, question in enumerate(ctx.engine.questions):
        stats = stats_by_id.get(question_id, {})
        rows.append(
            {
                'id': question_id,
                'text': question.get('text', ''),
                'category': question.get('category') or 'unknown',
                'axis': question.get('axis') or '',
                'disabled': bool(question.get('disabled')),
                'disc': stats.get('disc'),
                'ask_count': stats.get('ask_count', 0),
                'variant_count': stats.get('variant_count', 0),
            }
        )
    return rows


def _compound_works_rows(ctx, *, limit=200):
    items = ctx.list_compound_works()[: max(1, int(limit or 200))]
    rows = []
    for item in items:
        idx_a = ctx.engine.index_of(item['id_a'])
        idx_b = ctx.engine.index_of(item['id_b'])
        rows.append(
            {
                **item,
                'name_a': ctx.engine.fetishes[idx_a]['name'] if idx_a is not None else f'id={item["id_a"]}',
                'name_b': ctx.engine.fetishes[idx_b]['name'] if idx_b is not None else f'id={item["id_b"]}',
                'works_count': len(item.get('works') or []),
                'works_titles': [ctx.work_title(work) for work in (item.get('works') or [])[:5]],
            }
        )
    return rows


def operations_snapshot(ctx):
    """Read-only bundle for Codex/ops analysis; excludes CSRF, secrets, sessions, and mutation payloads."""
    stats_history = ctx.engine.get_stats_history(days=30)
    app_stats = ctx.engine.get_stats()
    dropoff_summary = ctx.engine.get_dropoff_summary(days=30)
    question_events = ctx.question_event_report(limit=1000)
    share_events = ctx.share_event_report(**report_handlers.share_event_query(ctx, default_limit=1000))
    gameplay_events = ctx.gameplay_event_report(limit=1000)
    audit_rows = ctx.recent_audit(ctx.bounded_int(ctx.request.args.get('audit_limit'), 50, 1, 200))
    return ctx.jsonify(
        {
            'status': 'ok',
            'scope': 'read_only_operations_snapshot',
            'counts': {
                'fetishes': len(ctx.engine.fetishes),
                'questions': len(ctx.engine.questions),
                'player_fetishes': len([f for f in ctx.engine.fetishes if f.get('id', 0) >= ctx.player_fetish_base_id]),
                'compound_works': len(ctx.list_compound_works()),
            },
            'engine_config': _safe_engine_config(ctx),
            'questions': _question_admin_rows(ctx),
            'question_categories': report_handlers.question_stats(ctx).get_json().get('categories', {}),
            'correlation_stats': ctx.engine.get_correlation_stats(top_n=30),
            'domain_suggestions': ctx.engine.get_top_questions_per_fetish(top_n=5),
            'matrix_heatmap': ctx.engine.get_matrix_heatmap(n_fetishes=20, n_questions=20),
            'axis_stats': ctx.engine.get_axis_stats(),
            'quality_report': ctx.engine.get_quality_report(),
            'dynamic_prior_shadow': ctx.engine.get_dynamic_prior_shadow_report(),
            'completion': ctx.build_completion_metrics(app_stats, stats_history, dropoff_summary),
            'analysis_logs': report_handlers.analysis_log_status(
                ctx, stats_history=stats_history, share_events=share_events, question_events=question_events
            ),
            'gameplay_events_summary': gameplay_events,
            'share_events_summary': {
                'total': share_events.get('total', 0),
                'invalid_result_events': share_events.get('invalid_result_events', 0),
                'metrics': share_events.get('metrics', {}),
                'work_ranking': share_events.get('work_ranking', [])[:20],
            },
            'question_events_summary': {
                'total': question_events.get('total', 0),
                'raw_loaded': question_events.get('raw_loaded', question_events.get('total', 0)),
                'total_available': question_events.get('total_available', question_events.get('total', 0)),
                'quality': question_events.get('quality', {}),
                'summary': question_events.get('summary', {}),
                'cold_start_summary': question_events.get('cold_start_summary', {}),
                'cold_start_questions': question_events.get('cold_start_questions', []),
                'warnings': question_events.get('warnings', []),
            },
            'compound_works': _compound_works_rows(ctx, limit=200),
            'test_play_audit_rows': report_handlers.test_play_audit_rows(audit_rows, limit=20),
            'audit_recent': [_safe_audit_row(ctx, row) for row in audit_rows[:50]],
        }
    )


def admin_read_overview(ctx):
    logs = report_handlers.analysis_log_status(ctx, stats_history=ctx.engine.get_stats_history(days=90))
    question_report = ctx.question_event_report(limit=5000)
    exposure_events = result_exposure_service.read_events(environ=ctx.environ, limit=300)
    fetish_rows = ctx.build_fetish_log_rows()
    return ctx.jsonify(
        {
            'status': 'ok',
            'share_links_count': share_links_service.count_links(environ=ctx.environ),
            'improvement_candidates': improvement_candidates_service.build_candidates(
                question_report,
                exposure_events=exposure_events,
                fetish_rows=fetish_rows,
            ),
            'low_learning_candidates': improvement_candidates_service.low_learning_candidates(
                fetish_rows,
                exposure_events=exposure_events,
            ),
            'available_endpoints': [
                '/api/admin/preflight',
                '/api/admin/fetishes_snapshot',
                '/api/admin/learning_stats',
                '/api/admin/question_stats',
                '/api/admin/operations_snapshot',
                '/api/admin/quality_report',
                '/api/admin/works_health',
                '/api/admin/audit_log',
                '/api/admin/maintenance_checklist',
                '/api/admin/matrix_health',
                '/api/admin/funnel_metrics',
                '/api/admin/player_fetishes',
                '/api/admin/added_fetishes',
                '/api/admin/promoted_fetish_history',
                '/api/admin/fetish_log_rows',
                '/api/admin/low_exposure_fetishes',
                '/api/admin/recent_fetish_ranking',
                '/api/admin/dry_run_guess',
                '/api/admin/result_exposures',
                '/api/admin/result_exposures/recent',
                '/api/admin/result_exposure_trend',
                '/api/admin/result_exposure_factors',
                '/api/admin/result_exposures/backfill',
                '/api/admin/question_events',
                '/api/admin/share_events',
                '/api/admin/share_notes',
                '/api/admin/export_stats_history',
                '/api/admin/matrix_backups',
                '/api/admin/works_link_queue',
                '/api/admin/compound_works',
            ],
            'analysis_log_status': logs,
        }
    )


def _safe_audit_row(ctx, row):
    safe = {
        'ts': str(row.get('ts', '')),
        'action': row.get('action', ''),
        'status': row.get('status', ''),
        'detail': row.get('detail', {}) if isinstance(row.get('detail'), dict) else {},
    }
    if row.get('method'):
        safe['method'] = row.get('method', '')
    if row.get('path'):
        safe['path'] = row.get('path', '')
    return safe


def audit_log(ctx):
    rows = [
        _safe_audit_row(ctx, row)
        for row in ctx.recent_audit(ctx.bounded_int(ctx.request.args.get('limit'), 500, 1, 500))
    ]
    if ctx.request.args.get('format') == 'csv':
        fieldnames = ['ts', 'action', 'status', 'method', 'path', 'detail']
        csv_rows = []
        for row in rows:
            csv_rows.append(
                {
                    'ts': row['ts'],
                    'action': row['action'],
                    'status': row['status'],
                    'method': row.get('method', ''),
                    'path': row.get('path', ''),
                    'detail': ctx.json_dumps(row.get('detail', {}), ensure_ascii=False),
                }
            )
        return ctx.Response(
            csv_text(csv_rows, fieldnames),
            mimetype='text/csv; charset=utf-8',
            headers={'Content-Disposition': 'attachment; filename="admin_audit_log.csv"'},
        )
    return ctx.jsonify({'status': 'ok', 'audit_log': rows})


def preflight(ctx):
    checks = []

    def add_check(name, ok, detail=''):
        checks.append({'name': name, 'ok': bool(ok), 'detail': detail})

    add_check(
        'secret_key_configured',
        bool(ctx.environ.get('SECRET_KEY')),
        'configured' if ctx.environ.get('SECRET_KEY') else 'development fallback in use',
    )
    add_check(
        'admin_pass_configured',
        bool(ctx.environ.get('ADMIN_PASS')),
        'configured' if ctx.environ.get('ADMIN_PASS') else 'missing',
    )
    add_check('storage_available', True, 'postgres' if ctx.use_db() else 'local_json')
    yes_rows = ctx.engine.matrix.get('yes', [])
    total_rows = ctx.engine.matrix.get('total', [])
    expected_rows = len(ctx.engine.fetishes)
    expected_cols = len(ctx.engine.questions)
    matrix_ok = (
        len(yes_rows) == expected_rows
        and len(total_rows) == expected_rows
        and all(len(row) == expected_cols for row in yes_rows)
        and all(len(row) == expected_cols for row in total_rows)
    )
    add_check(
        'matrix_shape',
        matrix_ok,
        f'yes={len(yes_rows)} total={len(total_rows)} / fetishes={expected_rows} questions={expected_cols}',
    )
    backups = ctx.list_matrix_import_backups()
    backup_keep = ctx.bounded_int(ctx.environ.get('MATRIX_IMPORT_BACKUP_KEEP'), 20, 1, 1000)
    add_check(
        'matrix_backups_retained',
        len(backups) <= backup_keep,
        f'{len(backups)} import backups present / keep={backup_keep}',
    )
    ogp_font = ogp_service.cjk_font_status()
    add_check('ogp_cjk_font_available', ogp_font['available'], ogp_font['detail'])
    add_check('csrf_enabled', ctx.should_enforce_runtime_guard('csrf'), 'enabled for non-test runtime')
    logs = report_handlers.analysis_log_status(ctx, stats_history=ctx.engine.get_stats_history(days=90))
    add_check('analysis_stats_history_rows', True, f'{logs["stats_history_count"]} active stats_history days')
    share_storage = logs.get('share_event_storage') or {}
    question_storage = logs.get('question_event_storage') or {}
    share_storage_ok = bool(share_storage.get('parent_writable') and share_storage.get('file_writable'))
    question_storage_ok = bool(question_storage.get('parent_writable') and question_storage.get('file_writable'))
    add_check(
        'analysis_share_events_rows',
        share_storage_ok,
        f'{logs["share_event_count"]} share_events rows / {"ready" if logs["share_ready"] else "insufficient for analysis"} / path={share_storage.get("path", "unknown")} / writable={share_storage_ok}',
    )
    add_check(
        'analysis_question_events_rows',
        question_storage_ok,
        f'{logs["question_event_count"]} question_events rows / {"ready" if logs["question_ready"] else "insufficient for analysis"} / path={question_storage.get("path", "unknown")} / writable={question_storage_ok}',
    )
    add_check('rate_limit_enabled', ctx.should_enforce_runtime_guard('rate_limit'), 'enabled for non-test runtime')
    ok = all(check['ok'] for check in checks)
    return ctx.jsonify({'status': 'ok' if ok else 'warning', 'checks': checks})


def list_compound_works(ctx):
    items = ctx.list_compound_works()
    result = []
    for item in items:
        idx_a = ctx.engine.index_of(item['id_a'])
        idx_b = ctx.engine.index_of(item['id_b'])
        name_a = ctx.engine.fetishes[idx_a]['name'] if idx_a is not None else f'id={item["id_a"]}'
        name_b = ctx.engine.fetishes[idx_b]['name'] if idx_b is not None else f'id={item["id_b"]}'
        result.append({**item, 'name_a': name_a, 'name_b': name_b})
    return ctx.jsonify(result)


def set_compound_works(ctx):
    data = ctx.request.get_json(silent=True) or {}
    try:
        id_a = int(data['id_a'])
        id_b = int(data['id_b'])
    except (KeyError, ValueError, TypeError):
        return ctx.jsonify({'status': 'error', 'message': 'id_a と id_b が必要です'}), 400
    if id_a == id_b:
        return ctx.jsonify({'status': 'error', 'message': '同じIDは指定できません'}), 400
    if ctx.engine.index_of(id_a) is None or ctx.engine.index_of(id_b) is None:
        return ctx.jsonify({'status': 'error', 'message': '存在しない性癖IDです'}), 400
    raw = data.get('works', [])
    if isinstance(raw, str):
        raw = [work.strip() for work in raw.split(',') if work.strip()]
    works = ctx.parse_works_list(raw)
    if not works:
        return ctx.jsonify({'status': 'error', 'message': '作品を1件以上入力してください'}), 400
    if len(works) > 10:
        return ctx.jsonify({'status': 'error', 'message': '作品は10件以内'}), 400
    try:
        key = ctx.set_compound_works(id_a, id_b, works)
    except ValueError as exc:
        return ctx.jsonify({'status': 'error', 'message': str(exc)}), 400
    ctx.write_audit(
        'compound_works_update',
        'ok',
        {'id_a': min(id_a, id_b), 'id_b': max(id_a, id_b), 'work_count': len(works)},
        ctx.request,
    )
    return ctx.jsonify({'status': 'ok', 'key': key, 'works': works})


def delete_compound_works(ctx, key):
    parts = key.split(',')
    if len(parts) != 2:
        return ctx.jsonify({'status': 'error', 'message': '不正なキーです'}), 400
    try:
        id_a, id_b = int(parts[0]), int(parts[1])
    except ValueError:
        return ctx.jsonify({'status': 'error', 'message': '不正なキーです'}), 400
    ok = ctx.delete_compound_works(id_a, id_b)
    if not ok:
        return ctx.jsonify({'status': 'error', 'message': '見つかりません'}), 404
    ctx.write_audit(
        'compound_works_delete',
        'ok',
        {'id_a': min(id_a, id_b), 'id_b': max(id_a, id_b)},
        ctx.request,
    )
    return ctx.jsonify({'status': 'deleted', 'key': key})


def toggle_question(ctx, q_id):
    if q_id < 0 or q_id >= len(ctx.engine.questions):
        return ctx.jsonify({'status': 'error', 'message': '不正な質問IDです'}), 400
    disabled = ctx.engine.toggle_question_disabled(q_id)
    return ctx.jsonify({'status': 'ok', 'disabled': disabled})


def update_params(ctx):
    data = ctx.request.get_json(silent=True) or {}
    updated = {}
    errors = []
    for key, value in data.items():
        try:
            ctx.engine.set_config(key, value)
            updated[key] = ctx.engine.config[key]
        except (ValueError, KeyError) as exc:
            errors.append(str(exc))
    return ctx.jsonify({'status': 'ok', 'updated': updated, 'errors': errors})


def cleanup_sessions(ctx):
    deleted = ctx.cleanup_sessions()
    return ctx.jsonify({'status': 'ok', 'deleted': deleted})


def add_fetish(ctx):
    data = ctx.request.get_json(silent=True) or {}
    name = data.get('name', '').strip()
    desc = data.get('desc', '').strip()
    if not name:
        return ctx.jsonify({'status': 'error', 'message': '名前を入力してください'}), 400
    if len(name) > 100:
        return ctx.jsonify({'status': 'error', 'message': '名前は100文字以内'}), 400
    if len(desc) > 500:
        return ctx.jsonify({'status': 'error', 'message': '説明は500文字以内'}), 400
    existing = next((fetish for fetish in ctx.engine.fetishes if fetish['name'] == name), None)
    if existing:
        return ctx.jsonify({'status': 'exists', 'fetish_id': existing['id'], 'fetish_name': existing['name']})
    if not desc:
        desc = name
    _, db_id = ctx.engine.add_fetish(name, desc, {})
    return ctx.jsonify({'status': 'created', 'fetish_id': db_id, 'fetish_name': name})


def capture_priors(ctx):
    ctx.engine.capture_learned_priors()
    return ctx.jsonify({'status': 'ok'})


def lookup_fetish(ctx, fetish_id):
    for fetish in ctx.engine.fetishes:
        if fetish.get('id') == fetish_id:
            return ctx.jsonify(
                {
                    'status': 'ok',
                    'id': fetish_id,
                    'name': fetish.get('name', ''),
                    'is_player_fetish': fetish_id >= ctx.player_fetish_base_id,
                }
            )
    return ctx.jsonify({'status': 'error', 'message': '性癖が見つかりません'}), 404


def promote_fetish(ctx, fetish_id):
    if fetish_id < ctx.player_fetish_base_id:
        return ctx.jsonify({'status': 'error', 'message': 'シード性癖は格上げ不要です'}), 400
    new_id = ctx.engine.promote_fetish(fetish_id)
    if new_id is None:
        return ctx.jsonify({'status': 'error', 'message': '見つかりません'}), 404
    promoted = next((fetish for fetish in ctx.engine.fetishes if fetish.get('id') == new_id), {})
    reassign_report = result_exposure_service.safe_reassign_fetish_id(
        fetish_id,
        new_id,
        fetish_name=promoted.get('name', ''),
        environ=ctx.environ,
    )
    ctx.write_audit(
        'promote_fetish',
        'ok',
        {
            'old_id': fetish_id,
            'new_id': new_id,
            'result_exposure_reassign': reassign_report,
        },
        ctx.request,
    )
    return ctx.jsonify(
        {
            'status': 'promoted',
            'old_id': fetish_id,
            'new_id': new_id,
            'result_exposure_reassign': reassign_report,
        }
    )


def _repair_mappings_from_request(ctx):
    data = ctx.request.get_json(silent=True) or {}
    raw = data.get('mappings') or []
    mappings = []
    if isinstance(raw, dict):
        raw = [{'old_id': key, 'new_id': value} for key, value in raw.items()]
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            old_id = int(item.get('old_id'))
            new_id = int(item.get('new_id'))
        except (TypeError, ValueError):
            continue
        if old_id >= ctx.player_fetish_base_id and 0 <= new_id < ctx.player_fetish_base_id:
            mappings.append((old_id, new_id))
    return mappings


def _manual_stats_history_mappings_from_request(ctx):
    data = ctx.request.get_json(silent=True) or {}
    raw = data.get('mappings') or []
    mappings = []
    seen_old = set()
    if isinstance(raw, dict):
        raw = [{'old_id': key, 'new_id': value} for key, value in raw.items()]
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            old_id = int(item.get('old_id'))
            new_id = int(item.get('new_id'))
        except (TypeError, ValueError):
            continue
        if old_id == new_id or old_id in seen_old:
            continue
        if 0 <= old_id < ctx.player_fetish_base_id and 0 <= new_id < ctx.player_fetish_base_id:
            mappings.append((old_id, new_id))
            seen_old.add(old_id)
    return mappings


def move_stats_history(ctx):
    data = ctx.request.get_json(silent=True) or {}
    mappings = _manual_stats_history_mappings_from_request(ctx)
    if not mappings:
        return (
            ctx.jsonify(
                {
                    'status': 'error',
                    'message': 'mappings に正式ID同士の old_id/new_id を指定してください',
                    'required_confirm_text': 'MOVE_STATS_HISTORY',
                }
            ),
            400,
        )
    if data.get('dry_run') is True:
        report = ctx.engine.promoted_stats_history_repair_report(mappings)
        return ctx.jsonify({'status': 'ok', 'mode': 'dry_run', 'required_confirm_text': 'MOVE_STATS_HISTORY', **report})
    confirm_error = ctx.require_confirm('MOVE_STATS_HISTORY')
    if confirm_error:
        return confirm_error
    report = ctx.engine.repair_promoted_stats_history(mappings)
    ctx.write_audit(
        'move_stats_history',
        'ok',
        {
            'mapping_count': report.get('mapping_count', 0),
            'total_value': report.get('total_value', 0),
            'mappings': [{'old_id': old_id, 'new_id': new_id} for old_id, new_id in mappings],
        },
        ctx.request,
    )
    return ctx.jsonify({'status': 'ok', 'mode': 'applied', 'required_confirm_text': 'MOVE_STATS_HISTORY', **report})


def repair_promoted_stats_history(ctx):
    data = ctx.request.get_json(silent=True) or {}
    mappings = _repair_mappings_from_request(ctx)
    if not mappings:
        return (
            ctx.jsonify(
                {
                    'status': 'error',
                    'message': 'mappings に old_id/new_id を指定してください',
                    'required_confirm_text': 'REPAIR_PROMOTED_STATS',
                }
            ),
            400,
        )
    if ctx.request.method == 'GET' or data.get('dry_run') is True:
        report = ctx.engine.promoted_stats_history_repair_report(mappings)
        return ctx.jsonify(
            {'status': 'ok', 'mode': 'dry_run', 'required_confirm_text': 'REPAIR_PROMOTED_STATS', **report}
        )
    confirm_error = ctx.require_confirm('REPAIR_PROMOTED_STATS')
    if confirm_error:
        return confirm_error
    report = ctx.engine.repair_promoted_stats_history(mappings)
    ctx.write_audit(
        'repair_promoted_stats_history',
        'ok',
        {
            'mapping_count': report.get('mapping_count', 0),
            'total_value': report.get('total_value', 0),
            'mappings': [{'old_id': old_id, 'new_id': new_id} for old_id, new_id in mappings],
        },
        ctx.request,
    )
    return ctx.jsonify({'status': 'ok', 'mode': 'applied', 'required_confirm_text': 'REPAIR_PROMOTED_STATS', **report})


def edit_question(ctx, q_idx):
    data = ctx.request.get_json(silent=True) or {}
    text = (data.get('text') or '').strip()
    if not text:
        return ctx.jsonify({'status': 'error', 'message': 'text が必要です'}), 400
    if len(text) > 120:
        return ctx.jsonify({'status': 'error', 'message': '質問は120文字以内'}), 400
    ok = ctx.engine.edit_question(q_idx, text)
    if not ok:
        return ctx.jsonify({'status': 'error', 'message': '不正なインデックスです'}), 404
    return ctx.jsonify({'status': 'ok', 'q_idx': q_idx, 'text': text})


def edit_fetish(ctx, fetish_id):
    data = ctx.request.get_json(silent=True) or {}
    name = data.get('name', '').strip() or None
    desc = data.get('desc', '').strip() if 'desc' in data else None
    works = None
    if 'works' in data:
        raw = data['works']
        if isinstance(raw, str):
            raw = [work.strip() for work in raw.split(',') if work.strip()]
        elif not isinstance(raw, list):
            return ctx.jsonify({'status': 'error', 'message': 'works はリストまたは文字列で指定してください'}), 400
        works = ctx.parse_works_list(raw)
    if name is not None and len(name) > 50:
        return ctx.jsonify({'status': 'error', 'message': '名前は50文字以内'}), 400
    if works is not None and len(works) > 10:
        return ctx.jsonify({'status': 'error', 'message': '作品は10件以内'}), 400
    ok = ctx.engine.edit_fetish(fetish_id, name=name, desc=desc, works=works)
    if not ok:
        return ctx.jsonify({'status': 'error', 'message': '見つかりません'}), 404
    idx = ctx.engine.index_of(fetish_id)
    fetish = ctx.engine.fetishes[idx]
    ctx.write_audit(
        'fetish_update',
        'ok',
        {
            'fetish_id': fetish_id,
            'updated_fields': [
                field for field, value in (('name', name), ('desc', desc), ('works', works)) if value is not None
            ],
            'work_count': len(works) if works is not None else None,
        },
        ctx.request,
    )
    return ctx.jsonify(
        {
            'status': 'ok',
            'name': fetish['name'],
            'desc': fetish['desc'],
            'works': ctx.engine.get_recommended_works(fetish_id),
        }
    )


def _export_player_fetishes_to_restore(ctx, exported_fetishes):
    return matrix_handlers._export_player_fetishes_to_restore(ctx, exported_fetishes)


def _missing_export_player_fetishes(ctx, exported_fetishes):
    return matrix_handlers._missing_export_player_fetishes(ctx, exported_fetishes)


def _backup_integer(value, label):
    return matrix_handlers._backup_integer(value, label)


def _matrix_backup_format_version(payload):
    return matrix_handlers._matrix_backup_format_version(payload)


def _adapt_matrix_rows_to_current_questions(ctx, rows, exported_questions, exported_fetishes, fetishes_to_restore):
    return matrix_handlers._adapt_matrix_rows_to_current_questions(
        ctx, rows, exported_questions, exported_fetishes, fetishes_to_restore
    )


def _import_validation_report(ctx, rows, fetishes_to_restore):
    return matrix_handlers._import_validation_report(ctx, rows, fetishes_to_restore)


def _matrix_import_completeness_error(ctx, report, expected_rows):
    return matrix_handlers._matrix_import_completeness_error(ctx, report, expected_rows)


def export_matrix(ctx):
    return matrix_handlers.export_matrix(ctx)


def import_matrix(ctx):
    return matrix_handlers.import_matrix(ctx)


def import_matrix_dry_run(ctx):
    return matrix_handlers.import_matrix_dry_run(ctx)


def matrix_backups(ctx):
    return matrix_handlers.matrix_backups(ctx)


def restore_matrix_backup(ctx, name):
    return matrix_handlers.restore_matrix_backup(ctx, name)


def merge_fetishes(ctx):
    data = ctx.request.get_json(silent=True) or {}
    id_keep = data.get('id_keep')
    id_remove = data.get('id_remove')
    new_name = (data.get('new_name') or '').strip() or None
    new_desc = (data.get('new_desc') or '').strip() or None
    if id_keep is None or id_remove is None:
        return ctx.jsonify({'status': 'error', 'message': 'id_keep と id_remove が必要です'}), 400
    try:
        id_keep = int(id_keep)
        id_remove = int(id_remove)
    except (TypeError, ValueError):
        return ctx.jsonify({'status': 'error', 'message': 'id_keep と id_remove は整数で指定してください'}), 400
    confirm_error = ctx.require_confirm('MERGE')
    if confirm_error:
        return confirm_error
    ok = ctx.engine.merge_fetishes(id_keep, id_remove, new_name=new_name, new_desc=new_desc)
    if not ok:
        return ctx.jsonify({'status': 'error', 'message': '性癖が見つかりません'}), 404
    idx = ctx.engine.index_of(id_keep)
    name = ctx.engine.fetishes[idx]['name'] if idx is not None else '(unknown)'
    return ctx.jsonify({'status': 'merged', 'id_keep': id_keep, 'name': name})


def work_catalog_admin(ctx):
    snapshot = ctx.engine.work_catalog_admin_snapshot()
    return ctx.jsonify({'status': 'ok', **snapshot})


def mutate_work_catalog_admin(ctx):
    data = ctx.request.get_json(silent=True) or {}
    operation = str(data.get('operation') or '')
    allowed = {
        'master_create',
        'master_update',
        'master_delete',
        'edition_create',
        'edition_update',
        'edition_delete',
        'identifier_create',
        'identifier_update',
        'identifier_delete',
        'alias_create',
        'alias_update',
        'alias_delete',
        'link_update',
        'review_decide',
        'review_apply_manifest',
        'seed_overrides_apply_manifest',
        'corrections_apply_manifest',
        'bibliography_apply_manifest',
    }
    if operation not in allowed:
        return ctx.jsonify({'status': 'error', 'message': '不正な作品catalog操作です'}), 400
    payload = data.get('payload')
    if not isinstance(payload, dict):
        return ctx.jsonify({'status': 'error', 'message': 'payloadはobjectで指定してください'}), 400
    expected_digest = str(data.get('expected_digest') or '')
    if len(expected_digest) != 64:
        return ctx.jsonify({'status': 'error', 'message': 'expected_digestが必要です'}), 400
    destructive = (
        operation.endswith('_delete')
        or operation == 'review_apply_manifest'
        or operation == 'corrections_apply_manifest'
        or operation == 'seed_overrides_apply_manifest'
        or operation == 'bibliography_apply_manifest'
        or (operation == 'review_decide' and payload.get('decision') == 'merge')
    )
    if destructive:
        confirm_error = ctx.require_confirm('WORK_CATALOG')
        if confirm_error:
            return confirm_error
    try:
        result = ctx.engine.mutate_work_catalog(operation, payload, expected_digest=expected_digest)
    except ValueError as exc:
        message = str(exc)
        status = 409 if 'conflict' in message else 400
        return ctx.jsonify({'status': 'error', 'message': message}), status
    audit_payload = {'operation': operation}
    for key in ('work_id', 'edition_id', 'identifier_id', 'alias_id', 'link_id', 'review_id'):
        if payload.get(key):
            audit_payload[key] = str(payload[key])[:80]
    if operation == 'seed_overrides_apply_manifest':
        manifest = payload.get('seed_overrides', {})
        encoded_manifest = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode(
            'utf-8'
        )
        audit_payload.update(
            normalization_count=len(manifest.get('title_normalizations', [])),
            removal_count=len(manifest.get('remove_display_titles', [])),
            manifest_sha256=hashlib.sha256(encoded_manifest).hexdigest(),
        )
    if operation == 'corrections_apply_manifest':
        manifest = payload.get('corrections_manifest', {})
        corrections = manifest.get('corrections', [])
        encoded_manifest = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode(
            'utf-8'
        )
        audit_payload.update(
            correction_count=len(corrections),
            split_count=sum(row.get('type') == 'split_misassigned_edition' for row in corrections),
            retitle_count=sum(row.get('type') == 'retitle_identity' for row in corrections),
            manifest_sha256=hashlib.sha256(encoded_manifest).hexdigest(),
            reviewed_by=str(manifest.get('reviewed_by') or '')[:80],
        )
    if operation == 'bibliography_apply_manifest':
        manifest = payload.get('bibliography_manifest', {})
        entries = manifest.get('entries', [])
        encoded_manifest = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode(
            'utf-8'
        )
        audit_payload.update(
            entry_count=len(entries),
            edition_count=sum(bool(row.get('edition')) for row in entries),
            manifest_sha256=hashlib.sha256(encoded_manifest).hexdigest(),
            reviewed_by=str(manifest.get('reviewed_by') or '')[:80],
        )
    if operation == 'review_apply_manifest':
        manifest = payload.get('decision_manifest', {})
        decisions = manifest.get('decisions', [])
        encoded_manifest = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode(
            'utf-8'
        )
        audit_payload.update(
            decision_count=len(decisions),
            merge_count=sum(row.get('decision') == 'merge' for row in decisions),
            keep_separate_count=sum(row.get('decision') == 'keep_separate' for row in decisions),
            manifest_sha256=hashlib.sha256(encoded_manifest).hexdigest(),
            reviewed_by=str(manifest.get('reviewed_by') or '')[:80],
        )
    ctx.write_audit('work_catalog_mutation', 'ok', audit_payload, ctx.request)
    return ctx.jsonify({'status': 'ok', **result})


def works_review(ctx):
    rows = []
    for fetish in _fetishes_with_recommended_works(ctx):
        for work in fetish.get('works', []):
            title = work['title'] if isinstance(work, dict) else work
            url = work.get('url', '') if isinstance(work, dict) else ''
            asin = ''
            url = _admin_work_url(ctx, work, title)
            if url:
                match = ctx.re_search(r'/dp/([A-Z0-9]{10})', url)
                asin = match.group(1) if match else ''
            rows.append((fetish['name'], title, asin, url))
    html = (
        """<!DOCTYPE html><html lang="ja"><head><meta charset="UTF-8">
<title>作品リンク確認</title>
<style>
body{font-family:sans-serif;font-size:13px;background:#111;color:#ddd;padding:16px;}
table{border-collapse:collapse;width:100%;}
th{background:#222;padding:6px 10px;text-align:left;position:sticky;top:0;z-index:1;}
td{padding:5px 10px;border-bottom:1px solid #222;vertical-align:top;}
tr:hover td{background:#1a1a1a;}
a{color:#7af0a0;}
.no-url{color:#e94560;}
input{background:#222;color:#ddd;border:1px solid #444;padding:4px 8px;border-radius:4px;margin-bottom:10px;width:300px;}
</style></head><body>
<h2>作品リンク確認（"""
        + str(len(rows))
        + """件）</h2>
<input type="text" id="q" placeholder="性癖名や作品名で絞り込み...">
<table id="tbl">
<tr><th>性癖</th><th>作品タイトル</th><th>ASIN</th><th>リンク</th></tr>"""
    )
    for fetish_name, title, asin, url in rows:
        fetish_name_e = ctx.html_escape(str(fetish_name))
        title_e = ctx.html_escape(str(title))
        asin_e = ctx.html_escape(str(asin))
        if url:
            url_e = ctx.html_escape(str(url), quote=True)
            link = f'<a href="{url_e}" target="_blank" rel="noopener">Kindle</a>'
        else:
            link = '<span class="no-url">URLなし</span>'
        html += f'<tr><td>{fetish_name_e}</td><td>{title_e}</td><td>{asin_e}</td><td>{link}</td></tr>'
    html += """</table>
<script>
document.getElementById("q").addEventListener("input", () => {
  const q = document.getElementById("q").value.toLowerCase();
  document.querySelectorAll("#tbl tr:not(:first-child)").forEach(tr => {
    tr.style.display = tr.textContent.toLowerCase().includes(q) ? "" : "none";
  });
});
</script>
</body></html>"""
    return ctx.Response(html, mimetype='text/html')


def fetish_similarity(ctx):
    data = ctx.request.get_json(silent=True) or {}
    id_a = data.get('id_a')
    id_b = data.get('id_b')
    if id_a is None or id_b is None:
        return ctx.jsonify({'status': 'error', 'message': 'id_a と id_b が必要です'}), 400
    try:
        id_a = int(id_a)
        id_b = int(id_b)
    except (TypeError, ValueError):
        return ctx.jsonify({'status': 'error', 'message': 'id_a と id_b は整数で指定してください'}), 400
    result = ctx.engine.fetish_similarity(id_a, id_b)
    if result is None:
        return ctx.jsonify({'status': 'error', 'message': '性癖が見つかりません'}), 404
    return ctx.jsonify({'status': 'ok', **result})


def create_blueprint(ctx_factory, require_admin, require_admin_or_read=None):
    bp = Blueprint('admin_routes', __name__)
    require_admin_or_read = require_admin_or_read or require_admin

    matrix_routes.register_routes(
        bp,
        ctx_factory=ctx_factory,
        require_admin=require_admin,
        require_admin_or_read=require_admin_or_read,
        export_matrix=lambda ctx: export_matrix(ctx),
        import_matrix=lambda ctx: import_matrix(ctx),
        import_matrix_dry_run=lambda ctx: import_matrix_dry_run(ctx),
        matrix_backups=lambda ctx: matrix_backups(ctx),
        restore_matrix_backup=lambda ctx, name: restore_matrix_backup(ctx, name),
    )

    works_routes.register_routes(
        bp,
        ctx_factory=ctx_factory,
        require_admin=require_admin,
        require_admin_or_read=require_admin_or_read,
        list_compound_works=lambda ctx: list_compound_works(ctx),
        set_compound_works=lambda ctx: set_compound_works(ctx),
        delete_compound_works=lambda ctx, key: delete_compound_works(ctx, key),
        works_review=lambda ctx: works_review(ctx),
        work_catalog_admin=lambda ctx: work_catalog_admin(ctx),
        mutate_work_catalog_admin=lambda ctx: mutate_work_catalog_admin(ctx),
        works_link_queue_payload=lambda ctx, **kwargs: works_link_queue_payload(ctx, **kwargs),
    )

    analytics_routes.register_routes(
        bp,
        ctx_factory=ctx_factory,
        require_admin=require_admin,
        require_admin_or_read=require_admin_or_read,
        resolve_handler=lambda name: globals().get(name) or getattr(report_handlers, name),
    )

    operations_routes.register_routes(
        bp,
        ctx_factory=ctx_factory,
        require_admin_or_read=require_admin_or_read,
        resolve_handler=lambda name: globals().get(name) or getattr(report_handlers, name),
    )

    page_routes.register_routes(
        bp,
        ctx_factory=ctx_factory,
        require_admin=require_admin,
        resolve_handler=lambda name: globals()[name],
    )

    mutation_routes.register_routes(
        bp,
        ctx_factory=ctx_factory,
        require_admin=require_admin,
        require_admin_or_read=require_admin_or_read,
        resolve_handler=lambda name: globals()[name],
    )

    return bp
