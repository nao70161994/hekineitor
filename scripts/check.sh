#!/bin/sh
set -eu

python -m py_compile app.py engine.py analytics.py audit.py matrix_service.py storage.py work_utils.py tests/test_smoke.py
python scripts/static_check.py
python -m unittest discover -s tests -q
