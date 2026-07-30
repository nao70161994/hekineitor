import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QUEUE_PATH = ROOT / 'data/work_catalog_research_queue.json'
CATALOG_PATH = ROOT / 'data/work_catalog.json'
COMPOUND_PATH = ROOT / 'data/compound_works.json'


def _load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def _entry_key(row):
    return row['id_a'], row['id_b'], row['position']


def test_research_queue_has_43_unique_entries():
    queue = _load(QUEUE_PATH)
    entries = queue['entries']

    assert queue['schema_version'] == 1
    assert queue['generated_at'] == '2026-07-30'
    assert len(entries) == 43
    assert len({row['work_id'] for row in entries}) == 43
    assert len({_entry_key(row) for row in entries}) == 43


def test_research_queue_matches_current_compound_links_and_titles():
    queue = _load(QUEUE_PATH)
    catalog = _load(CATALOG_PATH)
    links = {_entry_key(row): row for row in catalog['compound_work_links']}
    masters = {row['work_id']: row for row in catalog['works_master']}

    for entry in queue['entries']:
        link = links[_entry_key(entry)]
        assert link['work_id'] == entry['work_id']
        assert masters[entry['work_id']]['canonical_title'] == entry['canonical_title']


def test_research_queue_works_have_no_editions():
    queue = _load(QUEUE_PATH)
    catalog = _load(CATALOG_PATH)
    work_ids_with_editions = {row['work_id'] for row in catalog['work_editions']}

    assert not ({row['work_id'] for row in queue['entries']} & work_ids_with_editions)


def test_research_queue_exactly_matches_reproducible_raw_selection():
    queue = _load(QUEUE_PATH)
    catalog = _load(CATALOG_PATH)
    compound_source = _load(COMPOUND_PATH)
    links = {_entry_key(row): row for row in catalog['compound_work_links']}
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

    queued = {(row['id_a'], row['id_b'], row['position'], row['work_id']) for row in queue['entries']}
    assert queued == selected


def test_research_queue_status_and_issue_enums():
    queue = _load(QUEUE_PATH)
    entries = queue['entries']

    assert {row['status'] for row in entries} == {'pending'}
    assert {row['issue'] for row in entries} == {
        'adult_metadata_unverified',
        'unverified_bibliography',
    }
    assert Counter(row['issue'] for row in entries) == {
        'unverified_bibliography': 42,
        'adult_metadata_unverified': 1,
    }
    adult = [row for row in entries if row['issue'] == 'adult_metadata_unverified']
    assert adult[0]['canonical_title'] == '闇の契約（成人向け漫画）'
