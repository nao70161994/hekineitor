import json
import os
import tempfile
import unittest
from datetime import datetime, timezone

from services import gameplay_events


class GameplayEventTests(unittest.TestCase):
    def test_event_contains_only_bounded_product_fields(self):
        event = gameplay_events.build_event(
            'feedback_completed',
            source='feedback',
            outcome='yes',
            result_id='12',
            question_id=4,
            answered_count=99999,
            work_id='wrk_abc',
            edition_id='bad/id',
            now_fn=lambda: datetime(2026, 7, 28, tzinfo=timezone.utc),
        )

        self.assertEqual(
            event,
            {
                'timestamp': '2026-07-28T00:00:00+00:00',
                'event_name': 'feedback_completed',
                'source': 'feedback',
                'outcome': 'yes',
                'result_id': 12,
                'question_id': 4,
                'answered_count': 1000,
                'work_id': 'wrk_abc',
            },
        )
        self.assertFalse({'session_id', 'ip', 'user_agent', 'answer'} & set(event))

    def test_rejects_unknown_names_and_free_form_dimensions(self):
        with self.assertRaisesRegex(ValueError, 'unknown gameplay event'):
            gameplay_events.build_event('arbitrary')
        with self.assertRaisesRegex(ValueError, 'unknown gameplay source'):
            gameplay_events.build_event('result_shown', source='free form')
        with self.assertRaisesRegex(ValueError, 'unknown gameplay outcome'):
            gameplay_events.build_event('result_shown', outcome='free form')

    def test_jsonl_round_trip_and_safe_recorder(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'gameplay.jsonl')
            gameplay_events.record_event('result_shown', result_id=3, answered_count=8, path=path)
            gameplay_events.record_event('retry_started', source='result', path=path)
            with open(path, encoding='utf-8') as source:
                raw = [json.loads(line) for line in source]

            self.assertEqual(raw, gameplay_events.read_events(path=path))
            self.assertEqual(gameplay_events.event_count(path=path), 2)
            self.assertIsNone(gameplay_events.safe_record_event('invalid', path=path))

    def test_report_exposes_goal_metrics_with_explicit_denominators(self):
        events = [
            gameplay_events.build_event('result_shown'),
            gameplay_events.build_event('result_shown'),
            gameplay_events.build_event('retry_started'),
            gameplay_events.build_event('exclude_retry_started'),
            gameplay_events.build_event('continue_started'),
            gameplay_events.build_event('feedback_completed'),
            gameplay_events.build_event('work_impression', work_id='wrk_1'),
            gameplay_events.build_event('work_impression', work_id='wrk_2'),
            gameplay_events.build_event('question_repeated', question_id=4),
        ]

        report = gameplay_events.event_report(events=events, work_clicks=1, questions_shown=10)

        self.assertEqual(report['metrics']['retry_rate'], 50.0)
        self.assertEqual(report['metrics']['exclude_retry_rate'], 50.0)
        self.assertEqual(report['metrics']['continue_rate'], 50.0)
        self.assertEqual(report['metrics']['feedback_completion_rate'], 50.0)
        self.assertEqual(report['metrics']['work_click_rate'], 50.0)
        self.assertEqual(report['metrics']['question_repeat_rate'], 10.0)


if __name__ == '__main__':
    unittest.main()
