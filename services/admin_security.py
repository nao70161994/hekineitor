import functools
import hmac
import secrets
import time


MUTATION_METHODS = {'POST', 'PUT', 'PATCH', 'DELETE'}


def confirmation_text(request):
    data = request.get_json(silent=True) or {}
    return (data.get('confirm_text') or request.headers.get('X-Confirm-Text') or '').strip()


def require_confirm(request, jsonify, expected):
    if confirmation_text(request) != expected:
        return jsonify({
            'status': 'error',
            'message': f'確認のため「{expected}」と入力してください',
            'required_confirm_text': expected,
        }), 400
    return None


def csrf_token(session, environ, now_fn=time.time, token_fn=secrets.token_urlsafe):
    token = session.get('admin_csrf_token')
    issued_at = session.get('admin_csrf_issued_at', 0)
    ttl = int(environ.get('ADMIN_CSRF_TTL_SECONDS', '7200'))
    if not token or now_fn() - issued_at > ttl:
        token = token_fn(32)
        session['admin_csrf_token'] = token
        session['admin_csrf_issued_at'] = now_fn()
    return token


def check_admin_csrf(request, session, environ, should_enforce_runtime_guard, now_fn=time.time):
    if not should_enforce_runtime_guard('csrf'):
        return True
    expected = session.get('admin_csrf_token')
    issued_at = session.get('admin_csrf_issued_at', 0)
    ttl = int(environ.get('ADMIN_CSRF_TTL_SECONDS', '7200'))
    if not issued_at or now_fn() - issued_at > ttl:
        return False
    supplied = request.headers.get('X-CSRF-Token', '')
    return bool(expected and supplied and hmac.compare_digest(expected, supplied))


def _bearer_token(request):
    header = request.headers.get('Authorization', '')
    prefix = 'Bearer '
    if header.startswith(prefix):
        return header[len(prefix):].strip()
    return ''


def read_token_guard_response(request, environ, response_cls, rate_limit):
    limited = rate_limit('admin_read_api', 240)
    if limited:
        return limited
    token = environ.get('ADMIN_READ_TOKEN', '')
    if not token:
        return response_cls('ADMIN_READ_TOKEN が未設定です', 503)
    supplied = _bearer_token(request)
    if not supplied or not hmac.compare_digest(supplied, token):
        return response_cls('読み取り認証が必要です', 401, {'WWW-Authenticate': 'Bearer realm="AdminRead"'})
    return None


def admin_guard_response(request, environ, session, response_cls, jsonify, rate_limit, should_enforce_runtime_guard):
    limited = rate_limit('admin_api', 120)
    if limited:
        return limited
    admin_user = environ.get('ADMIN_USER', 'admin')
    admin_pass = environ.get('ADMIN_PASS', '')
    if not admin_pass:
        return response_cls('ADMIN_PASS が未設定です', 503)
    auth = request.authorization
    username = getattr(auth, 'username', '') if auth else ''
    password = getattr(auth, 'password', '') if auth else ''
    if not username or not password or not hmac.compare_digest(username, admin_user) or not hmac.compare_digest(password, admin_pass):
        return response_cls('認証が必要です', 401, {'WWW-Authenticate': 'Basic realm="Admin"'})
    if request.method in MUTATION_METHODS and not check_admin_csrf(
        request, session, environ, should_enforce_runtime_guard,
    ):
        return jsonify({'status': 'error', 'message': 'CSRF token が不正です'}), 403
    return None


def require_admin_or_read_decorator(admin_guard_fn, read_guard_fn):
    def require_admin_or_read(func):
        @functools.wraps(func)
        def decorated(*args, **kwargs):
            admin_guard = admin_guard_fn()
            if not admin_guard:
                return func(*args, **kwargs)
            read_guard = read_guard_fn()
            if not read_guard:
                return func(*args, **kwargs)
            return admin_guard
        return decorated
    return require_admin_or_read


def require_admin_decorator(guard_fn):
    def require_admin(func):
        @functools.wraps(func)
        def decorated(*args, **kwargs):
            guard = guard_fn()
            if guard:
                return guard
            return func(*args, **kwargs)
        return decorated
    return require_admin
