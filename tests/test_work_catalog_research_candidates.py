import json
from pathlib import Path

from engine.work_catalog import catalog_digest
from scripts import build_work_catalog_research_candidates as builder

ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / 'data/work_catalog.json'
BIBLIOGRAPHY_PATH = ROOT / 'data/work_catalog_bibliography.json'
BIBLIOGRAPHY_BATCH2_PATH = ROOT / 'data/work_catalog_bibliography_batch2.json'
CANDIDATES_PATH = ROOT / 'data/work_catalog_research_candidates.json'


def _load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def _reference_key(reference):
    if reference['table'] == 'fetish_work_links':
        return 0, reference['fetish_id'], reference['position']
    return 1, reference['id_a'], reference['id_b'], reference['position']


def test_research_candidates_artifact_is_current_and_has_one_unique_sorted_entry():
    artifact = _load(CANDIDATES_PATH)
    catalog = _load(CATALOG_PATH)
    entries = artifact['entries']
    work_ids = [row['work_id'] for row in entries]

    assert CANDIDATES_PATH.read_text(encoding='utf-8') == builder.render_candidates()
    assert artifact['schema_version'] == 1
    assert artifact['generated_at'] == '2026-07-30'
    assert artifact['catalog_digest'] == catalog_digest(catalog)
    assert artifact['selection_rule'] == builder.SELECTION_RULE
    assert len(entries) == 1
    assert work_ids == sorted(work_ids)
    assert len(work_ids) == len(set(work_ids))


def test_research_candidates_exactly_match_active_linked_editionless_selection():
    artifact = _load(CANDIDATES_PATH)
    catalog = _load(CATALOG_PATH)
    masters = {row['work_id']: row for row in catalog['works_master']}
    work_ids_with_editions = {row['work_id'] for row in catalog['work_editions']}
    linked_ids = {row['work_id'] for table in ('fetish_work_links', 'compound_work_links') for row in catalog[table]}
    expected = sorted(
        work_id
        for work_id in linked_ids
        if masters[work_id]['status'] == 'active' and work_id not in work_ids_with_editions
    )

    assert [row['work_id'] for row in artifact['entries']] == expected


def test_research_candidate_owner_references_are_sorted_unique_and_current():
    artifact = _load(CANDIDATES_PATH)
    catalog = _load(CATALOG_PATH)
    expected_by_work_id = {}
    for table in ('fetish_work_links', 'compound_work_links'):
        for link in catalog[table]:
            expected_by_work_id.setdefault(link['work_id'], []).append(builder._owner_reference(table, link))

    for entry in artifact['entries']:
        references = entry['owner_references']
        keys = [_reference_key(reference) for reference in references]
        assert references
        assert keys == sorted(keys)
        assert len(keys) == len(set(keys))
        assert references == sorted(expected_by_work_id[entry['work_id']], key=_reference_key)


def test_research_candidate_bibliography_state_uses_evidence_only_targets():
    artifact = _load(CANDIDATES_PATH)
    bibliographies = (
        _load(BIBLIOGRAPHY_PATH),
        _load(BIBLIOGRAPHY_BATCH2_PATH),
    )
    evidence_only_ids = {
        row['target_work']['work_id']
        for bibliography in bibliographies
        for row in bibliography['entries']
        if row.get('evidence_url') and not row.get('edition')
    }

    for entry in artifact['entries']:
        expected = 'media_confirmed' if entry['work_id'] in evidence_only_ids else 'identity_unverified'
        assert entry['bibliography_state'] == expected
        if expected == 'media_confirmed':
            assert entry['media_type']
