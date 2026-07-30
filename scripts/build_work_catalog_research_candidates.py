"""Build or verify the deterministic active work-catalog research candidates."""

import argparse
import json
from pathlib import Path

from engine.work_catalog import catalog_digest

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / 'data'
CATALOG_PATH = DATA_DIR / 'work_catalog.json'
BIBLIOGRAPHY_PATH = DATA_DIR / 'work_catalog_bibliography.json'
BIBLIOGRAPHY_BATCH2_PATH = DATA_DIR / 'work_catalog_bibliography_batch2.json'
OUTPUT_PATH = DATA_DIR / 'work_catalog_research_candidates.json'

GENERATED_AT = '2026-07-30'
SELECTION_RULE = {
    'catalog': 'data/work_catalog.json',
    'criteria': [
        'works_master.status is active',
        'work_id is referenced by fetish_work_links or compound_work_links',
        'work_id has no row in work_editions',
    ],
    'grouping': 'one entry per work_id with every current owner reference',
    'sort': [
        'entries by work_id',
        'owner_references by table, owner ids, then position',
    ],
}


def _owner_reference(table, link):
    if table == 'fetish_work_links':
        return {
            'table': table,
            'fetish_id': int(link['fetish_id']),
            'position': int(link['position']),
        }
    return {
        'table': table,
        'id_a': int(link['id_a']),
        'id_b': int(link['id_b']),
        'position': int(link['position']),
    }


def _owner_reference_key(reference):
    if reference['table'] == 'fetish_work_links':
        return (0, reference['fetish_id'], reference['position'])
    return (1, reference['id_a'], reference['id_b'], reference['position'])


def build_candidates(catalog, bibliography):
    masters = {row['work_id']: row for row in catalog['works_master']}
    work_ids_with_editions = {row['work_id'] for row in catalog['work_editions']}
    references_by_work_id = {}
    for table in ('fetish_work_links', 'compound_work_links'):
        for link in catalog[table]:
            references_by_work_id.setdefault(link['work_id'], []).append(_owner_reference(table, link))

    bibliography_manifests = [bibliography] if isinstance(bibliography, dict) else list(bibliography)
    media_confirmed_ids = {
        row['target_work']['work_id']
        for manifest in bibliography_manifests
        for row in manifest['entries']
        if row.get('evidence_url') and not row.get('edition')
    }
    selected_ids = sorted(
        work_id
        for work_id in references_by_work_id
        if masters[work_id]['status'] == 'active' and work_id not in work_ids_with_editions
    )
    entries = []
    for work_id in selected_ids:
        master = masters[work_id]
        entries.append(
            {
                'work_id': work_id,
                'canonical_title': master['canonical_title'],
                'media_type': master.get('media_type', ''),
                'owner_references': sorted(
                    references_by_work_id[work_id],
                    key=_owner_reference_key,
                ),
                'bibliography_state': ('media_confirmed' if work_id in media_confirmed_ids else 'identity_unverified'),
            }
        )
    return {
        'schema_version': 1,
        'generated_at': GENERATED_AT,
        'catalog_digest': catalog_digest(catalog),
        'selection_rule': SELECTION_RULE,
        'entries': entries,
    }


def render_candidates():
    catalog = json.loads(CATALOG_PATH.read_text(encoding='utf-8'))
    bibliography = json.loads(BIBLIOGRAPHY_PATH.read_text(encoding='utf-8'))
    bibliography_batch2 = json.loads(BIBLIOGRAPHY_BATCH2_PATH.read_text(encoding='utf-8'))
    candidates = build_candidates(catalog, (bibliography, bibliography_batch2))
    return json.dumps(candidates, ensure_ascii=False, indent=2) + '\n'


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--write', action='store_true', help='write the research candidate artifact')
    args = parser.parse_args(argv)
    rendered = render_candidates()
    if args.write:
        OUTPUT_PATH.write_text(rendered, encoding='utf-8')
        print(f'wrote {OUTPUT_PATH.relative_to(ROOT)}')
        return 0
    if not OUTPUT_PATH.exists() or OUTPUT_PATH.read_text(encoding='utf-8') != rendered:
        print(
            'data/work_catalog_research_candidates.json is stale; '
            'run PYTHONPATH=. python scripts/build_work_catalog_research_candidates.py --write'
        )
        return 1
    print('work catalog research candidates: OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
