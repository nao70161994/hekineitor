import os
import tempfile

_TEST_STORAGE_DIR = tempfile.mkdtemp(prefix='hekineitor-pytest-')

os.environ.setdefault('APP_ENV', 'testing')
os.environ.setdefault('FETISH_LOG_PATH', os.path.join(_TEST_STORAGE_DIR, 'fetish_log.json'))
