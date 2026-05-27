import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import engine_correlation
from engine import Engine



class TestEngineCorrelationHelpers(unittest.TestCase):
    def setUp(self):
        self._patches = [
            patch.object(Engine, '_save_matrix_file', return_value=None),
            patch.object(Engine, '_save_fetishes_file', return_value=None),
            patch.object(Engine, '_save_to_db', return_value=None),
            patch.object(Engine, '_load_matrix_file', new=lambda self: self._init_matrix_file()),
        ]
        for patcher in self._patches:
            patcher.start()
        self.engine = Engine()

    def tearDown(self):
        for patcher in self._patches:
            patcher.stop()

    def test_correlation_helper_matches_facade_and_reuses_cache(self):
        first = self.engine.get_correlation_stats(top_n=5)
        self.assertEqual(
            first,
            engine_correlation.correlation_stats(
                self.engine, top_n=5, now=self.engine._corr_cache_time, ttl=self.engine._CORR_CACHE_TTL
            ),
        )
        self.assertEqual(self.engine.get_correlation_stats(top_n=2), first[:2])

    def test_detect_contradictions_uses_positive_correlations_only(self):
        self.engine.get_correlation_stats = lambda top_n=60: [
            {'q1_id': 0, 'q1_text': 'q0', 'q2_id': 1, 'q2_text': 'q1', 'cos': 0.8},
            {'q1_id': 2, 'q1_text': 'q2', 'q2_id': 3, 'q2_text': 'q3', 'cos': 0.7},
        ]
        self.assertEqual(
            engine_correlation.detect_contradictions(self.engine, {'0': 1, '1': -1, '2': 1, '3': -1}),
            [{'q1': self.engine.questions[0]['text'], 'a1': 1, 'q2': self.engine.questions[1]['text'], 'a2': -1}],
        )
