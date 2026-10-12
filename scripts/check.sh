#!/bin/sh
set -eu

git ls-files -z -- '*.py' | xargs -0 python -m py_compile
python scripts/static_check.py
python scripts/check_docs.py
PYTHONPATH=. python scripts/build_work_catalog.py
PYTHONPATH=. python scripts/build_work_catalog_research_candidates.py
PYTHONPATH=. python scripts/build_recommended_works_list.py
PYTHONPATH=. python scripts/evaluate_gameplay.py --baseline tests/fixtures/gameplay_eval_baseline.json --check --output /tmp/gameplay_eval_report.json
git ls-files -z -- '*.py' | xargs -0 python -m ruff check --force-exclude
git ls-files -z -- '*.py' | xargs -0 python -m ruff format --check --force-exclude
python -m mypy matrix_service.py work_utils.py services/ids.py services/csv_safety.py services/name_matching.py
if command -v node >/dev/null 2>&1; then
  for js in static/*.js; do
    node --check "$js"
  done
  npm run test:js
fi
python run_coverage.py
