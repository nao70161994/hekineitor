import copy
import unittest
from unittest import mock

from scripts import evaluate_gameplay


def passing_report():
    return {
        'runtime_seconds': 1.0,
        'transcript': {
            'persona_count': 8,
            'accuracy_scored_persona_count': 8,
            'top1_rate': 0.875,
            'top3_rate': 1.0,
            'calibration_brier': 0.5,
            'result_distribution': {'1': 2, '2': 2, '3': 2, '4': 2},
        },
        'adaptive': {
            'top1_rate': 0.75,
            'top3_rate': 0.75,
            'average_questions': 25.0,
            'average_information_gain': 0.01,
            'average_effective_candidate_reduction': 20.0,
            'legacy_no_signal_selected': 0,
            'cold_start_per_persona': 1.0,
            'question_repeats': 0,
            'unknown_answer_rate': 0.0,
            'confidence_stop_leader_changes': 0,
            'stopping_reasons': {'hard_limit': 4, 'stable_leader': 4},
            'scenario_coverage': {
                'standard': 5,
                'idk_heavy': 1,
                'close_candidates': 1,
                'exclude_retry': 1,
            },
            'rows': [{} for _ in range(8)],
        },
        'diversity': {'preserved': True, 'formula_matches': True},
        'question_design': {
            'direct_result_name_mention_count': 0,
            'missing_answer_frame_count': 0,
        },
    }


class GameplayEvaluationTests(unittest.TestCase):
    def test_adaptive_report_keeps_per_question_explanations(self):
        class FakeEngine:
            fetishes = [{'id': 1}, {'id': 2}]
            questions = [{'text': 'indirect'}]
            disabled_questions = set()
            config = {'guess_threshold': 0.99}

            def posteriors(self, answers):
                return [0.8, 0.2] if answers else [0.5, 0.5]

            def index_of(self, fetish_id):
                return fetish_id - 1

        personas = [{'id': 'trace', 'target_result_id': 1, 'answers': {'0': 1.0}}]
        with mock.patch.object(evaluate_gameplay, 'next_question', side_effect=[0, None]):
            with mock.patch.object(
                evaluate_gameplay.question_selection,
                'question_signal_profile',
                return_value={'exact_neutral': False, 'cold_start': False},
            ):
                report = evaluate_gameplay.evaluate_adaptive(FakeEngine(), personas, 1)

        trace = report['rows'][0]['question_trace'][0]
        self.assertEqual(trace['question_id'], 0)
        self.assertIn('information_gain', trace)
        self.assertIn('effective_candidate_reduction', trace)
        self.assertEqual(report['question_metrics'][0]['times_selected'], 1)

    def test_absolute_failure_includes_actual_and_expected_values(self):
        report = passing_report()
        report['transcript']['top1_rate'] = 0.0

        failures = evaluate_gameplay.quality_failures(report, evaluate_gameplay.DEFAULT_THRESHOLDS)

        failure = next(item for item in failures if item['check'] == 'transcript_top1_rate_min')
        self.assertEqual(failure['actual'], 0.0)
        self.assertEqual(failure['expected'], '>= 0.25')

    def test_baseline_regression_includes_delta_and_tolerance(self):
        report = passing_report()
        baseline = copy.deepcopy(report)
        baseline['adaptive']['top3_rate'] = 1.0

        failures = evaluate_gameplay.quality_failures(
            report,
            evaluate_gameplay.DEFAULT_THRESHOLDS,
            baseline,
        )

        failure = next(item for item in failures if item['check'] == 'baseline:adaptive.top3_rate')
        self.assertEqual(failure['actual_delta'], -0.25)
        self.assertEqual(failure['tolerance'], 0.125)

    def test_scenario_coverage_failure_names_missing_boundary(self):
        report = passing_report()
        report['adaptive']['scenario_coverage'].pop('exclude_retry')

        failures = evaluate_gameplay.quality_failures(report, evaluate_gameplay.DEFAULT_THRESHOLDS)

        failure = next(item for item in failures if item['check'] == 'adaptive_scenario_coverage')
        self.assertIn('exclude_retry', failure['reason'])


if __name__ == '__main__':
    unittest.main()
