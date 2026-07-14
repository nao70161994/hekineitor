MUTATION_METHODS = {'POST', 'PUT', 'PATCH', 'DELETE'}

SECURITY_HEADERS = {
    'X-Content-Type-Options': 'nosniff',
    'Referrer-Policy': 'strict-origin-when-cross-origin',
    'Permissions-Policy': 'camera=(), microphone=(), geolocation=()',
    'Content-Security-Policy': (
        "default-src 'self'; img-src 'self' data: https:; "
        "script-src 'self' 'unsafe-inline' https://pagead2.googlesyndication.com https://ep2.adtrafficquality.google; "
        "style-src 'self' 'unsafe-inline'; connect-src 'self' https://pagead2.googlesyndication.com https://ep1.adtrafficquality.google https://ep2.adtrafficquality.google; "
        'frame-src https://googleads.g.doubleclick.net https://tpc.googlesyndication.com https://ep2.adtrafficquality.google https://www.google.com; '
        "object-src 'none'; base-uri 'self'"
    ),
}


def is_admin_mutation(request):
    return request.path.startswith('/api/admin/') or (
        request.path.startswith('/api/fetish/') and request.method == 'DELETE'
    )


def record_status_counts(response, error_counts):
    if 400 <= response.status_code < 500:
        error_counts['4xx'] += 1
    elif response.status_code >= 500:
        error_counts['5xx'] += 1


def write_admin_audit(response, request, write_audit):
    if not (is_admin_mutation(request) and request.method in MUTATION_METHODS and 'import_matrix' not in request.path):
        return
    try:
        write_audit(
            'admin_api',
            'ok' if response.status_code < 400 else 'error',
            {
                'status_code': response.status_code,
            },
            request,
        )
    except Exception:
        pass


def apply_security_headers(response, request):
    for name, value in SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    if request.path.startswith('/admin') or request.path.startswith('/api/admin'):
        response.headers.setdefault('X-Frame-Options', 'DENY')


def after_request(response, request, error_counts, write_audit):
    record_status_counts(response, error_counts)
    write_admin_audit(response, request, write_audit)
    apply_security_headers(response, request)
    return response
