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
BIBLIOGRAPHY_PATH = DATA_DIR / 'work_catalog_bibliography.json'
CORRECTIONS_BATCH2_PATH = DATA_DIR / 'work_catalog_corrections_batch2.json'
BIBLIOGRAPHY_BATCH2_PATH = DATA_DIR / 'work_catalog_bibliography_batch2.json'
LINK_BINDINGS_BATCH2_PATH = DATA_DIR / 'work_catalog_link_bindings_batch2.json'


def build_catalog():
    from engine.work_catalog import (
        apply_bibliography_manifest,
        apply_catalog_corrections,
        apply_review_decisions,
        apply_seed_overrides,
        build_catalog_from_inline,
        project_approved_inline_correction_manifests,
    )

    fetishes = json.loads((DATA_DIR / 'fetishes.json').read_text(encoding='utf-8'))
    compound_data = json.loads((DATA_DIR / 'compound_works.json').read_text(encoding='utf-8'))
    compound_rows = []
    for key, works in sorted(compound_data.items()):
        id_a, id_b = key.split(',', 1)
        compound_rows.append({'key': key, 'id_a': int(id_a), 'id_b': int(id_b), 'works': works})
    corrections = json.loads(CORRECTIONS_PATH.read_text(encoding='utf-8'))
    corrections_batch2 = json.loads(CORRECTIONS_BATCH2_PATH.read_text(encoding='utf-8'))
    link_bindings_batch2 = json.loads(LINK_BINDINGS_BATCH2_PATH.read_text(encoding='utf-8'))
    source_projection = project_approved_inline_correction_manifests(
        fetishes,
        compound_rows=compound_rows,
        correction_manifests=(corrections, corrections_batch2, link_bindings_batch2),
        direction='reverse',
    )
    catalog = build_catalog_from_inline(
        source_projection['fetishes'],
        compound_rows=source_projection['compound_rows'],
    )
    decisions = json.loads(DECISIONS_PATH.read_text(encoding='utf-8'))
    reviewed = apply_review_decisions(catalog, decisions)
    seed_overrides = json.loads(SEED_OVERRIDES_PATH.read_text(encoding='utf-8'))
    seeded = apply_seed_overrides(reviewed, seed_overrides)
    corrected = apply_catalog_corrections(seeded, corrections)
    bibliography = json.loads(BIBLIOGRAPHY_PATH.read_text(encoding='utf-8'))
    catalog = apply_bibliography_manifest(corrected, bibliography)[0]
    catalog = apply_catalog_corrections(catalog, corrections_batch2)
    bibliography_batch2 = json.loads(BIBLIOGRAPHY_BATCH2_PATH.read_text(encoding='utf-8'))
    catalog = apply_bibliography_manifest(catalog, bibliography_batch2)[0]
    return apply_catalog_corrections(catalog, link_bindings_batch2)


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
