#!/bin/sh
set -eu

git ls-files -z -- '*.py' | xargs -0 python -m py_compile
python scripts/static_check.py
python scripts/check_docs.py
PYTHONPATH=. python scripts/build_work_catalog.py
python -m ruff check app.py engine routes services scripts tests analytics.py audit.py matrix_service.py storage.py work_utils.py check_works_links.py config.py fetch_kindle_asins.py restore_matrix.py run_coverage.py
python -m ruff format --diff engine/db_work_catalog.py || true
python -m ruff format --check app.py engine routes services scripts tests analytics.py audit.py matrix_service.py storage.py work_utils.py check_works_links.py config.py fetch_kindle_asins.py restore_matrix.py run_coverage.py
python -m mypy matrix_service.py work_utils.py services/ids.py services/csv_safety.py services/name_matching.py
if command -v node >/dev/null 2>&1; then
  for js in static/*.js; do
    node --check "$js"
  done
  npm run test:js
fi
python run_coverage.py
