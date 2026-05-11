import time
import os

from storage import atomic_write_json, data_path, load_json_file


MAX_AUDIT_ROWS = 500


def _audit_file_name(ts=None):
    return time.strftime('admin_audit_log_%Y%m.json', time.localtime(ts or time.time()))


def write_audit(action, status='ok', detail=None, request=None):
    now = int(time.time())
    row = {
        'ts': now,
        'action': action,
        'status': status,
        'detail': detail or {},
    }
    if request is not None:
        row['method'] = request.method
        row['path'] = request.path
        row['remote_addr'] = request.headers.get('X-Forwarded-For', request.remote_addr)
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
