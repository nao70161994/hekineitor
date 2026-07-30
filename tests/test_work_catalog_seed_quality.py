import json
from collections import Counter
from pathlib import Path

import pytest

from engine import work_catalog
from scripts.build_work_catalog import build_catalog
from work_utils import work_title

ROOT = Path(__file__).resolve().parents[1]
PLACEHOLDERS = {'作品X', '作品Y', '作品Z', 'おれたち○○のいいやつ'}


def test_seed_normalizations_preserve_ids_and_public_display():
    fetishes = [
        {
            'id': 1,
            'works': [
                {
                    'title': '作品名（人物）',
                    'url': 'https://www.amazon.co.jp/dp/B000000001',
                }
            ],
        }
    ]
    baseline = work_catalog.build_catalog_from_inline(fetishes)
    normalized = work_catalog.build_catalog_from_inline(
        fetishes,
        seed_overrides={
            'schema_version': 1,
            'title_normalizations': [
                {
                    'display_title': '作品名（人物）',
                    'canonical_title': '作品名',
                    'context_label': '人物',
                }
            ],
        },
    )

    assert normalized['works_master'][0]['work_id'] == baseline['works_master'][0]['work_id']
    assert normalized['work_editions'][0]['edition_id'] == baseline['work_editions'][0]['edition_id']
    assert normalized['works_master'][0]['canonical_title'] == '作品名'
    assert normalized['work_aliases'][0]['alias'] == '作品名（人物）'
    assert normalized['fetish_work_links'][0]['context_label'] == '人物'
    assert work_catalog.materialize_fetish_works(normalized)[1][0]['title'] == '作品名（人物）'


@pytest.mark.parametrize(
    'overrides, message',
    [
        ({'schema_version': 2, 'title_normalizations': []}, 'schema_version'),
        ({'schema_version': {}, 'title_normalizations': []}, 'schema_version'),
        ({'schema_version': 1, 'title_normalizations': {}}, 'must be a list'),
        (
            {
                'schema_version': 1,
                'title_normalizations': [
                    {'display_title': 'A', 'canonical_title': 'A'},
                    {'display_title': 'A', 'canonical_title': 'A'},
                ],
            },
            'duplicate',
        ),
    ],
)
def test_seed_normalization_manifest_rejects_invalid_input(overrides, message):
    with pytest.raises(ValueError, match=message):
        work_catalog.build_catalog_from_inline([], seed_overrides=overrides)


def test_seed_overrides_apply_transaction_is_idempotent_and_fail_closed():
    fetishes = [
        {
            'id': 1,
            'works': [{'title': '作品名（人物）', 'url': 'https://www.amazon.co.jp/dp/B000000001'}],
        },
        {'id': 2, 'works': []},
    ]
    baseline = work_catalog.build_catalog_from_inline(
        fetishes,
        compound_rows=[{'id_a': 1, 'id_b': 2, 'works': ['作品X']}],
    )
    manifest = {
        'schema_version': 1,
        'remove_display_titles': ['作品X'],
        'title_normalizations': [
            {
                'display_title': '作品名（人物）',
                'canonical_title': '作品名',
                'context_label': '人物',
            }
        ],
    }

    updated = work_catalog.apply_seed_overrides(baseline, manifest)

    assert [row['canonical_title'] for row in updated['works_master']] == ['作品名']
    assert updated['compound_work_links'] == []
    assert work_catalog.materialize_fetish_works(updated)[1][0]['title'] == '作品名（人物）'
    assert updated['fetish_work_links'][0]['context_label'] == '人物'
    assert work_catalog.apply_seed_overrides(updated, manifest) == updated

    drifted = work_catalog.build_catalog_from_inline(
        [
            {
                'id': 1,
                'works': [
                    {'title': '作品名（人物）', 'url': 'https://www.amazon.co.jp/dp/B000000001'},
                    {'title': '作品名（人物）', 'url': 'https://www.amazon.co.jp/dp/B000000002'},
                ],
            }
        ]
    )
    with pytest.raises(ValueError, match='display drift'):
        work_catalog.apply_seed_overrides(drifted, manifest)


def test_existing_reviewed_catalog_migrates_to_exact_fresh_seed():
    fetishes = [
        {
            'id': 1,
            'works': [
                {'title': '作品名（人物）', 'url': 'https://www.amazon.co.jp/dp/B000000001'},
                {'title': '作品名', 'url': 'https://www.amazon.co.jp/dp/B000000002'},
            ],
        },
        {'id': 2, 'works': []},
    ]
    legacy = work_catalog.build_catalog_from_inline(
        fetishes,
        compound_rows=[{'id_a': 1, 'id_b': 2, 'works': ['作品X']}],
    )
    review = legacy['review_queue'][0]
    target_id = next(row['work_id'] for row in legacy['works_master'] if row['canonical_title'] == '作品名')
    decisions = {
        'schema_version': 1,
        'reviewed_at': '2026-07-28',
        'decisions': [
            {
                'review_id': review['review_id'],
                'candidate_key': review['candidate_key'],
                'work_ids': review['work_ids'],
                'decision': 'merge',
                'target_work_id': target_id,
            }
        ],
    }
    manifest = {
        'schema_version': 1,
        'remove_display_titles': ['作品X'],
        'title_normalizations': [
            {
                'display_title': '作品名（人物）',
                'canonical_title': '作品名',
                'context_label': '人物',
            }
        ],
    }
    existing = work_catalog.apply_review_decisions(legacy, decisions)
    fresh = work_catalog.build_catalog_from_inline(fetishes, seed_overrides=manifest)
    fresh = work_catalog.apply_review_decisions(fresh, decisions)

    migrated = work_catalog.apply_seed_overrides(existing, manifest)

    assert migrated == fresh
    assert work_catalog.apply_seed_overrides(migrated, manifest) == migrated
    for table, prefix, owners in (
        ('fetish_work_links', 'fwl', ('fetish_id',)),
        ('compound_work_links', 'cwl', ('id_a', 'id_b')),
    ):
        for link in migrated[table]:
            assert link['link_id'] == work_catalog._stable_id(
                prefix,
                *(link[field] for field in owners),
                link['work_id'],
                link.get('edition_id'),
                link.get('alias_id'),
            )


def test_checked_in_seed_has_only_verified_safe_normalizations():
    catalog = build_catalog()
    overrides = json.loads((ROOT / 'data/work_catalog_seed_overrides.json').read_text(encoding='utf-8'))
    compound_source = json.loads((ROOT / 'data/compound_works.json').read_text(encoding='utf-8'))
    corrections = json.loads((ROOT / 'data/work_catalog_corrections.json').read_text(encoding='utf-8'))
    masters = {row['work_id']: row for row in catalog['works_master']}
    aliases = {row['alias_id']: row for row in catalog['work_aliases']}
    links = catalog['fetish_work_links'] + catalog['compound_work_links']

    assert not PLACEHOLDERS.intersection(row['canonical_title'] for row in masters.values())
    assert not PLACEHOLDERS.intersection(
        work.get('title', '') if isinstance(work, dict) else work
        for works in compound_source.values()
        for work in works
    )

    for expected in overrides['title_normalizations']:
        matching_aliases = [row for row in aliases.values() if row['alias'] == expected['display_title']]
        assert matching_aliases, expected['display_title']
        for alias in matching_aliases:
            assert masters[alias['work_id']]['canonical_title'] == expected['canonical_title']
        matching_links = [
            row for row in links if row.get('alias_id') in {alias['alias_id'] for alias in matching_aliases}
        ]
        assert matching_links, expected['display_title']
        assert all(row['context_label'] == expected['context_label'] for row in matching_links)
    corrected_fetish_titles = {}
    corrected_compound_titles = {}
    for correction in corrections['corrections']:
        added_aliases = {
            row['target']['alias_id']: row['target']['alias'] for row in correction.get('alias_additions', [])
        }
        for update in correction.get('link_updates', []):
            title = added_aliases.get(update.get('alias_id'), correction['target_work']['canonical_title'])
            expected_link = update['expected']
            if update['table'] == 'fetish_work_links':
                corrected_fetish_titles[(expected_link['fetish_id'], expected_link['position'])] = title
            else:
                key = f'{expected_link["id_a"]},{expected_link["id_b"]}'
                corrected_compound_titles[(key, expected_link['position'])] = title

    fetish_source = json.loads((ROOT / 'data/fetishes.json').read_text(encoding='utf-8'))
    materialized_fetishes = work_catalog.materialize_fetish_works(catalog)
    materialized_compounds = work_catalog.materialize_compound_works(catalog)
    for fetish in fetish_source:
        expected_titles = [
            corrected_fetish_titles.get((fetish['id'], position), work_title(row))
            for position, row in enumerate(fetish.get('works', []))
        ]
        assert [row['title'] for row in materialized_fetishes.get(fetish['id'], [])] == expected_titles
    for key, works in compound_source.items():
        expected_titles = [
            corrected_compound_titles.get((key, position), work_title(row)) for position, row in enumerate(works)
        ]
        assert [row['title'] for row in materialized_compounds.get(key, [])] == expected_titles

    canonical_titles = {row['canonical_title'] for row in masters.values()}
    assert '現実で30歳独身・無職、仮想現実でリア充（参考）' in canonical_titles
    assert '賭ケグルイ（参考）' not in {row['display_title'] for row in overrides['title_normalizations']}
    assert '賭ケグルイ（参考）' in {row['alias'] for row in aliases.values()}
    assert len([title for title in canonical_titles if title.startswith('ベルセルク')]) == 2
    assert len([title for title in canonical_titles if title.startswith('小林さんちのメイドラゴン')]) == 2
    assert sum(bool(row['media_type']) for row in masters.values()) == 22
    assert sum(row['format'] == 'paper' for row in catalog['work_editions']) == 12
    assert len(catalog['work_edition_identifiers']) == 14
    assert Counter(
        (row['scheme'], row['authority']) for row in catalog['work_edition_identifiers']
    ) == {('isbn', 'isbn'): 14}
    assert all(len(row['value']) == 13 and row['value'].isdigit() for row in catalog['work_edition_identifiers'])
    assert '4199007804' not in {row['value'] for row in catalog['work_edition_identifiers']}
