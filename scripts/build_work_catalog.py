"""Build or verify the deterministic normalized work catalog seed."""

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / 'data'
CATALOG_PATH = DATA_DIR / 'work_catalog.json'
DECISIONS_PATH = DATA_DIR / 'work_catalog_review_decisions.json'
SEED_OVERRIDES_PATH = DATA_DIR / 'work_catalog_seed_overrides.json'
CORRECTIONS_PATH = DATA_DIR / 'work_catalog_corrections.json'


def build_catalog():
    from engine.work_catalog import apply_catalog_corrections, apply_review_decisions, build_catalog_from_inline

    fetishes = json.loads((DATA_DIR / 'fetishes.json').read_text(encoding='utf-8'))
    compound_data = json.loads((DATA_DIR / 'compound_works.json').read_text(encoding='utf-8'))
    compound_rows = []
    for key, works in sorted(compound_data.items()):
        id_a, id_b = key.split(',', 1)
        compound_rows.append({'key': key, 'id_a': int(id_a), 'id_b': int(id_b), 'works': works})
    seed_overrides = json.loads(SEED_OVERRIDES_PATH.read_text(encoding='utf-8'))
    catalog = build_catalog_from_inline(fetishes, compound_rows=compound_rows, seed_overrides=seed_overrides)
    decisions = json.loads(DECISIONS_PATH.read_text(encoding='utf-8'))
    reviewed = apply_review_decisions(catalog, decisions)
    corrections = json.loads(CORRECTIONS_PATH.read_text(encoding='utf-8'))
    return apply_catalog_corrections(reviewed, corrections)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--write', action='store_true', help='write data/work_catalog.json')
    args = parser.parse_args(argv)
    catalog = build_catalog()
    rendered = json.dumps(catalog, ensure_ascii=False, indent=2) + '\n'
    if args.write:
        CATALOG_PATH.write_text(rendered, encoding='utf-8')
        print(f'wrote {CATALOG_PATH.relative_to(ROOT)}')
        return 0
    if not CATALOG_PATH.exists() or CATALOG_PATH.read_text(encoding='utf-8') != rendered:
        print('data/work_catalog.json is stale; run python scripts/build_work_catalog.py --write')
        return 1
    print('work catalog seed: OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
