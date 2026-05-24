import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from engine import Engine

MATRIX_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'matrix.json')


class TestEngineInferenceRegression(unittest.TestCase):
    def setUp(self):
        self._matrix_backup = None
        if os.path.exists(MATRIX_PATH):
            with open(MATRIX_PATH, 'rb') as f:
                self._matrix_backup = f.read()
            os.remove(MATRIX_PATH)

        self._patches = [
            patch.object(Engine, '_save_matrix_file', return_value=None),
            patch.object(Engine, '_save_fetishes_file', return_value=None),
            patch.object(Engine, '_save_to_db', return_value=None),
            patch.object(Engine, 'get_fetish_log', return_value={}),
        ]
        for patcher in self._patches:
            patcher.start()
        self.engine = Engine()

    def tearDown(self):
        for patcher in self._patches:
            patcher.stop()
        if self._matrix_backup is not None:
            with open(MATRIX_PATH, 'wb') as f:
                f.write(self._matrix_backup)

    def assert_top_guess_ids_and_probs(self, answers, expected):
        actual = self.engine.top_guess(answers, n=len(expected))
        actual_ids = [self.engine.fetishes[idx]['id'] for idx, _prob in actual]
        self.assertEqual(actual_ids, [fid for fid, _prob in expected])
        for (_idx, actual_prob), (_fid, expected_prob) in zip(actual, expected):
            self.assertAlmostEqual(actual_prob, expected_prob, places=8)

    def test_empty_answers_top_guess_snapshot(self):
        self.assert_top_guess_ids_and_probs({}, [
            (0, 0.01624256),
            (10, 0.01624256),
            (23, 0.01624256),
            (16, 0.01353546),
            (17, 0.01353546),
        ])

    def test_ntr_signal_top_guess_snapshot(self):
        self.assert_top_guess_ids_and_probs({'8': 1, '6': 1, '0': 1, '40': 1}, [
            (0, 0.03554502),
            (10, 0.02405302),
            (3, 0.01692620),
            (18, 0.01603535),
            (99, 0.01603535),
        ])

    def test_soft_mixed_answers_top_guess_snapshot(self):
        self.assert_top_guess_ids_and_probs({'0': 1, '3': -1, '9': 0.5, '15': -0.5}, [
            (0, 0.01826877),
            (18, 0.01826877),
            (99, 0.01826877),
            (35, 0.01552846),
            (3, 0.01542696),
        ])
