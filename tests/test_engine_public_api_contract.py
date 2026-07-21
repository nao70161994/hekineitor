import inspect
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import engine

EXPECTED_MODULE_EXPORTS = {
    'Engine',
    'PLAYER_FETISH_BASE_ID',
    'FOCUS_THRESHOLD',
    'FOCUS_TOP_N',
    'UCB_EXPLORE_C',
    'EARLY_RANDOM_DEPTH',
    'EARLY_RANDOM_TOP_K',
    'AXIS_INDIRECT_BONUS',
    'PSEUDO',
    'QUESTION_AXES',
    'DOMAIN_PRIORS',
    'FETISH_RELATIONS',
    'FETISH_PRIOR_WEIGHTS',
    'get_compound_works',
    'list_compound_works',
    'set_compound_works',
    'delete_compound_works',
    'parse_works_list',
}

EXPECTED_PUBLIC_METHOD_SIGNATURES = {
    'increment_start_count': '(self)',
    'increment_play_count': '(self)',
    'log_dropoff': '(self, answered_count)',
    'get_stats': '(self)',
    'get_stats_history': '(self, days=30)',
    'get_dropoff_summary': '(self, days=7, top_n=8)',
    'get_recent_fetish_ranking': '(self, days=7, top_n=10, end_date=None)',
    'get_fetish_history': '(self, fetish_db_id, days=30)',
    'promoted_stats_history_repair_report': '(self, mappings)',
    'repair_promoted_stats_history': '(self, mappings)',
    'get_quality_event_summary': '(self, days=30)',
    'toggle_question_disabled': '(self, q_id)',
    'log_guessed': '(self, fetish_db_id)',
    'log_correct': '(self, fetish_db_id)',
    'log_wrong': '(self, fetish_db_id)',
    'get_fetish_log': '(self)',
    'set_config': '(self, key, value)',
    'get_top_questions_per_fetish': '(self, top_n=5)',
    'posteriors': '(self, answers)',
    'best_question': '(self, answers, asked, idk_streak=0)',
    'best_disambiguating_question': '(self, answers, asked, candidate_count=3, idk_streak=0)',
    'get_matrix_heatmap': '(self, n_fetishes=20, n_questions=20)',
    'get_learning_stats': '(self)',
    'get_question_stats': '(self)',
    'get_axis_stats': '(self)',
    'fetish_similarity': '(self, id_a, id_b)',
    'get_correlation_stats': '(self, top_n=30)',
    'get_quality_report': '(self)',
    'top_guess': '(self, answers, n=1)',
    'get_answer_contributions': '(self, answers, fetish_idx, top_n=3)',
    'detect_contradictions': '(self, answers)',
    'learn': '(self, answers, fetish_idx, strength_factor=1.0)',
    'learn_cooccurrence': '(self, answers, idx_a, idx_b, factor=0.25)',
    'learn_near_miss': '(self, answers, fetish_idx, strength_factor=1.0)',
    'learn_negative': '(self, answers, fetish_idx, strength_factor=1.0)',
    'add_fetish': '(self, name, desc, answers)',
    'restore_player_fetishes': '(self, exported_fetishes)',
    'restore_matrix_snapshot': '(self, exported_fetishes, matrix_rows, *, work_catalog=None)',
    'boost_learn_new': '(self, fetish_idx, answers)',
    'index_of': '(self, db_id)',
    'merge_fetishes': '(self, id_keep, id_remove, new_name=None, new_desc=None)',
    'edit_question': '(self, q_idx, text)',
    'validate_matrix_rows': '(self, matrix_rows: list) -> dict',
    'import_matrix': '(self, matrix_rows: list) -> int',
    'edit_fetish': '(self, fetish_id, name=None, desc=None, works=None)',
    'delete_fetish': '(self, fetish_id)',
    'promote_fetish': '(self, old_id)',
    'capture_learned_priors': '(self)',
    'get_related': '(self, fetish_id)',
    'get_recommended_works': '(self, fetish_id)',
    'get_compound_recommended_works': '(self, id_a, id_b)',
    'list_compound_work_rows': '(self)',
    'set_compound_work_rows': '(self, id_a, id_b, works)',
    'delete_compound_work_rows': '(self, id_a, id_b)',
}

EXPECTED_STATE_ATTRIBUTES = {
    'questions',
    'fetishes',
    'matrix',
    'config',
    '_lock',
    '_disc_cache',
    '_disc_cache_time',
    '_corr_cache',
    '_corr_cache_time',
}


class TestEnginePublicApiContract(unittest.TestCase):
    def setUp(self):
        self._patches = [
            patch.object(engine.Engine, '_save_matrix_file', return_value=None),
            patch.object(engine.Engine, '_save_fetishes_file', return_value=None),
            patch.object(engine.Engine, '_save_to_db', return_value=None),
            patch.object(engine.Engine, '_load_matrix_file', new=lambda self: self._init_matrix_file()),
        ]
        for patcher in self._patches:
            patcher.start()

    def tearDown(self):
        for patcher in self._patches:
            patcher.stop()

    def test_module_exports_stay_import_compatible(self):
        missing = sorted(name for name in EXPECTED_MODULE_EXPORTS if not hasattr(engine, name))
        self.assertEqual(missing, [])
        self.assertIs(engine.Engine, engine.__dict__['Engine'])
        self.assertIsInstance(engine.QUESTION_AXES, list)
        self.assertIsInstance(engine.DOMAIN_PRIORS, list)
        self.assertIsInstance(engine.FETISH_RELATIONS, dict)
        self.assertIsInstance(engine.FETISH_PRIOR_WEIGHTS, dict)

    def test_engine_public_method_signatures_stay_stable(self):
        for name, expected in EXPECTED_PUBLIC_METHOD_SIGNATURES.items():
            with self.subTest(name=name):
                self.assertTrue(hasattr(engine.Engine, name), name)
                self.assertEqual(str(inspect.signature(getattr(engine.Engine, name))), expected)

    def test_no_untracked_public_engine_methods_are_added_silently(self):
        actual = {
            name
            for name, member in inspect.getmembers(engine.Engine, predicate=inspect.isfunction)
            if not name.startswith('_')
        }
        self.assertEqual(actual, set(EXPECTED_PUBLIC_METHOD_SIGNATURES))

    def test_engine_initial_state_shape_stays_stable(self):
        instance = engine.Engine()
        missing = sorted(name for name in EXPECTED_STATE_ATTRIBUTES if not hasattr(instance, name))
        self.assertEqual(missing, [])
        self.assertIsInstance(instance.questions, list)
        self.assertIsInstance(instance.fetishes, list)
        self.assertIsInstance(instance.matrix, dict)
        self.assertEqual(set(instance.matrix), {'yes', 'total'})
        self.assertEqual(len(instance.matrix['yes']), len(instance.fetishes))
        self.assertEqual(len(instance.matrix['total']), len(instance.fetishes))
        self.assertIsInstance(instance.config, dict)

    def test_config_unknown_key_contract_remains_value_error(self):
        instance = engine.Engine()
        with self.assertRaises(ValueError):
            instance.set_config('__unknown__', 1.0)

    def test_facade_contract_doc_mentions_public_exports_and_methods(self):
        contract_path = os.path.join(os.path.dirname(__file__), '..', 'docs', 'ENGINE_FACADE_CONTRACT.md')
        with open(contract_path, encoding='utf-8') as file_obj:
            contract = file_obj.read()
        missing_exports = sorted(name for name in EXPECTED_MODULE_EXPORTS if name not in contract)
        self.assertEqual(missing_exports, [])
        missing_methods = sorted(name for name in EXPECTED_PUBLIC_METHOD_SIGNATURES if name not in contract)
        self.assertEqual(missing_methods, [])
