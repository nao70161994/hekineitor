from flask import Blueprint


def _bounded_int_env(environ, name, default, min_value=0, max_value=1000000):
    try:
        value = int(environ.get(name, default))
    except (TypeError, ValueError):
        return default
    return max(min_value, min(max_value, value))


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
    if ctx.error_counts['5xx'] >= _bounded_int_env(ctx.environ, 'HEALTH_5XX_DEGRADED_THRESHOLD', 5):
        degraded_reasons.append('5xx_threshold')
    if error_total >= _bounded_int_env(ctx.environ, 'HEALTH_ERROR_DEGRADED_THRESHOLD', 50):
        degraded_reasons.append('error_threshold')
    if ctx.use_db() and not db_ok:
        degraded_reasons.append('db_unavailable')
    status_code = 503 if degraded_reasons and ctx.environ.get('HEALTH_STRICT_STATUS') == '1' else 200
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
    }), status_code


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


ERROR_PAGE = '''<!DOCTYPE html>
<html lang="ja"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>へきネイター - {title}</title>
<style>
body{{margin:0;background:#0a0a1a;color:#eee;font-family:sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;text-align:center;}}
h1{{font-size:3rem;color:#e94560;margin-bottom:8px;}}
p{{color:#888;margin-bottom:24px;}}
a{{color:#7af0a0;text-decoration:none;border:1px solid #7af0a0;padding:8px 20px;border-radius:8px;}}
a:hover{{background:#7af0a0;color:#0a0a1a;}}
</style></head><body>
<div>
<div style="font-size:3rem;">{emoji}</div>
<h1>{code}</h1>
<p>{message}</p>
<a href="/">トップに戻る</a>
</div></body></html>'''


def error_page(title, emoji, code, message):
    return ERROR_PAGE.format(title=title, emoji=emoji, code=code, message=message)


def not_found():
    return error_page('ページが見つかりません', '🔮', '404', 'ページが見つかりません。'), 404


def server_error():
    return error_page('エラーが発生しました', '💀', '500', 'サーバーエラーが発生しました。しばらくしてからお試しください。'), 500


def service_unavailable():
    return error_page('サービス停止中', '🛠️', '503', 'ただいまメンテナンス中です。しばらくしてからお試しください。'), 503



def create_health_blueprint(ctx_factory):
    bp = Blueprint('system_health', __name__)

    @bp.route('/health')
    def health_route():
        return health(ctx_factory())

    return bp



def create_public_blueprint(ctx_factory):
    bp = Blueprint('system_public', __name__)

    @bp.route('/manifest.json')
    def manifest_route():
        return manifest(ctx_factory())

    @bp.route('/sw.js')
    def service_worker_route():
        return service_worker(ctx_factory())

    @bp.route('/offline')
    def offline_route():
        return offline(ctx_factory())

    return bp
