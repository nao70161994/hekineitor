import copy
import json
from collections import defaultdict
from pathlib import Path

from engine import work_catalog
from scripts import build_work_catalog_research_candidates
from work_utils import safe_work_url

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'
TABLES = (
    'works_master',
    'work_editions',
    'work_edition_identifiers',
    'work_aliases',
    'fetish_work_links',
    'compound_work_links',
    'review_queue',
)
GENERIC_IDS = {
    'wrk_155d0d4b09c2e1d259a3',
    'wrk_1b56de6af1d38d43e224',
    'wrk_1cec191856c214c192f1',
    'wrk_21bb20f169273683f2b6',
    'wrk_25b03aa9a6b5e9888cac',
    'wrk_28c451be4b4678bce9ff',
    'wrk_333b65d2d9ee0c7205f9',
    'wrk_3ff5a233cd3e832ef463',
    'wrk_44a1ff54bed717db5a45',
    'wrk_68a72af17d9e02b69aa5',
    'wrk_68f7f8d8e539f4618c84',
    'wrk_72f9affc12a5e50611a9',
    'wrk_84af05a91c95bb24f510',
    'wrk_959daf1b9e7a84a22085',
    'wrk_9877e226c9aa2fa4f23c',
    'wrk_9da94312fcf2f57cc7d9',
    'wrk_9f13b09b0e6167ec1d8e',
    'wrk_d6874d787632ca5225d7',
    'wrk_f33e10a3bc2a5acea1c5',
}
PALMA_ID = 'wrk_65bff4a8c47786418f40'
BIBLIOGRAPHY_ENTRY_IDS = {
    'edition-ef-steam-bundle-12092',
    'edition-dance-with-devils-switch',
    'edition-star-twinkle-bluray-vol1',
    'edition-osana-president-initial',
    'edition-rosario-vampire-9784088736655',
    'edition-vampire-bund-9784864726986',
    'edition-hatsukoi-monster-9784063588323',
    'evidence-hana-wa-saku-ka',
    'edition-ano-natsu-bluray-box',
    'edition-killing-stalking-9781638585572',
    'edition-free-season1-vol1',
    'edition-eminence-shadow-9784047353022',
    'edition-demon-academy-9784048936811',
}


def _load(name):
    return json.loads((DATA / name).read_text(encoding='utf-8'))


def _build_phase1_catalog():
    source = copy.deepcopy(_load('work_catalog.json'))
    bibliography = _load('work_catalog_bibliography_batch2.json')
    masters = {row['work_id']: row for row in source['works_master']}
    removed_edition_ids = set()

    for entry in bibliography['entries']:
        expected = entry['expected_work']
        target = entry['target_work']
        assert masters[expected['work_id']] == target
        masters[expected['work_id']] = copy.deepcopy(expected)
        edition = entry.get('edition')
        if edition:
            matches = [row for row in source['work_editions'] if row['canonical_url'] == edition['canonical_url']]
            assert len(matches) == 1
            removed_edition_ids.add(matches[0]['edition_id'])
        if expected['canonical_title'] != target['canonical_title']:
            source['work_aliases'] = [
                row
                for row in source['work_aliases']
                if not (row['work_id'] == expected['work_id'] and row['alias'] == expected['canonical_title'])
            ]

    source['works_master'] = list(masters.values())
    source['work_editions'] = [row for row in source['work_editions'] if row['edition_id'] not in removed_edition_ids]
    source['work_edition_identifiers'] = [
        row for row in source['work_edition_identifiers'] if row['edition_id'] not in removed_edition_ids
    ]

    corrections = _load('work_catalog_corrections_batch2.json')
    masters = {row['work_id']: row for row in source['works_master']}
    removals_by_owner = defaultdict(list)
    for correction in corrections['corrections']:
        expected = correction['expected_work']
        assert masters[expected['work_id']] == correction['target_work']
        masters[expected['work_id']] = copy.deepcopy(expected)
        for removal in correction['link_removals']:
            row = copy.deepcopy(removal['expected'])
            table = removal['table']
            owner = (row['fetish_id'],) if table == 'fetish_work_links' else (row['id_a'], row['id_b'])
            removals_by_owner[(table, owner)].append(row)
    source['works_master'] = list(masters.values())

    for table in ('fetish_work_links', 'compound_work_links'):
        owner_fields = ('fetish_id',) if table == 'fetish_work_links' else ('id_a', 'id_b')
        grouped = defaultdict(list)
        for link in source[table]:
            grouped[tuple(link[field] for field in owner_fields)].append(link)
        for (removal_table, owner), removals in removals_by_owner.items():
            if removal_table != table:
                continue
            links = sorted(grouped[owner], key=lambda row: row['position'])
            for removal in sorted(removals, key=lambda row: row['position']):
                links.insert(removal['position'], removal)
            for position, link in enumerate(links):
                link['position'] = position
            grouped[owner] = links
        source[table] = [link for links in grouped.values() for link in links]

    work_catalog._sort_catalog_rows(source)
    work_catalog.validate_catalog(source)
    return source


def _apply_batch2():
    phase1 = _load('work_catalog.json')
    corrections = _load('work_catalog_corrections_batch2.json')
    bibliography = _load('work_catalog_bibliography_batch2.json')
    corrected = work_catalog.apply_catalog_corrections(phase1, corrections)
    final, result = work_catalog.apply_bibliography_manifest(corrected, bibliography)
    return phase1, corrected, final, corrections, bibliography, result


def _counts(catalog):
    return {table: len(catalog[table]) for table in TABLES}


def test_batch2_counts_and_both_manifests_are_idempotent():
    phase1, corrected, final, corrections, bibliography, result = _apply_batch2()

    assert _counts(phase1) == {
        'works_master': 325,
        'work_editions': 265,
        'work_edition_identifiers': 25,
        'work_aliases': 164,
        'fetish_work_links': 373,
        'compound_work_links': 120,
        'review_queue': 74,
    }
    assert _counts(final) == {
        'works_master': 325,
        'work_editions': 265,
        'work_edition_identifiers': 25,
        'work_aliases': 164,
        'fetish_work_links': 373,
        'compound_work_links': 120,
        'review_queue': 74,
    }
    assert result == {
        'entry_count': 13,
        'work_update_count': 0,
        'edition_count': 0,
        'identifier_count': 0,
    }
    assert work_catalog.apply_catalog_corrections(corrected, corrections) == corrected
    reapplied, second_result = work_catalog.apply_bibliography_manifest(final, bibliography)
    assert reapplied == final
    assert second_result == {
        'entry_count': 13,
        'work_update_count': 0,
        'edition_count': 0,
        'identifier_count': 0,
    }


def test_batch2_quarantine_set_is_exact_archived_and_unreferenced():
    _, _, final, corrections, _, _ = _apply_batch2()
    quarantined_ids = {row['target_work']['work_id'] for row in corrections['corrections']}
    masters = {row['work_id']: row for row in final['works_master']}
    referenced_ids = {row['work_id'] for table in ('fetish_work_links', 'compound_work_links') for row in final[table]}

    assert len(corrections['corrections']) == 20
    assert sum(len(row['link_removals']) for row in corrections['corrections']) == 21
    assert quarantined_ids == GENERIC_IDS | {PALMA_ID}
    assert len(GENERIC_IDS) == 19
    assert all(masters[work_id]['status'] == 'archived' for work_id in quarantined_ids)
    assert not (quarantined_ids & referenced_ids)


def test_batch2_bibliography_sources_and_targets_are_exactly_locked():
    _, _, final, _, bibliography, _ = _apply_batch2()
    target_masters = {row['work_id']: row for row in final['works_master']}
    assert sum(entry['expected_work'] != entry['target_work'] for entry in bibliography['entries']) == 8
    assert (
        sum(
            bool((entry.get('edition') or {}).get('isbn') or (entry.get('edition') or {}).get('identifier'))
            for entry in bibliography['entries']
        )
        == 11
    )

    assert len(bibliography['entries']) == 13
    assert {row['entry_id'] for row in bibliography['entries']} == BIBLIOGRAPHY_ENTRY_IDS
    assert sum('edition' in row for row in bibliography['entries']) == 12
    for entry in bibliography['entries']:
        work_id = entry['expected_work']['work_id']
        assert entry['target_work']['work_id'] == work_id
        assert set(entry['expected_work']) == {
            'work_id',
            'canonical_title',
            'normalized_title',
            'media_type',
            'status',
        }
        assert entry['expected_work']['status'] == 'active'
        assert target_masters[work_id] == entry['target_work']


def test_batch2_leaves_only_media_confirmed_hana_wa_saku_ka_without_an_edition():
    _, _, final, _, bibliography, _ = _apply_batch2()
    candidates = build_work_catalog_research_candidates.build_candidates(
        final,
        (_load('work_catalog_bibliography.json'), bibliography),
    )

    assert candidates['entries'] == [
        {
            'work_id': 'wrk_b0c6dc64fe5060a13680',
            'canonical_title': '花は咲くか',
            'media_type': 'manga',
            'owner_references': [
                {
                    'table': 'compound_work_links',
                    'id_a': 2,
                    'id_b': 6,
                    'position': 0,
                }
            ],
            'bibliography_state': 'media_confirmed',
        }
    ]


def test_batch2_reindexes_every_owner_and_preserves_identifier_uniqueness_and_safe_urls():
    _, _, final, _, bibliography, _ = _apply_batch2()
    owner_positions = defaultdict(list)
    for link in final['fetish_work_links']:
        owner_positions[('fetish', link['fetish_id'])].append(link['position'])
    for link in final['compound_work_links']:
        owner_positions[('compound', link['id_a'], link['id_b'])].append(link['position'])
    assert all(sorted(positions) == list(range(len(positions))) for positions in owner_positions.values())

    identifiers = final['work_edition_identifiers']
    keys = [(row['scheme'], row['authority'], row['value']) for row in identifiers]
    assert len(identifiers) == 25
    assert len(keys) == len(set(keys))
    assert len({row['identifier_id'] for row in identifiers}) == len(identifiers)
    assert all(safe_work_url(row['canonical_url']) == row['canonical_url'] for row in final['work_editions'])
    for entry in bibliography['entries']:
        url = entry.get('evidence_url') or entry['edition']['canonical_url']
        assert safe_work_url(url) == url


def test_batch2_inline_projection_round_trips_phase2_source():
    fetishes = _load('fetishes.json')
    compounds = _load('compound_works.json')
    correction_manifests = tuple(
        _load(name)
        for name in (
            'work_catalog_corrections.json',
            'work_catalog_corrections_batch2.json',
            'work_catalog_link_bindings_batch2.json',
        )
    )

    source = work_catalog.project_approved_inline_correction_manifests(
        fetishes,
        compound_rows=compounds,
        correction_manifests=correction_manifests,
        direction='reverse',
    )
    forward = work_catalog.project_approved_inline_correction_manifests(
        source['fetishes'],
        compound_rows=source['compound_rows'],
        correction_manifests=correction_manifests,
    )

    assert forward['fetishes'] == fetishes
    assert forward['compound_rows'] == compounds
