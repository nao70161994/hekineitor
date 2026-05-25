#!/bin/sh
set -eu

python -m compileall -q app.py engine routes services analytics.py audit.py matrix_service.py storage.py work_utils.py tests
python scripts/static_check.py
if command -v node >/dev/null 2>&1; then
  for js in static/*.js; do
    node --check "$js"
  done
fi
python -m unittest discover -s tests -q
