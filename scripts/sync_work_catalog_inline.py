"""Verify or write the approved legacy-inline projection for catalog corrections."""

import argparse
import json
from pathlib import Path

from engine.work_catalog import project_approved_inline_correction_manifests

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / 'data'
FETISHES_PATH = DATA_DIR / 'fetishes.json'
COMPOUNDS_PATH = DATA_DIR / 'compound_works.json'
CORRECTIONS_PATH = DATA_DIR / 'work_catalog_corrections.json'
CORRECTIONS_BATCH2_PATH = DATA_DIR / 'work_catalog_corrections_batch2.json'
LINK_BINDINGS_BATCH2_PATH = DATA_DIR / 'work_catalog_link_bindings_batch2.json'


def projected_inline():
    fetishes = json.loads(FETISHES_PATH.read_text(encoding='utf-8'))
    compounds = json.loads(COMPOUNDS_PATH.read_text(encoding='utf-8'))
    corrections = json.loads(CORRECTIONS_PATH.read_text(encoding='utf-8'))
    corrections_batch2 = json.loads(CORRECTIONS_BATCH2_PATH.read_text(encoding='utf-8'))
    link_bindings_batch2 = json.loads(LINK_BINDINGS_BATCH2_PATH.read_text(encoding='utf-8'))
    manifests = (corrections, corrections_batch2, link_bindings_batch2)

    try:
        final = project_approved_inline_correction_manifests(
            fetishes,
            compound_rows=compounds,
            correction_manifests=manifests,
        )
    except ValueError:
        source = project_approved_inline_correction_manifests(
            fetishes,
            compound_rows=compounds,
            correction_manifests=manifests,
            direction='reverse',
        )
        final = project_approved_inline_correction_manifests(
            source['fetishes'],
            compound_rows=source['compound_rows'],
            correction_manifests=manifests,
        )

    before_fetishes = {row['id']: row.get('works') or [] for row in fetishes}
    after_fetishes = {row['id']: row.get('works') or [] for row in final['fetishes']}
    final['fetish_owner_count'] = sum(
        before_fetishes.get(owner_id) != works for owner_id, works in after_fetishes.items()
    )
    before_compounds = (
        compounds if isinstance(compounds, dict) else {row['key']: row.get('works') or [] for row in compounds}
    )
    after_compounds = (
        final['compound_rows']
        if isinstance(final['compound_rows'], dict)
        else {row['key']: row.get('works') or [] for row in final['compound_rows']}
    )
    final['compound_owner_count'] = sum(
        before_compounds.get(owner_id) != works for owner_id, works in after_compounds.items()
    )
    return final


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
