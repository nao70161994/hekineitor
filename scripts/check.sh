#!/bin/sh
set -eu

python -m compileall -q app.py engine routes services analytics.py audit.py matrix_service.py storage.py work_utils.py tests
python scripts/static_check.py
python -m unittest discover -s tests -q
