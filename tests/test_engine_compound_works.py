import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import engine_compound_works


class TestEngineCompoundWorksHelpers(unittest.TestCase):
    def test_pair_key_normalizes_id_order(self):
        self.assertEqual(engine_compound_works.pair_key(200, 100), '100,200')
        self.assertEqual(engine_compound_works.pair_key(100, 200), '100,200')

    def test_serialize_compound_works_sorts_and_parses_ids(self):
        rows = engine_compound_works.serialize_compound_works({
            '3,4': ['B'],
            '1,2': ['A'],
        })
        self.assertEqual([row['key'] for row in rows], ['1,2', '3,4'])
        self.assertEqual(rows[0], {'key': '1,2', 'id_a': 1, 'id_b': 2, 'works': ['A']})

    def test_serialize_compound_works_skips_malformed_keys(self):
        rows = engine_compound_works.serialize_compound_works({
            '1,2': ['A'],
            'bad': ['skip'],
        })
        self.assertEqual([row['key'] for row in rows], ['1,2'])


class TestEngineCompoundWorksCacheHelpers(unittest.TestCase):
    def test_load_cache_loads_once(self):
        calls = []

        def load_fn(name, default=None):
            calls.append((name, default))
            return {'1,2': ['A']}

        self.assertEqual(
            engine_compound_works.load_cache(loaded=False, load_fn=load_fn),
            {'1,2': ['A']},
        )
        self.assertIsNone(engine_compound_works.load_cache(loaded=True, load_fn=load_fn))
        self.assertEqual(calls, [('compound_works.json', {})])

    def test_save_cache_uses_json_writer_options(self):
        calls = []
        engine_compound_works.save_cache(
            '/tmp/compound.json',
            {'1,2': ['A']},
            lambda *args, **kwargs: calls.append((args, kwargs)),
        )
        self.assertEqual(calls[0][0], ('/tmp/compound.json', {'1,2': ['A']}))
        self.assertEqual(calls[0][1], {'ensure_ascii': False, 'indent': 2})

    def test_get_works_returns_copy(self):
        cache = {'1,2': ['A']}
        works = engine_compound_works.get_works(cache, 2, 1)
        works.append('B')
        self.assertEqual(cache['1,2'], ['A'])

    def test_set_and_delete_works_mutate_cache_by_normalized_key(self):
        cache = {}
        self.assertEqual(engine_compound_works.set_works(cache, 2, 1, ['A']), '1,2')
        self.assertEqual(cache, {'1,2': ['A']})
        self.assertFalse(engine_compound_works.delete_works(cache, 9, 8))
        self.assertTrue(engine_compound_works.delete_works(cache, 1, 2))
        self.assertEqual(cache, {})


class TestEngineCompoundWorksPublicCacheBehavior(unittest.TestCase):
    def setUp(self):
        import engine as engine_module

        self.engine = engine_module
        self.original_cache = engine_module._COMPOUND_WORKS
        self.original_loaded = engine_module._compound_works_loaded
        engine_module._COMPOUND_WORKS = {}
        engine_module._compound_works_loaded = False

    def tearDown(self):
        self.engine._COMPOUND_WORKS = self.original_cache
        self.engine._compound_works_loaded = self.original_loaded

    def test_load_compound_works_uses_cache_after_first_load(self):
        calls = []
        original_loader = self.engine.load_json_file
        try:
            self.engine.load_json_file = lambda name, default=None: calls.append((name, default)) or {'1,2': ['A']}
            self.assertEqual(self.engine.get_compound_works(1, 2), ['A'])
            self.assertEqual(self.engine.get_compound_works(2, 1), ['A'])
        finally:
            self.engine.load_json_file = original_loader
        self.assertEqual(calls, [('compound_works.json', {})])

    def test_set_and_delete_public_functions_save_only_on_mutation(self):
        calls = []
        original_save = self.engine._save_compound_works
        try:
            self.engine._compound_works_loaded = True
            self.engine._save_compound_works = lambda: calls.append('save')
            key = self.engine.set_compound_works(2, 1, ['A'])
            missing_deleted = self.engine.delete_compound_works(9, 8)
            existing_deleted = self.engine.delete_compound_works(1, 2)
        finally:
            self.engine._save_compound_works = original_save
        self.assertEqual(key, '1,2')
        self.assertFalse(missing_deleted)
        self.assertTrue(existing_deleted)
        self.assertEqual(calls, ['save', 'save'])
