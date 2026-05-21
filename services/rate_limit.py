import ipaddress
import os
import time


def client_ip(request, app_config, environ=os.environ):
    remote_addr = request.remote_addr or 'unknown'
    trusted = app_config.get('TRUSTED_PROXY_IPS')
    if trusted is None:
        trusted = environ.get('TRUSTED_PROXY_IPS', '')
    if isinstance(trusted, str):
        trusted = [item.strip() for item in trusted.split(',') if item.strip()]
    if trusted:
        try:
            remote_ip = ipaddress.ip_address(remote_addr)
            proxy_trusted = any(
                remote_ip in ipaddress.ip_network(entry, strict=False)
                for entry in trusted
            )
        except ValueError:
            proxy_trusted = remote_addr in trusted
        if proxy_trusted:
            forwarded = request.headers.get('X-Forwarded-For', '')
            return forwarded.split(',')[0].strip() or remote_addr
    return remote_addr


def rate_limit(
    scope,
    limit,
    request,
    app_config,
    buckets,
    jsonify,
    should_enforce_runtime_guard,
    *,
    window_seconds=60,
    environ=os.environ,
    time_fn=time.time,
):
    if not should_enforce_runtime_guard('rate_limit'):
        return None
    overrides = app_config.get('RATE_LIMIT_OVERRIDES') or {}
    if scope in overrides:
        limit, window_seconds = overrides[scope]
    else:
        env_prefix = 'RATE_LIMIT_' + scope.upper()
        try:
            limit = int(environ.get(env_prefix + '_LIMIT', limit))
            window_seconds = int(environ.get(env_prefix + '_WINDOW', window_seconds))
        except ValueError:
            pass
    now = time_fn()
    key = (scope, client_ip(request, app_config, environ))
    bucket = [ts for ts in buckets.get(key, []) if now - ts < window_seconds]
    if len(bucket) >= limit:
        buckets[key] = bucket
        retry_after = max(1, int(window_seconds - (now - bucket[0])))
        return jsonify({
            'status': 'error',
            'message': f'リクエストが多すぎます。{retry_after}秒後に再試行してください。',
            'retry_after': retry_after,
        }), 429, {'Retry-After': str(retry_after)}
    bucket.append(now)
    buckets[key] = bucket
    return None
