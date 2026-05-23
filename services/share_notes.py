from datetime import datetime, timezone

from storage import atomic_write_json, data_path, load_json_file

NOTES_FILE = 'share_improvement_notes.json'


def notes_path(environ=None):
    if environ and environ.get('SHARE_NOTES_PATH'):
        return environ['SHARE_NOTES_PATH']
    return data_path(NOTES_FILE)


def _clean_result_name(value):
    return str(value or '').strip()[:80]


def _clean_note(value):
    return str(value or '').strip()[:500]


def load_notes(path=None, environ=None):
    data = load_json_file(path or notes_path(environ), {})
    if not isinstance(data, dict):
        return {}
    result = {}
    for name, entry in data.items():
        clean_name = _clean_result_name(name)
        if not clean_name or not isinstance(entry, dict):
            continue
        note = _clean_note(entry.get('note'))
        if note:
            result[clean_name] = {
                'note': note,
                'updated_at': str(entry.get('updated_at') or ''),
            }
    return result


def save_note(result_name, note, *, path=None, environ=None, now_fn=None):
    result_name = _clean_result_name(result_name)
    note = _clean_note(note)
    if not result_name:
        raise ValueError('result_name is required')
    target = path or notes_path(environ)
    notes = load_notes(path=target)
    if note:
        now = now_fn() if now_fn else datetime.now(timezone.utc)
        notes[result_name] = {
            'note': note,
            'updated_at': now.astimezone(timezone.utc).isoformat(timespec='seconds'),
        }
    else:
        notes.pop(result_name, None)
    atomic_write_json(target, notes)
    return notes.get(result_name, {'note': '', 'updated_at': ''})
