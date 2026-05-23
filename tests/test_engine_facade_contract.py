import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import engine_inference
import engine_learning
import engine_question_selection
from engine import (
    AXIS_INDIRECT_BONUS,
    EARLY_RANDOM_DEPTH,
    EARLY_RANDOM_TOP_K,
    Engine,
    FETISH_PRIOR_WEIGHTS,
    FOCUS_THRESHOLD,
    FOCUS_TOP_N,
    PSEUDO,
    QUESTION_AXES,
    UCB_EXPLORE_C,
)

MATRIX_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'matrix.json')


class TestEngineFacadeContract(unittest.TestCase):
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

    def test_inference_facade_matches_helper_module(self):
        answers = {'0': 1, '3': -1, '8': 1, '11': 0}
        self.assertEqual(
            self.engine.posteriors(answers),
            engine_inference.posteriors(
                self.engine,
                answers,
                fetish_prior_weights=FETISH_PRIOR_WEIGHTS,
            ),
        )
        self.assertEqual(
            self.engine.top_guess(answers, n=3),
            engine_inference.top_guess(self.engine, answers, n=3),
        )
        self.assertEqual(
            self.engine.get_answer_contributions(answers, 0, top_n=2),
            engine_inference.answer_contributions(self.engine, answers, 0, top_n=2),
        )

    def test_question_selection_facade_matches_helper_module(self):
        answers = {'8': 1, '6': 1, '0': 1}
        asked = {0, 6, 8}
        with patch('engine_question_selection.random.choice', side_effect=lambda pool: pool[0]):
            facade_question = self.engine.best_question(answers, asked, idk_streak=1)
            helper_question = engine_question_selection.best_question(
                self.engine,
                answers,
                asked,
                idk_streak=1,
                question_axes=QUESTION_AXES,
                focus_threshold_default=FOCUS_THRESHOLD,
                ucb_explore_c=UCB_EXPLORE_C,
                focus_top_n=FOCUS_TOP_N,
                early_random_depth=EARLY_RANDOM_DEPTH,
                early_random_top_k=EARLY_RANDOM_TOP_K,
                axis_indirect_bonus=AXIS_INDIRECT_BONUS,
            )
        self.assertEqual(facade_question, helper_question)
        self.assertEqual(
            self.engine.best_disambiguating_question(answers, asked, candidate_count=3, idk_streak=1),
            engine_question_selection.best_disambiguating_question(
                self.engine,
                answers,
                asked,
                candidate_count=3,
                idk_streak=1,
            ),
        )

    def test_learning_facade_matches_helper_module_for_positive_learning(self):
        answers = {'8': 1, '9': -1, '10': 0}
        facade_engine = self.engine
        helper_engine = Engine()

        facade_engine.learn(answers, 0, strength_factor=0.5)
        engine_learning.learn(helper_engine, answers, 0, strength_factor=0.5, pseudo=PSEUDO)

        self.assertEqual(facade_engine.matrix['yes'][0], helper_engine.matrix['yes'][0])
        self.assertEqual(facade_engine.matrix['total'][0], helper_engine.matrix['total'][0])
        self.assertEqual(facade_engine.matrix['yes'][1], helper_engine.matrix['yes'][1])
        self.assertEqual(facade_engine.matrix['total'][1], helper_engine.matrix['total'][1])

    def test_public_engine_module_exports_remain_available(self):
        import engine

        expected_exports = [
            'Engine',
            'PLAYER_FETISH_BASE_ID',
            'FOCUS_THRESHOLD',
            'FETISH_RELATIONS',
            'get_compound_works',
            'list_compound_works',
            'set_compound_works',
            'delete_compound_works',
            'parse_works_list',
        ]
        for name in expected_exports:
            self.assertTrue(hasattr(engine, name), name)
