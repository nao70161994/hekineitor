import os
import json
import tempfile

try:
    import psycopg2
    from psycopg2 import pool as psycopg2_pool
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False


DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
DATABASE_URL = os.environ.get('DATABASE_URL', '')

_conn_pool = None


def use_db():
    return bool(DATABASE_URL) and HAS_PSYCOPG2


def get_pool():
    global _conn_pool
    if _conn_pool is None:
        url = DATABASE_URL
        if url.startswith('postgres://'):
            url = url.replace('postgres://', 'postgresql://', 1)
        _conn_pool = psycopg2_pool.SimpleConnectionPool(2, 20, url, sslmode='require')
    return _conn_pool


def get_conn():
    return get_pool().getconn()


def put_conn(conn):
    get_pool().putconn(conn)


def data_path(name):
    return os.path.join(DATA_DIR, name)


def load_json_file(name, default=None):
    path = data_path(name)
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        if default is None:
            raise
        return default


def atomic_write_json(path, data, **kwargs):
    target_dir = os.path.dirname(os.path.abspath(path)) or DATA_DIR
    os.makedirs(target_dir, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=target_dir, suffix='.tmp')
    try:
        os.chmod(tmp, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, **kwargs)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        dir_fd = os.open(target_dir, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
