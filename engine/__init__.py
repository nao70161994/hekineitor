"""Public engine package facade.

The implementation source lives in ``engine.facade``. This module re-exports the
facade API while keeping historical patch points such as ``engine._use_db``
compatible for tests and callers.
"""

from . import facade as _facade

_MISSING = object()
_original_use_db = _facade._use_db
_original_get_conn = _facade._get_conn
_original_put_conn = _facade._put_conn
_original_get_fetish_log_path = _facade.get_fetish_log_path
_original_psycopg2 = getattr(_facade, 'psycopg2', _MISSING)


def _public_value(name, original=_MISSING):
    value = globals().get(name, _MISSING)
    if value is not _MISSING:
        return value
    if original is _MISSING:
        raise AttributeError(name)
    return original


def _use_db():
    return _original_use_db()


def _get_conn():
    return _original_get_conn()


def _put_conn(conn):
    return _original_put_conn(conn)


def get_fetish_log_path():
    return _original_get_fetish_log_path()


def _public_use_db():
    return _public_value('_use_db')()


def _public_get_conn():
    return _public_value('_get_conn')()


def _public_put_conn(conn):
    return _public_value('_put_conn')(conn)


def _public_get_fetish_log_path():
    return _public_value('get_fetish_log_path', _original_get_fetish_log_path)()


class _PublicModuleProxy:
    def __init__(self, name, original=_MISSING):
        self._name = name
        self._original = original

    def __getattr__(self, attr):
        return getattr(_public_value(self._name, self._original), attr)


_facade._use_db = _public_use_db
_facade._get_conn = _public_get_conn
_facade._put_conn = _public_put_conn
_facade.get_fetish_log_path = _public_get_fetish_log_path
_facade.psycopg2 = _PublicModuleProxy('psycopg2', _original_psycopg2)

for _name, _value in vars(_facade).items():
    if _name.startswith('__') or _name in {'_use_db', '_get_conn', '_put_conn', 'get_fetish_log_path', 'psycopg2'}:
        continue
    globals()[_name] = _value

if _original_psycopg2 is not _MISSING:
    psycopg2 = _original_psycopg2

facade = _facade
