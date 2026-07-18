"""Build or verify the deterministic normalized work catalog seed."""

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / 'data'
CATALOG_PATH = DATA_DIR / 'work_catalog.json'


def build_catalog():
    from services.work_catalog import build_catalog_from_inline

    fetishes = json.loads((DATA_DIR / 'fetishes.json').read_text(encoding='utf-8'))
    compound_data = json.loads((DATA_DIR / 'compound_works.json').read_text(encoding='utf-8'))
    compound_rows = []
    for key, works in sorted(compound_data.items()):
        id_a, id_b = key.split(',', 1)
        compound_rows.append({'key': key, 'id_a': int(id_a), 'id_b': int(id_b), 'works': works})
    return build_catalog_from_inline(fetishes, compound_rows=compound_rows)


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
