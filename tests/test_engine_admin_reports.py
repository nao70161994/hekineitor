import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import engine_admin_reports
from engine import DOMAIN_PRIORS, Engine, PSEUDO, QUESTION_AXES

MATRIX_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'matrix.json')


class TestEngineAdminReports(unittest.TestCase):
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

    def test_learning_stats_uses_public_fetish_id_not_array_index(self):
        self.engine.fetishes[0]['id'] = 9999
        rows = engine_admin_reports.learning_stats(self.engine, domain_priors=DOMAIN_PRIORS, pseudo=PSEUDO)
        row = next(item for item in rows if item['name'] == self.engine.fetishes[0]['name'])
        self.assertEqual(row['id'], 9999)
        self.assertEqual(row['index'], 0)

    def test_admin_report_helpers_match_engine_facade(self):
        self.assertEqual(
            self.engine.get_matrix_heatmap(n_fetishes=3, n_questions=4),
            engine_admin_reports.matrix_heatmap(self.engine, n_fetishes=3, n_questions=4),
        )
        self.assertEqual(
            self.engine.get_learning_stats(),
            engine_admin_reports.learning_stats(self.engine, domain_priors=DOMAIN_PRIORS, pseudo=PSEUDO),
        )
        self.assertEqual(self.engine.get_question_stats(), engine_admin_reports.question_stats(self.engine))
        self.assertEqual(
            self.engine.get_axis_stats(),
            engine_admin_reports.axis_stats(self.engine, question_axes=QUESTION_AXES),
        )
        self.assertEqual(
            self.engine.fetish_similarity(0, 1),
            engine_admin_reports.fetish_similarity(self.engine, 0, 1),
        )

    def test_fetish_similarity_returns_none_for_unknown_ids(self):
        self.assertIsNone(engine_admin_reports.fetish_similarity(self.engine, -1, -2))

    def test_question_stats_include_disabled_and_variant_counts(self):
        self.engine.disabled_questions.add(0)
        self.engine.questions[0]['variants'] = ['alt']
        row = next(item for item in engine_admin_reports.question_stats(self.engine) if item['id'] == 0)
        self.assertTrue(row['disabled'])
        self.assertEqual(row['variants_count'], 1)
