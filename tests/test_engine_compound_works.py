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
