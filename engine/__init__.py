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


def _load_compound_works():
    global _COMPOUND_WORKS, _compound_works_loaded
    loaded = engine_compound_works.load_cache(
        loaded=_compound_works_loaded,
        load_fn=load_json_file,
    )
    if loaded is not None:
        _COMPOUND_WORKS = loaded
        _compound_works_loaded = True


def _save_compound_works():
    engine_compound_works.save_cache(_COMPOUND_WORKS_PATH, _COMPOUND_WORKS, atomic_write_json)


def get_compound_works(id_a: int, id_b: int) -> list:
    _load_compound_works()
    return engine_compound_works.get_works(_COMPOUND_WORKS, id_a, id_b)


def list_compound_works() -> list:
    _load_compound_works()
    return engine_compound_works.serialize_compound_works(_COMPOUND_WORKS)


def set_compound_works(id_a: int, id_b: int, works: list) -> str:
    _load_compound_works()
    key = engine_compound_works.set_works(_COMPOUND_WORKS, id_a, id_b, works)
    globals()['_save_compound_works']()
    return key


def delete_compound_works(id_a: int, id_b: int) -> bool:
    _load_compound_works()
    if not engine_compound_works.delete_works(_COMPOUND_WORKS, id_a, id_b):
        return False
    globals()['_save_compound_works']()
    return True
