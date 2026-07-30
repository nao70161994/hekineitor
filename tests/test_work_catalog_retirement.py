import json
from pathlib import Path

import engine
from engine import work_catalog

ROOT = Path(__file__).resolve().parents[1]


def test_production_seed_has_no_legacy_recommendation_storage():
    fetishes = json.loads((ROOT / 'data' / 'fetishes.json').read_text(encoding='utf-8'))
    assert all('works' not in fetish for fetish in fetishes)
    assert not (ROOT / 'data' / 'compound_works.json').exists()


def test_normalized_catalog_is_the_complete_recommendation_seed():
    fetishes = json.loads((ROOT / 'data' / 'fetishes.json').read_text(encoding='utf-8'))
    catalog = json.loads((ROOT / 'data' / 'work_catalog.json').read_text(encoding='utf-8'))
    work_catalog.validate_catalog_fetish_references(catalog, {row['id'] for row in fetishes})
    assert work_catalog.materialize_fetish_works(catalog)
    assert work_catalog.materialize_compound_works(catalog)


def test_legacy_compound_storage_api_is_removed():
    for name in ('get_compound_works', 'list_compound_works', 'set_compound_works', 'delete_compound_works'):
        assert not hasattr(engine, name)
