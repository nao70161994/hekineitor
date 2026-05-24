import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from engine import Engine

MATRIX_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'matrix.json')


class TestEngineQuestionSelectionRegression(unittest.TestCase):
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
            patch('engine_question_selection.random.choice', side_effect=lambda pool: pool[0]),
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

    def test_best_question_snapshots_with_deterministic_randomness(self):
        cases = [
            ({}, set(), 0, 0),
            ({'0': 0, '1': 0}, {0, 1}, 2, 91),
            ({'8': 1, '6': 1, '0': 1, '40': 1}, {0, 6, 8, 40}, 0, 37),
        ]
        for answers, asked, idk_streak, expected_question in cases:
            with self.subTest(expected_question=expected_question):
                self.assertEqual(
                    self.engine.best_question(answers, asked, idk_streak=idk_streak),
                    expected_question,
                )

    def test_best_disambiguating_question_snapshots(self):
        cases = [
            ({}, set(), 0, 2),
            ({'0': 0, '1': 0}, {0, 1}, 2, 2),
            ({'8': 1, '6': 1, '0': 1, '40': 1}, {0, 6, 8, 40}, 0, 2),
        ]
        for answers, asked, idk_streak, expected_question in cases:
            with self.subTest(expected_question=expected_question):
                self.assertEqual(
                    self.engine.best_disambiguating_question(
                        answers,
                        asked,
                        candidate_count=3,
                        idk_streak=idk_streak,
                    ),
                    expected_question,
                )
