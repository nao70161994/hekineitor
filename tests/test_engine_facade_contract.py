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


    def test_learning_facade_matches_helper_module_for_near_miss_and_negative(self):
        answers = {'8': 1, '9': -1, '10': 0}

        facade_near = self.engine
        helper_near = Engine()
        facade_near.learn_near_miss(answers, 0, strength_factor=0.5)
        engine_learning.learn_near_miss(helper_near, answers, 0, strength_factor=0.5, pseudo=PSEUDO)
        self.assertEqual(facade_near.matrix['yes'][0], helper_near.matrix['yes'][0])
        self.assertEqual(facade_near.matrix['total'][0], helper_near.matrix['total'][0])

        facade_negative = Engine()
        helper_negative = Engine()
        facade_negative.learn_negative(answers, 0, strength_factor=0.5)
        engine_learning.learn_negative(helper_negative, answers, 0, strength_factor=0.5, pseudo=PSEUDO)
        self.assertEqual(facade_negative.matrix['yes'][0], helper_negative.matrix['yes'][0])
        self.assertEqual(facade_negative.matrix['total'][0], helper_negative.matrix['total'][0])

    def test_learning_facade_matches_helper_module_for_cooccurrence(self):
        answers = {'8': 1, '9': -1, '10': 0}
        facade_engine = self.engine
        helper_engine = Engine()

        facade_engine.learn_cooccurrence(answers, 0, 1, factor=0.25)
        engine_learning.learn_cooccurrence(helper_engine, answers, 0, 1, factor=0.25, pseudo=PSEUDO)

        self.assertEqual(facade_engine.matrix['yes'][0], helper_engine.matrix['yes'][0])
        self.assertEqual(facade_engine.matrix['total'][0], helper_engine.matrix['total'][0])
        self.assertEqual(facade_engine.matrix['yes'][1], helper_engine.matrix['yes'][1])
        self.assertEqual(facade_engine.matrix['total'][1], helper_engine.matrix['total'][1])


    def test_learn_silent_facade_matches_helper_module(self):
        answers = {'8': 1, '9': -1, '10': 0}
        facade_engine = self.engine
        helper_engine = Engine()

        facade_engine._learn_silent(answers, 0, cold_start=True)
        engine_learning.learn_silent(helper_engine, answers, 0, cold_start=True, pseudo=PSEUDO)

        self.assertEqual(facade_engine.matrix['yes'][0], helper_engine.matrix['yes'][0])
        self.assertEqual(facade_engine.matrix['total'][0], helper_engine.matrix['total'][0])
        self.assertEqual(facade_engine.matrix['yes'][1], helper_engine.matrix['yes'][1])
        self.assertEqual(facade_engine.matrix['total'][1], helper_engine.matrix['total'][1])

    def test_db_schema_facade_delegates_to_db_helper(self):
        with patch('engine.engine_db.ensure_schema', return_value=None) as helper, \
                patch('engine.psycopg2', create=True) as psycopg2_module:
            psycopg2_module.extras.execute_values = object()
            self.engine._ensure_db()

        helper.assert_called_once()
        self.assertIs(helper.call_args.args[0], self.engine)
        self.assertIn('get_conn', helper.call_args.kwargs)
        self.assertIn('put_conn', helper.call_args.kwargs)
        self.assertIn('execute_values', helper.call_args.kwargs)
        self.assertIn('player_base_id', helper.call_args.kwargs)
        self.assertIn('build_initial_matrix', helper.call_args.kwargs)

    def test_db_load_facades_delegate_to_db_helper(self):
        with patch('engine.engine_db.load_fetishes', return_value=[{'id': 1}]) as helper:
            self.assertEqual(self.engine._load_fetishes_from_db(), [{'id': 1}])
        helper.assert_called_once()
        self.assertIn('get_conn', helper.call_args.kwargs)
        self.assertIn('put_conn', helper.call_args.kwargs)

        matrix = {'yes': [[1.0]], 'total': [[2.0]]}
        with patch('engine.engine_db.load_matrix', return_value=matrix) as helper:
            self.assertIs(self.engine._load_from_db(), matrix)
        helper.assert_called_once_with(
            self.engine.fetishes,
            self.engine.questions,
            get_conn=helper.call_args.kwargs['get_conn'],
            put_conn=helper.call_args.kwargs['put_conn'],
        )

    def test_config_persistence_facades_delegate_to_db_helper(self):
        loaded = {'guess_threshold': 0.7}
        with patch('engine.engine_db.load_config', return_value=loaded) as helper:
            self.assertIs(self.engine._load_config(), loaded)
        helper.assert_called_once()
        self.assertIn('use_db', helper.call_args.kwargs)
        self.assertIn('read_json', helper.call_args.kwargs)

        with patch('engine.engine_db.save_config_value', return_value=None) as helper:
            self.engine.set_config('guess_threshold', '0.66')
        self.assertEqual(self.engine.config['guess_threshold'], 0.66)
        helper.assert_called_once()
        self.assertEqual(helper.call_args.args[:2], ('guess_threshold', 0.66))
        self.assertIn('atomic_write', helper.call_args.kwargs)

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


class TestEngineRuntimeCacheContract(unittest.TestCase):
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

    def test_disc_scale_facade_owns_cache_and_reuses_within_ttl(self):
        calls = []

        def fake_probability(fetish_idx, question_idx):
            calls.append((fetish_idx, question_idx))
            return 0.9 if question_idx == 0 else 0.5

        with patch.object(self.engine, '_prob', side_effect=fake_probability), \
                patch('engine.time.monotonic', side_effect=[100.0, 101.0]):
            first = self.engine._get_disc_scales()
            second = self.engine._get_disc_scales()

        self.assertIs(first, second)
        self.assertEqual(self.engine._disc_cache, first)
        self.assertEqual(self.engine._disc_cache_time, 100.0)
        self.assertEqual(len(calls), len(self.engine.fetishes) * len(self.engine.questions))

    def test_dynamic_prior_facade_owns_cache_and_empty_log_timestamp(self):
        with patch.object(self.engine, 'get_fetish_log', return_value={}) as get_log, \
                patch('engine.time.monotonic', side_effect=[200.0, 201.0]):
            first = self.engine._get_dynamic_prior_weights()
            second = self.engine._get_dynamic_prior_weights()

        self.assertIs(first, second)
        self.assertEqual(first, {})
        self.assertEqual(self.engine._dynamic_prior_time, 200.0)
        get_log.assert_called_once_with()

    def test_dynamic_prior_facade_updates_cache_from_log(self):
        target_id = self.engine.fetishes[0]['id']
        with patch.object(self.engine, 'get_fetish_log', return_value={target_id: {'guessed': 10, 'correct': 8}}), \
                patch('engine.time.monotonic', return_value=300.0):
            weights = self.engine._get_dynamic_prior_weights()

        self.assertIs(self.engine._dynamic_prior_cache, weights)
        self.assertEqual(self.engine._dynamic_prior_time, 300.0)
        self.assertIn(target_id, weights)
        self.assertGreaterEqual(weights[target_id], 0.1)
