import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

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
                'schema_version': 2,
                'release': 'dev',
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

    def test_postgres_and_jsonl_store_the_same_versioned_payload(self):
        now_fn = lambda: datetime(2026, 8, 9, tzinfo=timezone.utc)
        stored = []
        with (
            patch.object(gameplay_events.event_store, 'enabled', return_value=True),
            patch.object(
                gameplay_events.event_store,
                'record_event',
                side_effect=lambda event_type, event, **kwargs: stored.append((event_type, event, kwargs)) or event,
            ),
        ):
            postgres_event = gameplay_events.record_event(
                'result_shown',
                result_id=3,
                answered_count=8,
                now_fn=now_fn,
                environ={'RELEASE_VERSION': 'release-a'},
            )

        with tempfile.TemporaryDirectory() as tmp:
            json_event = gameplay_events.record_event(
                'result_shown',
                result_id=3,
                answered_count=8,
                now_fn=now_fn,
                environ={'ANALYTICS_EVENT_STORAGE': 'jsonl', 'RELEASE_VERSION': 'release-a'},
                path=os.path.join(tmp, 'gameplay.jsonl'),
            )

        self.assertEqual(postgres_event, json_event)
        self.assertEqual(stored[0][0], 'gameplay')
        self.assertEqual(stored[0][2]['retention_days'], gameplay_events.POSTGRES_RETENTION_DAYS)

    def test_report_exposes_the_active_jsonl_retention_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'gameplay.jsonl')
            gameplay_events.record_event('diagnosis_started', path=path)
            report = gameplay_events.event_report(path=path)

        self.assertEqual(report['storage']['retention']['mode'], 'size_rotation')
        self.assertEqual(report['storage']['retention']['generations'], 2)

    def test_report_exposes_goal_metrics_with_explicit_denominators(self):
        events = [
            gameplay_events.build_event(
                'diagnosis_summary',
                summary_status='completed',
                retry_kind='retry',
                result_reached=True,
                continued=True,
                feedback_outcome='yes',
                answered_count=10,
                work_impressions=2,
                work_clicks=1,
                question_repeats=1,
            ),
            gameplay_events.build_event(
                'diagnosis_summary',
                summary_status='completed',
                retry_kind='exclude_retry',
                result_reached=True,
                answered_count=10,
            ),
        ]

        report = gameplay_events.event_report(events=events)

        self.assertEqual(report['metrics']['retry_rate'], 50.0)
        self.assertEqual(report['metrics']['exclude_retry_rate'], 50.0)
        self.assertEqual(report['metrics']['continue_rate'], 50.0)
        self.assertEqual(report['metrics']['feedback_completion_rate'], 50.0)
        self.assertEqual(report['metrics']['work_click_rate'], 50.0)
        self.assertEqual(report['metrics']['question_repeat_rate'], 5.0)
        self.assertTrue(report['invariants']['valid'])

    def test_report_keeps_release_denominators_separate(self):
        events = [
            gameplay_events.build_event(
                'diagnosis_summary',
                summary_status='completed',
                result_reached=True,
                feedback_outcome='yes',
                release='release-a',
            ),
            gameplay_events.build_event(
                'diagnosis_summary',
                summary_status='abandoned',
                result_reached=False,
                release='release-b',
            ),
        ]

        report = gameplay_events.event_report(events=events)

        self.assertEqual(report['by_release']['release-a']['summary_total'], 1)
        self.assertEqual(report['by_release']['release-a']['result_reach_rate'], 100.0)
        self.assertEqual(report['by_release']['release-b']['summary_total'], 1)
        self.assertEqual(report['by_release']['release-b']['result_reach_rate'], 0.0)
        self.assertTrue(report['by_release']['release-a']['invariants']['valid'])

    def test_release_identifier_accepts_dotted_versions(self):
        event = gameplay_events.build_event('diagnosis_started', release='2026.08.09')

        self.assertEqual(event['release'], '2026.08.09')

    def test_release_invariants_cannot_be_hidden_by_another_release(self):
        events = [
            gameplay_events.build_event(
                'diagnosis_summary',
                summary_status='completed',
                result_reached=False,
                feedback_outcome='yes',
                release='release-a',
            ),
            gameplay_events.build_event(
                'diagnosis_summary',
                summary_status='completed',
                result_reached=True,
                release='release-b',
            ),
        ]

        report = gameplay_events.event_report(events=events)

        self.assertTrue(report['invariants']['valid'])
        self.assertFalse(report['by_release']['release-a']['invariants']['valid'])
        self.assertEqual(
            report['by_release']['release-a']['invariants']['violations'],
            ['feedback_without_result'],
        )

    def test_summary_lifecycle_has_no_player_identifier_and_is_finalized_once(self):
        session = {}
        recorded = []
        gameplay_events.begin_summary(session, retry_kind='new')
        gameplay_events.update_summary(session, 'result_shown', result_id=3, answered_count=12)
        gameplay_events.update_summary(session, 'feedback_completed', outcome='maybe', correction_count=1)
        gameplay_events.update_summary(session, 'work_impression')
        gameplay_events.update_summary(session, 'work_click')

        def record(event_name, **fields):
            recorded.append(gameplay_events.build_event(event_name, **fields))
            return recorded[-1]

        first = gameplay_events.finalize_summary(session, 'completed', record)
        second = gameplay_events.finalize_summary(session, 'completed', record)

        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertEqual(first['feedback_outcome'], 'maybe')
        self.assertEqual(first['correction_count'], 1)
        self.assertEqual(first['work_clicks'], 1)
        self.assertFalse({'session_id', 'run_id', 'ip', 'user_agent'} & set(first))

    def test_report_separates_legacy_events_and_detects_invalid_summary(self):
        invalid = gameplay_events.build_event(
            'diagnosis_summary',
            summary_status='completed',
            result_reached=False,
            feedback_outcome='yes',
            work_impressions=0,
            work_clicks=1,
        )
        report = gameplay_events.event_report(events=[{'timestamp': 'old', 'event_name': 'result_shown'}, invalid])

        self.assertEqual(report['legacy']['total'], 1)
        self.assertFalse(report['legacy']['metrics_trusted'])
        self.assertFalse(report['invariants']['valid'])
        self.assertEqual(
            report['invariants']['violations'],
            ['feedback_without_result', 'work_clicks_exceed_impressions'],
        )


if __name__ == '__main__':
    unittest.main()
