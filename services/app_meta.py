import hashlib
import os


def app_version(base_dir, paths=('app.py', 'engine.py', 'templates/index.html')):
    digest = hashlib.md5()
    for relpath in paths:
        try:
            with open(os.path.join(base_dir, relpath), 'rb') as f:
                digest.update(f.read())
        except OSError:
            pass
    return digest.hexdigest()[:8]
