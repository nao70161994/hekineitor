import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import engine_reporting


class TestEngineReportingHelpers(unittest.TestCase):
    def test_recent_fetish_ranking_from_history_sorts_by_total_and_formats_accuracy(self):
        raw = {
            '2026-05-22': {'f_guessed_10': 3, 'f_correct_10': 1, 'f_wrong_20': 2},
            '2026-05-23': {'f_guessed_20': 5, 'f_wrong_10': 1, 'f_correct_20': 2, 'other': 99},
        }
        rows = engine_reporting.recent_fetish_ranking_from_history(
            raw,
            ['2026-05-22', '2026-05-23'],
            {10: 'A', 20: 'B'},
            top_n=2,
        )
        self.assertEqual(rows, [
            {'fetish_id': 20, 'fetish_name': 'B', 'guessed': 5, 'correct': 2, 'wrong': 2, 'feedback_total': 4, 'total': 5, 'acc': 50, 'source': 'recent'},
            {'fetish_id': 10, 'fetish_name': 'A', 'guessed': 3, 'correct': 1, 'wrong': 1, 'feedback_total': 2, 'total': 3, 'acc': 50, 'source': 'recent'},
        ])

    def test_fetish_history_rows_preserve_missing_days(self):
        rows = engine_reporting.fetish_history_rows(
            {'2026-05-23': {'f_correct_10': 2}},
            ['2026-05-22', '2026-05-23'],
            'f_correct_10',
            'f_wrong_10',
        )
        self.assertEqual(rows, [
            {'date': '2026-05-22', 'correct': 0, 'wrong': 0},
            {'date': '2026-05-23', 'correct': 2, 'wrong': 0},
        ])

    def test_quality_event_summary_from_history_matches_engine_shape(self):
        keys = (
            'q_low_conf_guess',
            'q_low_conf_correct',
            'q_low_conf_wrong',
            'q_additional_guess',
            'q_additional_correct',
            'q_additional_wrong',
            'q_additional_question',
        )
        summary = engine_reporting.quality_event_summary_from_history(
            {
                '2026-05-22': {'q_low_conf_guess': 1, 'q_additional_question': 2},
                '2026-05-23': {'q_low_conf_wrong': 3, 'q_additional_correct': 4},
            },
            ['2026-05-22', '2026-05-23'],
            keys,
            days=2,
        )
        self.assertEqual(summary, {
            'days': 2,
            'low_confidence': {'guesses': 1, 'correct': 0, 'wrong': 3},
            'additional_questions': {'guesses': 0, 'correct': 4, 'wrong': 0, 'questions': 2},
        })

    def test_dropoff_summary_from_history_groups_by_answered_count(self):
        raw = {
            '2026-05-22': {'dropoff': 2, 'dropoff_q_0': 1, 'dropoff_q_3': 1},
            '2026-05-23': {'dropoff': 1, 'dropoff_q_3': 1, 'other': 9},
        }
        totals = engine_reporting.dropoff_totals_from_history(raw, ['2026-05-22', '2026-05-23'])
        self.assertEqual(totals, {'total': 3, 'by_answered': {0: 1, 3: 2}})
        self.assertEqual(
            engine_reporting.format_dropoff_summary(totals, days=2),
            {'days': 2, 'total': 3, 'by_answered': [
                {'answered_count': 3, 'count': 2},
                {'answered_count': 0, 'count': 1},
            ]},
        )
