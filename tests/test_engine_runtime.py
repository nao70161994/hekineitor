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
                1: {'exposure_guessed': 0, 'exposure_correct': 0},
                2: {'exposure_guessed': 10, 'exposure_correct': 8},
                3: {'exposure_guessed': 20, 'exposure_correct': 0},
            },
            {1: 2.0, 2: 1.5, 3: 0.01},
        )
        self.assertEqual(weights[1], 2.0)
        self.assertAlmostEqual(weights[2], 1.1071428571428572)
        self.assertEqual(weights[3], 0.1)

    def test_dynamic_prior_completely_ignores_legacy_mixed_population(self):
        fetishes = [{'id': 1}]
        log = {1: {'guessed': 100, 'correct': 60, 'correction_selected': 50}}
        self.assertEqual(engine_runtime.dynamic_prior_weights(fetishes, log, {1: 1.25}), {1: 1.25})

    def test_dynamic_prior_uses_only_new_exposure_population(self):
        fetishes = [{'id': 1}]
        log = {
            1: {
                'guessed': 100,
                'correct': 60,
                'exposure_guessed': 10,
                'exposure_correct': 8,
            }
        }
        weights = engine_runtime.dynamic_prior_weights(fetishes, log, {1: 1.5})
        self.assertAlmostEqual(weights[1], 1.1071428571428572)

    def test_dynamic_prior_shadow_keeps_legacy_clamp_comparison_without_reclassification(self):
        fetishes = [{'id': 1}]
        log = {1: {'guessed': 2, 'correct': 50, 'correction_selected': 7}}
        weights = engine_runtime.dynamic_prior_weights(fetishes, log, {1: 1.0})
        self.assertEqual(weights[1], 1.0)
        shadow = engine_runtime.dynamic_prior_shadow_report(fetishes, log, {1: 1.0})
        self.assertEqual(shadow['schema_version'], 2)
        self.assertEqual(shadow['mismatched_count'], 1)
        self.assertEqual(shadow['rows'][0]['correction_selected'], 7)
        self.assertEqual(shadow['excess_correct_count'], 48)
        self.assertEqual(shadow['legacy_row_count'], 1)
        self.assertEqual(shadow['exposure_guessed_count'], 0)
        self.assertEqual(shadow['exposure_correct_count'], 0)
        self.assertEqual(
            shadow['migration_policy']['strategy'],
            'non_destructive_exposure_counter_isolation',
        )
        self.assertFalse(shadow['migration_policy']['irreversible_reclassification_performed'])
        row = shadow['rows'][0]
        self.assertEqual(row['current_weight'], 1.0)
        self.assertNotEqual(row['legacy_clamped_weight'], row['legacy_unclamped_weight'])
        self.assertLess(row['current_weight'], row['legacy_unclamped_weight'])

    def test_entropy_ignores_zero_and_tiny_probabilities(self):
        self.assertAlmostEqual(engine_runtime.entropy([0.5, 0.5, 0.0, 1e-11]), 1.0)
