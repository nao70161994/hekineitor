import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from engine import Engine


class TestEngineLearningRegression(unittest.TestCase):
    def setUp(self):
        self._patches = [
            patch.object(Engine, '_save_matrix_file', return_value=None),
            patch.object(Engine, '_save_fetishes_file', return_value=None),
            patch.object(Engine, '_save_to_db', return_value=None),
            patch.object(Engine, '_load_matrix_file', new=lambda self: self._init_matrix_file()),
            patch.object(Engine, 'get_fetish_log', return_value={}),
            patch.object(Engine, '_increment_learn_count', return_value=None),
        ]
        for patcher in self._patches:
            patcher.start()

    def tearDown(self):
        for patcher in self._patches:
            patcher.stop()

    def assert_cells(self, engine, expected):
        for fetish_idx, questions in expected.items():
            for question_idx, (yes, total) in questions.items():
                with self.subTest(fetish_idx=fetish_idx, question_idx=question_idx):
                    self.assertAlmostEqual(engine.matrix['yes'][fetish_idx][question_idx], yes, places=10)
                    self.assertAlmostEqual(engine.matrix['total'][fetish_idx][question_idx], total, places=10)

    def test_positive_learning_matrix_delta_snapshot(self):
        engine = Engine()
        engine.learn({'8': 1, '9': -1, '10': 0}, 0, strength_factor=0.5)
        self.assert_cells(
            engine,
            {
                0: {8: (19.765263926052054, 20.765263926052054), 9: (2.0, 4.921795183653612), 10: (2.0, 4.0)},
                1: {8: (2.0, 4.0), 9: (19.0, 20.0), 10: (2.0, 4.0)},
            },
        )

    def test_positive_learning_leaves_every_non_target_cell_unchanged(self):
        engine = Engine()
        other_yes_before = list(engine.matrix['yes'][1])
        other_total_before = list(engine.matrix['total'][1])

        engine.learn({'8': 1, '9': -1}, 0, strength_factor=0.5)

        self.assertEqual(engine.matrix['yes'][1], other_yes_before)
        self.assertEqual(engine.matrix['total'][1], other_total_before)

    def test_near_miss_learning_matrix_delta_snapshot(self):
        engine = Engine()
        engine.learn_near_miss({'8': 1, '9': -1, '10': 0}, 0, strength_factor=0.5)
        self.assert_cells(
            engine,
            {
                0: {8: (19.26784237411822, 20.26784237411822), 9: (2.0, 4.322628314278764), 10: (2.0, 4.0)},
                1: {8: (2.0, 4.0), 9: (19.0, 20.0), 10: (2.0, 4.0)},
            },
        )

    def test_negative_learning_matrix_delta_snapshot(self):
        engine = Engine()
        engine.learn_negative({'8': 1, '9': -1, '10': 0}, 0, strength_factor=0.5)
        self.assert_cells(
            engine,
            {
                0: {8: (19.0, 20.1), 9: (2.1, 4.1), 10: (2.0, 4.0)},
                1: {8: (2.0, 4.0), 9: (19.0, 20.0), 10: (2.0, 4.0)},
            },
        )

    def test_cooccurrence_learning_matrix_delta_snapshot(self):
        engine = Engine()
        engine.learn_cooccurrence({'8': 1, '9': -1, '10': 0}, 0, 1, factor=0.25)
        self.assert_cells(
            engine,
            {
                0: {8: (19.0, 20.0), 9: (2.0, 4.0), 10: (2.0, 4.0)},
                1: {8: (2.1125, 4.1125), 9: (19.0, 20.0), 10: (2.0, 4.0)},
            },
        )
