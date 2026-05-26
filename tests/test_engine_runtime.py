import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import engine_runtime


class TestEngineRuntimeHelpers(unittest.TestCase):
    def test_disc_scales_normalizes_and_clamps_like_engine_cache(self):
        probabilities = {
            (0, 0): 0.9,
            (1, 0): 0.1,
            (0, 1): 0.55,
            (1, 1): 0.45,
            (0, 2): 0.5,
            (1, 2): 0.5,
        }
        scales = engine_runtime.disc_scales(2, 3, probability=lambda f, q: probabilities[(f, q)])
        self.assertEqual(scales, [2.0, 0.5, 0.5])


    def test_disc_scales_can_exclude_neutral_extension_questions_from_mean(self):
        probabilities = {
            (0, 0): 0.9,
            (1, 0): 0.1,
            (0, 1): 0.55,
            (1, 1): 0.45,
            (0, 2): 0.5,
            (1, 2): 0.5,
        }
        base = engine_runtime.disc_scales(2, 2, probability=lambda f, q: probabilities[(f, q)])
        extended = engine_runtime.disc_scales(
            2,
            3,
            probability=lambda f, q: probabilities[(f, q)],
            mean_question_indexes=[0, 1],
        )
        self.assertEqual(extended[:2], base)
        self.assertEqual(extended[2], 0.5)

    def test_disc_scales_handles_empty_inputs(self):
        self.assertEqual(engine_runtime.disc_scales(0, 0, probability=lambda f, q: 0.5), [])
        self.assertEqual(engine_runtime.disc_scales(0, 2, probability=lambda f, q: 0.5), [0.5, 0.5])

    def test_dynamic_prior_weights_preserves_blend_and_floor_contract(self):
        weights = engine_runtime.dynamic_prior_weights(
            [{'id': 1}, {'id': 2}, {'id': 3}],
            {
                1: {'guessed': 0, 'correct': 0},
                2: {'guessed': 10, 'correct': 8},
                3: {'guessed': 20, 'correct': 0},
            },
            {1: 2.0, 2: 1.5, 3: 0.01},
        )
        self.assertEqual(weights[1], 2.0)
        self.assertAlmostEqual(weights[2], 1.1071428571428572)
        self.assertEqual(weights[3], 0.1)

    def test_entropy_ignores_zero_and_tiny_probabilities(self):
        self.assertAlmostEqual(engine_runtime.entropy([0.5, 0.5, 0.0, 1e-11]), 1.0)
