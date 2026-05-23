from flask import Blueprint
from services.works_links import collect_work_link_queue


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
    matrix_heatmap = ctx.engine.get_matrix_heatmap(n_fetishes=20, n_questions=20)
    axis_stats = ctx.engine.get_axis_stats()
    quality = ctx.engine.get_quality_report()
    maintenance = ctx.build_admin_maintenance_checklist()
    share_events = ctx.share_event_report(limit=1000)
    return ctx.render_template(
        'admin.html',
        stats=stats,
        play_count=app_stats['play_count'],
        learn_count=app_stats['learn_count'],
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
        csrf_token=ctx.csrf_token(),
        csrf_expires_at=int(ctx.session.get('admin_csrf_issued_at', 0) + int(ctx.environ.get('ADMIN_CSRF_TTL_SECONDS', '7200'))),
        audit_rows=ctx.recent_audit(20),
        matrix_backups=ctx.list_matrix_import_backups(),
    )



def works_link_queue_payload(engine, *, sample_limit=20):
    return collect_work_link_queue(engine.fetishes, sample_limit=sample_limit)


def export_log(ctx):
    log = ctx.engine.get_fetish_log()
    fetish_map = {fetish['id']: fetish['name'] for fetish in ctx.engine.fetishes}
    lines = ['id,name,guessed,correct,wrong,accuracy']
    for fid, entry in sorted(log.items(), key=lambda item: -item[1].get('guessed', 0)):
        name = fetish_map.get(fid, str(fid))
        guessed = entry.get('guessed', 0)
        correct = entry.get('correct', 0)
        wrong = entry.get('wrong', 0)
        acc = f"{round(correct / guessed * 100, 1)}" if guessed else ''
        name_esc = '"' + name.replace('"', '""') + '"'
        lines.append(f'{fid},{name_esc},{guessed},{correct},{wrong},{acc}')
    return ctx.Response(
        '\n'.join(lines),
        mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': 'attachment; filename="fetish_log.csv"'},
    )


def fetish_history(ctx, fetish_id):
    days = ctx.bounded_int(ctx.request.args.get('days'), 30, 1, 90)
    return ctx.jsonify(ctx.engine.get_fetish_history(fetish_id, days=days))


def fetish_log_rows(ctx):
    return ctx.jsonify({
        'status': 'ok',
        **ctx.paged_fetish_log_rows(ctx.build_fetish_log_rows(), ctx.request.args),
    })


def performance(ctx):
    measurements = []

    def measure(name, fn):
        start = ctx.perf_counter()
        result = fn()
        elapsed = (ctx.perf_counter() - start) * 1000
        measurements.append({'name': name, 'ms': round(elapsed, 3)})
        return result

    measure('get_question_stats', ctx.engine.get_question_stats)
    measure('get_learning_stats', ctx.engine.get_learning_stats)
    measure('get_fetish_log', ctx.engine.get_fetish_log)
    measure('best_question_empty', lambda: ctx.best_question(ctx.engine, {}, set()))
    return ctx.jsonify({'status': 'ok', 'measurements': measurements})


def recent_fetish_ranking(ctx):
    days = ctx.bounded_int(ctx.request.args.get('days'), 7, 1, 90)
    top_n = ctx.bounded_int(ctx.request.args.get('top_n'), 10, 1, 50)
    ranking = ctx.engine.get_recent_fetish_ranking(days=days, top_n=top_n)
    return ctx.jsonify({'ranking': ranking, 'days': days})


def export_stats_history(ctx):
    history = ctx.engine.get_stats_history(days=90)
    lines = ['date,play,learn,correct,wrong']
    for row in history:
        lines.append(
            f"{row['date']},{row.get('play', 0)},{row.get('learn', 0)},"
            f"{row.get('correct', 0)},{row.get('wrong', 0)}"
        )
    return ctx.Response(
        '\n'.join(lines),
        mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': 'attachment; filename="stats_history.csv"'},
    )


def quality_report(ctx):
    return ctx.jsonify(ctx.engine.get_quality_report())


def share_events_report(ctx):
    limit = ctx.bounded_int(ctx.request.args.get('limit'), 500, 1, 5000)
    return ctx.jsonify({'status': 'ok', **ctx.share_event_report(limit=limit)})


def maintenance_checklist(ctx):
    return ctx.jsonify(ctx.build_admin_maintenance_checklist())


def audit_log(ctx):
    rows = ctx.recent_audit(ctx.bounded_int(ctx.request.args.get('limit'), 500, 1, 500))
    if ctx.request.args.get('format') == 'csv':
        lines = ['ts,action,status,method,path,remote_addr,detail']
        for row in rows:
            detail = ctx.json_dumps(row.get('detail', {}), ensure_ascii=False)
            vals = [
                str(row.get('ts', '')),
                row.get('action', ''),
                row.get('status', ''),
                row.get('method', ''),
                row.get('path', ''),
                row.get('remote_addr', ''),
                detail,
            ]
            escaped = ['"' + str(value).replace('"', '""') + '"' for value in vals]
            lines.append(','.join(escaped))
        return ctx.Response(
            '\n'.join(lines),
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
        'SECRET_KEY is set' if ctx.environ.get('SECRET_KEY') else 'SECRET_KEY is using local development fallback',
    )
    add_check(
        'admin_pass_configured',
        bool(ctx.environ.get('ADMIN_PASS')),
        'ADMIN_PASS is set' if ctx.environ.get('ADMIN_PASS') else 'ADMIN_PASS is missing',
    )
    add_check('storage_available', True, 'postgres' if ctx.use_db() else 'local_json')
    add_check(
        'matrix_shape',
        len(ctx.engine.matrix.get('yes', [])) == len(ctx.engine.fetishes),
        f"{len(ctx.engine.matrix.get('yes', []))} matrix rows / {len(ctx.engine.fetishes)} fetishes",
    )
    backups = ctx.list_matrix_import_backups()
    add_check(
        'matrix_backups_retained',
        len(backups) <= int(ctx.environ.get('MATRIX_IMPORT_BACKUP_KEEP', '20')),
        f'{len(backups)} import backups present',
    )
    add_check('csrf_enabled', ctx.should_enforce_runtime_guard('csrf'), 'enabled for non-test runtime')
    add_check('rate_limit_enabled', ctx.should_enforce_runtime_guard('rate_limit'), 'enabled for non-test runtime')
    ok = all(check['ok'] for check in checks)
    return ctx.jsonify({'status': 'ok' if ok else 'warning', 'checks': checks})


def list_compound_works(ctx):
    items = ctx.list_compound_works()
    result = []
    for item in items:
        idx_a = ctx.engine.index_of(item['id_a'])
        idx_b = ctx.engine.index_of(item['id_b'])
        name_a = ctx.engine.fetishes[idx_a]['name'] if idx_a is not None else f"id={item['id_a']}"
        name_b = ctx.engine.fetishes[idx_b]['name'] if idx_b is not None else f"id={item['id_b']}"
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
    raw = data.get('works', [])
    if isinstance(raw, str):
        raw = [work.strip() for work in raw.split(',') if work.strip()]
    works = ctx.parse_works_list(raw)
    if not works:
        return ctx.jsonify({'status': 'error', 'message': '作品を1件以上入力してください'}), 400
    if len(works) > 10:
        return ctx.jsonify({'status': 'error', 'message': '作品は10件以内'}), 400
    key = ctx.set_compound_works(id_a, id_b, works)
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


def promote_fetish(ctx, fetish_id):
    if fetish_id < ctx.player_fetish_base_id:
        return ctx.jsonify({'status': 'error', 'message': 'シード性癖は格上げ不要です'}), 400
    new_id = ctx.engine.promote_fetish(fetish_id)
    if new_id is None:
        return ctx.jsonify({'status': 'error', 'message': '見つかりません'}), 404
    return ctx.jsonify({'status': 'promoted', 'old_id': fetish_id, 'new_id': new_id})


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
    return ctx.jsonify({'status': 'ok', 'name': fetish['name'], 'desc': fetish['desc'], 'works': fetish.get('works', [])})


def export_matrix(ctx):
    fetishes = ctx.engine.fetishes
    questions = ctx.engine.questions
    rows = []
    for fetish_idx, fetish in enumerate(fetishes):
        for question_idx, question in enumerate(questions):
            yes = ctx.engine.matrix['yes'][fetish_idx][question_idx]
            total = ctx.engine.matrix['total'][fetish_idx][question_idx]
            rows.append({
                'fetish_id': fetish['id'],
                'fetish_name': fetish['name'],
                'question_id': question_idx,
                'question_text': question['text'],
                'yes': round(yes, 4),
                'total': round(total, 4),
            })
    exported_at = ctx.strftime('%Y-%m-%dT%H:%M:%SZ', ctx.gmtime())
    payload = ctx.json_dumps({
        'exported_at': exported_at,
        'metadata': {
            'exported_at': exported_at,
            'fetish_count': len(fetishes),
            'question_count': len(questions),
            'matrix_row_count': len(rows),
        },
        'fetishes': fetishes,
        'matrix_rows': rows,
    }, ensure_ascii=False, indent=2)
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
    try:
        report = ctx.engine.validate_matrix_rows(rows)
        complete_error = ctx.matrix_import_completeness_error(report)
        if complete_error:
            return complete_error
        confirm_error = ctx.require_confirm('IMPORT')
        if confirm_error:
            return confirm_error
        backup_path = ctx.snapshot_current_matrix('before_import_matrix')
        count = ctx.engine.import_matrix(rows)
    except ValueError as exc:
        ctx.write_audit('import_matrix', 'error', {'message': str(exc)}, ctx.request)
        return ctx.jsonify({'status': 'error', 'message': str(exc)}), 400
    backup_relpath = ctx.relpath(backup_path, ctx.app_dir)
    ctx.write_audit('import_matrix', 'ok', {
        'imported_rows': count,
        'input_rows': report['input_rows'],
        'skipped_rows': report['skipped_rows'],
        'backup_path': backup_relpath,
    }, ctx.request)
    return ctx.jsonify({'status': 'ok', 'imported_rows': count, 'backup_path': backup_relpath})


def import_matrix_dry_run(ctx):
    data = ctx.request.get_json(silent=True) or {}
    rows = data.get('matrix_rows', [])
    if not rows:
        return ctx.jsonify({'status': 'error', 'message': 'matrix_rows が空です'}), 400
    try:
        report = ctx.engine.validate_matrix_rows(rows)
    except ValueError as exc:
        ctx.write_audit('import_matrix_dry_run', 'error', {'message': str(exc)}, ctx.request)
        return ctx.jsonify({'status': 'error', 'message': str(exc)}), 400
    ctx.write_audit('import_matrix_dry_run', 'ok', report, ctx.request)
    expected_rows = ctx.matrix_import_expected_rows()
    return ctx.jsonify({
        'status': 'ok',
        **report,
        'expected_rows': expected_rows,
        'complete': report['skipped_rows'] == 0 and report['valid_rows'] == expected_rows,
    })


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
    try:
        report = ctx.engine.validate_matrix_rows(rows)
        complete_error = ctx.matrix_import_completeness_error(report)
        if complete_error:
            return complete_error
        confirm_error = ctx.require_confirm('RESTORE')
        if confirm_error:
            return confirm_error
        snapshot = ctx.snapshot_current_matrix('before_restore_matrix_backup')
        count = ctx.engine.import_matrix(rows)
    except ValueError as exc:
        ctx.write_audit('restore_matrix_backup', 'error', {'name': safe_name, 'message': str(exc)}, ctx.request)
        return ctx.jsonify({'status': 'error', 'message': str(exc)}), 400
    snapshot_relpath = ctx.relpath(snapshot, ctx.app_dir)
    ctx.write_audit('restore_matrix_backup', 'ok', {
        'name': safe_name,
        'restored_rows': count,
        'input_rows': report['input_rows'],
        'skipped_rows': report['skipped_rows'],
        'pre_restore_backup': snapshot_relpath,
    }, ctx.request)
    return ctx.jsonify({'status': 'ok', 'restored_rows': count, 'pre_restore_backup': snapshot_relpath})


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


def works_review(ctx):
    rows = []
    for fetish in ctx.engine.fetishes:
        for work in fetish.get('works', []):
            title = work['title'] if isinstance(work, dict) else work
            url = work.get('url', '') if isinstance(work, dict) else ''
            asin = ''
            if url:
                match = ctx.re_search(r'/dp/([A-Z0-9]{10})', url)
                asin = match.group(1) if match else ''
            rows.append((fetish['name'], title, asin, url))
    html = """<!DOCTYPE html><html lang="ja"><head><meta charset="UTF-8">
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
<h2>作品リンク確認（""" + str(len(rows)) + """件）</h2>
<input type="text" id="q" placeholder="性癖名や作品名で絞り込み...">
<table id="tbl">
<tr><th>性癖</th><th>作品タイトル</th><th>ASIN</th><th>リンク</th></tr>"""
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



def create_blueprint(ctx_factory, require_admin):
    bp = Blueprint('admin_routes', __name__)

    @bp.route('/admin')
    @require_admin
    def admin_page_route():
        return admin_page(ctx_factory())

    @bp.route('/api/admin/toggle_question/<int:q_id>', methods=['POST'])
    @require_admin
    def toggle_question_route(q_id):
        return toggle_question(ctx_factory(), q_id)

    @bp.route('/api/admin/params', methods=['POST'])
    @require_admin
    def update_params_route():
        return update_params(ctx_factory())

    @bp.route('/api/admin/cleanup_sessions', methods=['POST'])
    @require_admin
    def cleanup_sessions_route():
        return cleanup_sessions(ctx_factory())

    @bp.route('/api/admin/add_fetish', methods=['POST'])
    @require_admin
    def add_fetish_route():
        return add_fetish(ctx_factory())

    @bp.route('/api/admin/capture_priors', methods=['POST'])
    @require_admin
    def capture_priors_route():
        return capture_priors(ctx_factory())

    @bp.route('/api/admin/promote_fetish/<int:fetish_id>', methods=['POST'])
    @require_admin
    def promote_fetish_route(fetish_id):
        return promote_fetish(ctx_factory(), fetish_id)

    @bp.route('/api/admin/edit_question/<int:q_idx>', methods=['POST'])
    @require_admin
    def edit_question_route(q_idx):
        return edit_question(ctx_factory(), q_idx)

    @bp.route('/api/admin/edit_fetish/<int:fetish_id>', methods=['POST'])
    @require_admin
    def edit_fetish_route(fetish_id):
        return edit_fetish(ctx_factory(), fetish_id)

    @bp.route('/api/admin/compound_works', methods=['GET'])
    @require_admin
    def list_compound_works_route():
        return list_compound_works(ctx_factory())

    @bp.route('/api/admin/compound_works', methods=['POST'])
    @require_admin
    def set_compound_works_route():
        return set_compound_works(ctx_factory())

    @bp.route('/api/admin/compound_works/<path:key>', methods=['DELETE'])
    @require_admin
    def delete_compound_works_route(key):
        return delete_compound_works(ctx_factory(), key)

    @bp.route('/api/admin/merge_fetishes', methods=['POST'])
    @require_admin
    def merge_fetishes_route():
        return merge_fetishes(ctx_factory())

    @bp.route('/api/admin/works_review', methods=['GET'])
    @require_admin
    def works_review_route():
        return works_review(ctx_factory())

    @bp.route('/api/admin/works_link_queue', methods=['GET'])
    @require_admin
    def works_link_queue_route():
        ctx = ctx_factory()
        try:
            sample_limit = max(1, min(int(ctx.request.args.get('sample_limit', 20)), 100))
        except ValueError:
            sample_limit = 20
        return ctx.jsonify(works_link_queue_payload(ctx.engine, sample_limit=sample_limit))

    @bp.route('/api/admin/export_matrix', methods=['GET'])
    @require_admin
    def export_matrix_route():
        return export_matrix(ctx_factory())

    @bp.route('/api/admin/import_matrix', methods=['POST'])
    @require_admin
    def import_matrix_route():
        return import_matrix(ctx_factory())

    @bp.route('/api/admin/import_matrix/dry_run', methods=['POST'])
    @require_admin
    def import_matrix_dry_run_route():
        return import_matrix_dry_run(ctx_factory())

    @bp.route('/api/admin/matrix_backups', methods=['GET'])
    @require_admin
    def matrix_backups_route():
        return matrix_backups(ctx_factory())

    @bp.route('/api/admin/matrix_backups/<path:name>/restore', methods=['POST'])
    @require_admin
    def restore_matrix_backup_route(name):
        return restore_matrix_backup(ctx_factory(), name)

    @bp.route('/api/admin/export_log', methods=['GET'])
    @require_admin
    def export_log_route():
        return export_log(ctx_factory())

    @bp.route('/api/admin/audit_log', methods=['GET'])
    @require_admin
    def audit_log_route():
        return audit_log(ctx_factory())

    @bp.route('/api/admin/preflight', methods=['GET'])
    @require_admin
    def preflight_route():
        return preflight(ctx_factory())

    @bp.route('/api/admin/fetish_history/<int:fetish_id>', methods=['GET'])
    @require_admin
    def fetish_history_route(fetish_id):
        return fetish_history(ctx_factory(), fetish_id)

    @bp.route('/api/admin/fetish_log_rows', methods=['GET'])
    @require_admin
    def fetish_log_rows_route():
        return fetish_log_rows(ctx_factory())

    @bp.route('/api/admin/performance', methods=['GET'])
    @require_admin
    def performance_route():
        return performance(ctx_factory())

    @bp.route('/api/admin/recent_fetish_ranking', methods=['GET'])
    @require_admin
    def recent_fetish_ranking_route():
        return recent_fetish_ranking(ctx_factory())

    @bp.route('/api/admin/export_stats_history', methods=['GET'])
    @require_admin
    def export_stats_history_route():
        return export_stats_history(ctx_factory())

    @bp.route('/api/admin/fetish_similarity', methods=['POST'])
    @require_admin
    def fetish_similarity_route():
        return fetish_similarity(ctx_factory())

    @bp.route('/api/admin/quality_report', methods=['GET'])
    @require_admin
    def quality_report_route():
        return quality_report(ctx_factory())

    @bp.route('/api/admin/share_events', methods=['GET'])
    @require_admin
    def share_events_report_route():
        return share_events_report(ctx_factory())

    @bp.route('/api/admin/maintenance_checklist', methods=['GET'])
    @require_admin
    def maintenance_checklist_route():
        return maintenance_checklist(ctx_factory())

    return bp
