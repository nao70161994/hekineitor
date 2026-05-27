import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from engine import Engine



class TestEngineInferenceRegression(unittest.TestCase):
    def setUp(self):
        self._patches = [
            patch.object(Engine, '_save_matrix_file', return_value=None),
            patch.object(Engine, '_save_fetishes_file', return_value=None),
            patch.object(Engine, '_save_to_db', return_value=None),
            patch.object(Engine, '_load_matrix_file', new=lambda self: self._init_matrix_file()),
            patch.object(Engine, 'get_fetish_log', return_value={}),
        ]
        for patcher in self._patches:
            patcher.start()
        self.engine = Engine()

    def tearDown(self):
        for patcher in self._patches:
            patcher.stop()

    def assert_top_guess_ids_and_probs(self, answers, expected):
        actual = self.engine.top_guess(answers, n=len(expected))
        actual_ids = [self.engine.fetishes[idx]['id'] for idx, _prob in actual]
        self.assertEqual(actual_ids, [fid for fid, _prob in expected])
        for (_idx, actual_prob), (_fid, expected_prob) in zip(actual, expected):
            self.assertAlmostEqual(actual_prob, expected_prob, places=8)

    def test_empty_answers_top_guess_snapshot(self):
        self.assert_top_guess_ids_and_probs({}, [
            (0, 0.01640241),
            (10, 0.01640241),
            (23, 0.01640241),
            (16, 0.01366867),
            (17, 0.01366867),
        ])

    def test_ntr_signal_top_guess_snapshot(self):
        self.assert_top_guess_ids_and_probs({'8': 1, '6': 1, '0': 1, '40': 1}, [
            (0, 0.03596150),
            (10, 0.02433485),
            (3, 0.01712452),
            (18, 0.01622323),
            (99, 0.01622323),
        ])

    def test_soft_mixed_answers_top_guess_snapshot(self):
        self.assert_top_guess_ids_and_probs({'0': 1, '3': -1, '9': 0.5, '15': -0.5}, [
            (0, 0.01843719),
            (18, 0.01843719),
            (99, 0.01843719),
            (35, 0.01567161),
            (3, 0.01556918),
        ])
