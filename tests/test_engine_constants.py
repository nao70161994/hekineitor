import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import engine
import engine_constants


class TestEngineConstantsCompatibility(unittest.TestCase):
    def test_engine_reexports_scalar_constants(self):
        names = [
            'PLAYER_FETISH_BASE_ID',
            'PSEUDO',
            'AXIS_INDIRECT_BONUS',
            'FOCUS_THRESHOLD',
            'FOCUS_TOP_N',
            'EARLY_RANDOM_DEPTH',
            'EARLY_RANDOM_TOP_K',
            'UCB_EXPLORE_C',
        ]
        for name in names:
            self.assertIs(getattr(engine, name), getattr(engine_constants, name))

    def test_constant_values_remain_stable(self):
        self.assertEqual(engine_constants.PLAYER_FETISH_BASE_ID, 10000)
        self.assertEqual(engine_constants.PSEUDO, 20)
        self.assertEqual(engine_constants.FOCUS_THRESHOLD, 0.40)
        self.assertEqual(engine_constants.FOCUS_TOP_N, 6)
        self.assertEqual(engine_constants.EARLY_RANDOM_DEPTH, 3)
        self.assertEqual(engine_constants.EARLY_RANDOM_TOP_K, 5)
        self.assertEqual(engine_constants.UCB_EXPLORE_C, 0.05)
        self.assertEqual(
            engine_constants.AXIS_INDIRECT_BONUS,
            {'content': 1.0, 'abstract': 1.01, 'personality': 1.02},
        )
