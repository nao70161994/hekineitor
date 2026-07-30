import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QUEUE_PATH = ROOT / 'data/work_catalog_research_queue.json'
CATALOG_PATH = ROOT / 'data/work_catalog.json'
COMPOUND_PATH = ROOT / 'data/compound_works.json'
CORRECTIONS_PATH = ROOT / 'data/work_catalog_corrections.json'


def _load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def _entry_key(row):
    if row.get('source_table') == 'fetish_work_links' or 'fetish_id' in row:
        return 'fetish', row['fetish_id'], row['position']
    return 'compound', row['id_a'], row['id_b'], row['position']


def test_research_queue_has_46_unique_entries():
    queue = _load(QUEUE_PATH)
    entries = queue['entries']

    assert queue['schema_version'] == 1
    assert queue['generated_at'] == '2026-07-30'
    assert len(entries) == 46
    assert len({row['work_id'] for row in entries}) == 46
    assert len({_entry_key(row) for row in entries}) == 46


def test_research_queue_matches_current_links_and_titles():
    queue = _load(QUEUE_PATH)
    catalog = _load(CATALOG_PATH)
    links = {
        _entry_key(row): row
        for table in ('fetish_work_links', 'compound_work_links')
        for row in catalog[table]
    }
    masters = {row['work_id']: row for row in catalog['works_master']}

    for entry in queue['entries']:
        master = masters[entry['work_id']]
        assert master['canonical_title'] == entry['canonical_title']
        if entry['status'] == 'pending':
            assert links[_entry_key(entry)]['work_id'] == entry['work_id']
            assert master['status'] == 'active'
        else:
            assert entry['status'] == 'quarantined'
            assert not any(link['work_id'] == entry['work_id'] for link in links.values())
            assert master['status'] == 'archived'


def test_pending_research_queue_works_have_no_editions():
    queue = _load(QUEUE_PATH)
    catalog = _load(CATALOG_PATH)
    work_ids_with_editions = {row['work_id'] for row in catalog['work_editions']}
    pending_ids = {row['work_id'] for row in queue['entries'] if row['status'] == 'pending'}

    assert not (pending_ids & work_ids_with_editions)


def test_pending_research_queue_exactly_matches_reproducible_raw_selection():
    queue = _load(QUEUE_PATH)
    catalog = _load(CATALOG_PATH)
    compound_source = _load(COMPOUND_PATH)
    links = {(row['id_a'], row['id_b'], row['position']): row for row in catalog['compound_work_links']}
    work_ids_with_editions = {row['work_id'] for row in catalog['work_editions']}
    selected = set()

    for pair, works in compound_source.items():
        id_a, id_b = (int(value) for value in pair.split(',', 1))
        for position, work in enumerate(works):
            if not isinstance(work, dict) or work.get('url'):
                continue
            key = (id_a, id_b, position)
            work_id = links[key]['work_id']
            if work_id not in work_ids_with_editions:
                selected.add((*key, work_id))

    queued = {
        (row['id_a'], row['id_b'], row['position'], row['work_id'])
        for row in queue['entries']
        if row['status'] == 'pending'
    }
    assert queued == selected


def test_all_quarantines_remain_machine_readable_with_source_and_reason():
    queue = _load(QUEUE_PATH)
    corrections = _load(CORRECTIONS_PATH)
    quarantined = [row for row in queue['entries'] if row['status'] == 'quarantined']
    manifest_ids = {
        row['target_work']['work_id']
        for row in corrections['corrections']
        if row['type'] == 'quarantine_recommendation'
    }

    assert {row['work_id'] for row in quarantined} == manifest_ids
    assert all(row.get('source_table') in {'fetish_work_links', 'compound_work_links'} for row in quarantined)
    assert all(row.get('reason', '').strip() for row in quarantined)


def test_research_queue_status_and_issue_enums():
    queue = _load(QUEUE_PATH)
    entries = queue['entries']

    assert Counter(row['status'] for row in entries) == {'pending': 39, 'quarantined': 7}
    assert Counter(row['issue'] for row in entries) == {
        'unverified_bibliography': 43,
        'adult_metadata_unverified': 1,
        'ambiguous_identity': 1,
        'edition_identity_unverified': 1,
    }
    adult = [row for row in entries if row['issue'] == 'adult_metadata_unverified']
    assert adult[0]['canonical_title'] == '闇の契約（成人向け漫画）'
