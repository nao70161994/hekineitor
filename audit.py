import time
import os

from storage import atomic_write_json, data_path, load_json_file


MAX_AUDIT_ROWS = 500
SENSITIVE_DETAIL_KEYS = {'password', 'secret', 'token', 'cookie', 'authorization', 'api_key', 'apikey'}


def _audit_file_name(ts=None):
    return time.strftime('admin_audit_log_%Y%m.json', time.localtime(ts or time.time()))


def _sanitize_detail(value):
    if isinstance(value, dict):
        sanitized = {}
        for key, item in value.items():
            key_text = str(key).lower()
            if key_text in SENSITIVE_DETAIL_KEYS or any(token in key_text for token in SENSITIVE_DETAIL_KEYS):
                sanitized[key] = '[redacted]'
            else:
                sanitized[key] = _sanitize_detail(item)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_detail(item) for item in value]
    return value


def _redact_remote_addr(remote_addr):
    text = str(remote_addr or '')
    if not text:
        return ''
    if ':' in text:
        parts = text.split(':')
        return ':'.join(parts[:4]) + '::/64'
    parts = text.split('.')
    if len(parts) == 4 and all(part.isdigit() for part in parts):
        return '.'.join(parts[:3] + ['0']) + '/24'
    return '[redacted]'


def write_audit(action, status='ok', detail=None, request=None):
    now = int(time.time())
    row = {
        'ts': now,
        'action': action,
        'status': status,
        'detail': _sanitize_detail(detail or {}),
    }
    if request is not None:
        row['method'] = request.method
        row['path'] = request.path
        row['remote_addr'] = _redact_remote_addr(request.remote_addr)
    name = _audit_file_name(now)
    rows = load_json_file(name, default=[])
    if not isinstance(rows, list):
        rows = []
    rows.append(row)
    rows = rows[-MAX_AUDIT_ROWS:]
    atomic_write_json(data_path(name), rows, ensure_ascii=False, indent=2)
    return row


def recent_audit(limit=50):
    names = []
    try:
        names = sorted(
            name for name in os.listdir(data_path(''))
            if name.startswith('admin_audit_log_') and name.endswith('.json')
        )
    except OSError:
        pass
    rows = []
    for name in names[-3:]:
        data = load_json_file(name, default=[])
        if isinstance(data, list):
            rows.extend(data)
    rows.sort(key=lambda row: row.get('ts', 0))
    return list(reversed(rows[-limit:]))
