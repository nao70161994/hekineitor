"""Runtime configuration helpers.

Keep this module free of Flask imports so scripts, tests, and engine code can
share the same environment-based paths.
"""
import os
import tempfile


PROJECT_ROOT = os.path.dirname(__file__)
DATA_DIR = os.path.join(PROJECT_ROOT, 'data')


def app_env():
    return os.environ.get('APP_ENV') or os.environ.get('FLASK_ENV') or 'development'


def _abs_path(path):
    return path if os.path.isabs(path) else os.path.join(PROJECT_ROOT, path)


def get_fetish_log_path():
    """Return the JSON fallback path for fetish logs when DATABASE_URL is unused.

    Priority:
    1. FETISH_LOG_PATH explicit override.
    2. test/testing env -> temp directory.
    3. production env -> production-only local fallback.
    4. development/default -> local-only development file.
    """
    override = os.environ.get('FETISH_LOG_PATH')
    if override:
        return _abs_path(override)

    explicit_env = os.environ.get('APP_ENV') or os.environ.get('FLASK_ENV')
    env = app_env().lower()
    if env in ('test', 'testing') or (not explicit_env and os.environ.get('PYTEST_CURRENT_TEST')):
        return os.path.join(tempfile.gettempdir(), 'hekineitor-tests', 'fetish_log.json')
    if env in ('production', 'prod'):
        return os.path.join(DATA_DIR, 'fetish_log.production.json')
    return os.path.join(DATA_DIR, 'fetish_log.local.json')


LOG_PATH = get_fetish_log_path()
