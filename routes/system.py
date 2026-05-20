def health(ctx):
    db_ok = False
    matrix_rows = len(ctx.engine.matrix.get('yes', []))
    matrix_cols = len(ctx.engine.matrix.get('yes', [[]])[0]) if matrix_rows else 0
    matrix_ok = (
        matrix_rows == len(ctx.engine.fetishes)
        and matrix_cols == len(ctx.engine.questions)
        and len(ctx.engine.matrix.get('total', [])) == len(ctx.engine.fetishes)
        and all(len(row) == len(ctx.engine.questions) for row in ctx.engine.matrix.get('yes', []))
        and all(len(row) == len(ctx.engine.questions) for row in ctx.engine.matrix.get('total', []))
    )
    backup_path = ctx.join_path(ctx.app_dir, 'data', 'matrix_backup.json')
    backup_mtime = None
    if ctx.path_exists(backup_path):
        backup_mtime = int(ctx.path_getmtime(backup_path))
    matrix_path = ctx.data_path('matrix.json')
    matrix_mtime = int(ctx.path_getmtime(matrix_path)) if ctx.path_exists(matrix_path) else None
    if ctx.use_db():
        conn = None
        try:
            conn = ctx.get_conn()
            conn.cursor().execute('SELECT 1')
            db_ok = True
        except Exception:
            pass
        finally:
            if conn is not None:
                ctx.put_conn(conn)
    error_total = ctx.error_counts['4xx'] + ctx.error_counts['5xx']
    degraded_reasons = []
    if not matrix_ok:
        degraded_reasons.append('matrix_shape')
    if ctx.error_counts['5xx'] >= int(ctx.environ.get('HEALTH_5XX_DEGRADED_THRESHOLD', '5')):
        degraded_reasons.append('5xx_threshold')
    if error_total >= int(ctx.environ.get('HEALTH_ERROR_DEGRADED_THRESHOLD', '50')):
        degraded_reasons.append('error_threshold')
    if ctx.use_db() and not db_ok:
        degraded_reasons.append('db_unavailable')
    return ctx.jsonify({
        'status': 'ok' if not degraded_reasons else 'degraded',
        'degraded_reasons': degraded_reasons,
        'db': db_ok,
        'storage': 'postgres' if ctx.use_db() else 'local_json',
        'fetishes': len(ctx.engine.fetishes),
        'questions': len(ctx.engine.questions),
        'matrix': {'rows': matrix_rows, 'cols': matrix_cols, 'ok': matrix_ok},
        'backup': {'matrix_backup_mtime': backup_mtime},
        'runtime': {
            'started_at': ctx.app_started_at,
            'uptime_seconds': int(ctx.time()) - ctx.app_started_at,
            'local_sessions': ctx.local_session_count(),
            'error_counts': dict(ctx.error_counts),
        },
        'persistence': {
            'matrix_saved_mtime': matrix_mtime,
            'audit_entries': len(ctx.recent_audit(500)),
        },
    })


def manifest(ctx):
    path = ctx.join_path(ctx.static_folder, 'manifest.json')
    with open(path, encoding='utf-8') as f:
        body = f.read()
    return ctx.Response(body, mimetype='application/manifest+json', headers={'Cache-Control': 'no-cache'})


def service_worker(ctx):
    return ctx.render_template('sw.js', version=ctx.app_version), 200, {
        'Content-Type': 'application/javascript',
        'Cache-Control': 'no-cache',
    }


def offline(ctx):
    return ctx.render_template('offline.html')
