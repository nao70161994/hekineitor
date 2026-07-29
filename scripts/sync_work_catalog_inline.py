"""Verify or write the approved legacy-inline projection for catalog corrections."""

import argparse
import json
from pathlib import Path

from engine.work_catalog import project_approved_inline_corrections

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / 'data'
FETISHES_PATH = DATA_DIR / 'fetishes.json'
COMPOUNDS_PATH = DATA_DIR / 'compound_works.json'
CORRECTIONS_PATH = DATA_DIR / 'work_catalog_corrections.json'


def projected_inline():
    fetishes = json.loads(FETISHES_PATH.read_text(encoding='utf-8'))
    compounds = json.loads(COMPOUNDS_PATH.read_text(encoding='utf-8'))
    corrections = json.loads(CORRECTIONS_PATH.read_text(encoding='utf-8'))
    return project_approved_inline_corrections(
        fetishes,
        compound_rows=compounds,
        corrections=corrections,
    )


def _render(value):
    return json.dumps(value, ensure_ascii=False, indent=2) + '\n'


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args(argv)
    projection = projected_inline()
    expected = {
        FETISHES_PATH: _render(projection['fetishes']),
        COMPOUNDS_PATH: _render(projection['compound_rows']),
    }
    stale = [path for path, rendered in expected.items() if path.read_text(encoding='utf-8') != rendered]
    if args.write:
        for path in stale:
            path.write_text(expected[path], encoding='utf-8')
        print(
            'work catalog inline projection: wrote '
            f'{projection["applied_link_count"]} links / '
            f'{projection["fetish_owner_count"]} fetish owners / '
            f'{projection["compound_owner_count"]} compound owners'
        )
        return 0
    if stale:
        print('work catalog inline projection is stale; run python scripts/sync_work_catalog_inline.py --write')
        return 1
    print('work catalog inline projection: OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
