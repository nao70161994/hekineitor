import hashlib
import os
import sys
import warnings


SECRET_KEY_REQUIRED_MESSAGE = '本番環境では SECRET_KEY 環境変数の設定が必須です'
SECRET_KEY_MISSING_WARNING = 'SECRET_KEY が未設定です。本番環境では環境変数に設定してください。'
SECRET_KEY_SHORT_WARNING = 'SECRET_KEY が短すぎます（16文字以上推奨）。'
DEV_SECRET_KEY = 'hekineitor_dev_secret_2024'


def is_production_env(environ):
    app_env = str(environ.get('APP_ENV') or environ.get('FLASK_ENV') or '').lower()
    return app_env in ('production', 'prod') or bool(environ.get('RENDER'))


def secret_key(environ, stderr=None, warn_fn=None):
    secret = environ.get('SECRET_KEY')
    stderr = stderr or sys.stderr
    if not secret:
        if environ.get('DATABASE_URL') or is_production_env(environ):
            raise RuntimeError(SECRET_KEY_REQUIRED_MESSAGE)
        print(f'WARNING: {SECRET_KEY_MISSING_WARNING}', file=stderr)
        (warn_fn or warnings.warn)(SECRET_KEY_MISSING_WARNING, stacklevel=1)
        return DEV_SECRET_KEY
    if len(secret) < 16:
        print(f'WARNING: {SECRET_KEY_SHORT_WARNING}', file=stderr)
    return secret


APP_VERSION_PATHS = (
    'app.py',
    'engine/__init__.py',
    'engine/facade.py',
    'templates/index.html',
    'templates/sw.js',
    'static/manifest.json',
    'static/icon-192.png',
    'static/icon-512.png',
)


def app_version(base_dir, paths=APP_VERSION_PATHS):
    digest = hashlib.md5()
    for relpath in paths:
        try:
            with open(os.path.join(base_dir, relpath), 'rb') as f:
                digest.update(f.read())
        except OSError:
            pass
    return digest.hexdigest()[:8]
