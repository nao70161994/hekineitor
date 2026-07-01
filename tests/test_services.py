import sys
import os
import json
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import audit
from routes import game as game_routes
from services import admin_context, admin_helpers, admin_security, bootstrap, context, csv_safety, filesystem_context, game_context, seo_context, app_meta, ids, inference, matrix_backups, name_matching, ogp, quality_stats, question_selection, rate_limit, response_hooks, runtime_guards, runtime as runtime_service, share, share_events, question_events, result_exposure, improvement_candidates, event_store, share_links, share_notes, system_context, test_play, works_links


class DummyRequest:
    def __init__(self, json_data=None, headers=None, method='GET', authorization=None):
        self._json_data = json_data
        self.headers = headers or {}
        self.method = method
        self.authorization = authorization

    def get_json(self, silent=True):
        return self._json_data


class DummyAuth:
    def __init__(self, username, password):
        self.username = username
        self.password = password


def dummy_jsonify(payload):
    return payload


def dummy_runtime(**overrides):
    req = overrides.pop('request', DummyRequest())
    req.remote_addr = getattr(req, 'remote_addr', '127.0.0.1')
    return runtime_service.flask_runtime(
        request=req,
        session=overrides.pop('session', {}),
        response_cls=overrides.pop('response_cls', object),
        jsonify=overrides.pop('jsonify', dummy_jsonify),
        app_config=overrides.pop('app_config', {'TESTING': True}),
        environ=overrides.pop('environ', {}),
        buckets=overrides.pop('buckets', {}),
        time_fn=overrides.pop('time_fn', lambda: 100),
    )


class DummyLogEngine:
    fetishes = [
        {'id': 1, 'name': 'OnlyGuessed'},
        {'id': 2, 'name': 'MixedFeedback'},
    ]

    def get_fetish_log(self):
        return {
            1: {'guessed': 10, 'correct': 0, 'wrong': 0},
            2: {'guessed': 10, 'correct': 3, 'wrong': 1},
        }


class TestServices(unittest.TestCase):
    def test_admin_fetish_log_uses_feedback_accuracy_not_guess_count(self):
        rows = admin_helpers.build_fetish_log_rows(DummyLogEngine())
        by_id = {row['id']: row for row in rows}
        self.assertIsNone(by_id[1]['acc'])
        self.assertEqual(by_id[1]['unfeedback'], 10)
        self.assertEqual(by_id[1]['guess_confirm_rate'], 0)
        self.assertEqual(by_id[2]['feedback_total'], 4)
        self.assertEqual(by_id[2]['acc'], 75)
        self.assertEqual(by_id[2]['unfeedback'], 6)
        self.assertEqual(by_id[2]['guess_confirm_rate'], 30)

    def test_admin_read_token_guard_allows_bearer(self):
        req = DummyRequest(headers={'Authorization': 'Bearer token'})
        req.remote_addr = '127.0.0.1'
        runtime = dummy_runtime(request=req, environ={'ADMIN_READ_TOKEN': 'token'})
        self.assertIsNone(runtime.admin_read_guard_response())

    def test_admin_read_token_guard_rejects_mutation_methods(self):
        req = DummyRequest(headers={'Authorization': 'Bearer token'}, method='POST')

        class Response:
            def __init__(self, body, status=200, headers=None):
                self.body = body
                self.status_code = status
                self.headers = headers or {}

        runtime = dummy_runtime(request=req, response_cls=Response, environ={'ADMIN_READ_TOKEN': 'token'})
        response = runtime.admin_read_guard_response()
        self.assertEqual(response.status_code, 403)

    def test_admin_read_token_guard_rejects_missing_token(self):
        req = DummyRequest(headers={'Authorization': 'Bearer token'})
        req.remote_addr = '127.0.0.1'
        class Response:
            def __init__(self, body, status=200, headers=None):
                self.body = body
                self.status_code = status
                self.headers = headers or {}

        runtime = dummy_runtime(request=req, response_cls=Response, environ={})
        response = runtime.admin_read_guard_response()
        self.assertEqual(response.status_code, 503)

    def test_audit_redacts_remote_addr_and_sensitive_detail(self):
        self.assertEqual(audit._redact_remote_addr('203.0.113.42'), '203.0.113.0/24')
        self.assertEqual(audit._sanitize_detail({'token': 'secret', 'nested': {'password': 'x'}}), {
            'token': '[redacted]',
            'nested': {'password': '[redacted]'},
        })

    def test_ogp_cjk_font_status_shape_and_android_candidate(self):
        candidates = list(ogp._ogp_font_candidates())
        self.assertIn('/system/fonts/NotoSansCJK-Regular.ttc', candidates)
        self.assertIn('data/fonts/NotoSansCJKjp-Regular.otf', candidates)
        status = ogp.cjk_font_status()
        self.assertIn('available', status)
        self.assertIn('detail', status)

    def test_ogp_bold_font_prefers_downloaded_cjk_before_latin_bold(self):
        candidates = ogp._ordered_ogp_font_candidates(bold=True)
        self.assertLess(
            candidates.index('data/fonts/NotoSansCJKjp-Regular.otf'),
            candidates.index('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'),
        )

    def test_csv_safety_prefixes_formula_values(self):
        self.assertEqual(csv_safety.safe_csv_cell('=cmd'), "'=cmd")
        self.assertEqual(csv_safety.safe_csv_cell(' +SUM(A1)'), "' +SUM(A1)")
        self.assertEqual(csv_safety.safe_csv_cell('plain'), 'plain')


    def test_improvement_candidates_reports_low_learning_candidates(self):
        rows = [
            {'id': 1, 'name': 'A', 'guessed': 10, 'correct': 2, 'wrong': 1, 'feedback_total': 3},
            {'id': 2, 'name': 'B', 'guessed': 0, 'correct': 0, 'wrong': 0, 'feedback_total': 0},
            {'id': 3, 'name': 'C', 'guessed': 1, 'correct': 0, 'wrong': 0, 'feedback_total': 0},
        ]
        events = [result_exposure.build_event(1, 'A'), result_exposure.build_event(1, 'A')]

        report = improvement_candidates.low_learning_candidates(rows, events, limit=2)

        self.assertEqual(report['status'], 'ok')
        self.assertEqual(report['sample_count'], 2)
        self.assertEqual(report['zero_exposure_count'], 2)
        self.assertEqual(report['zero_feedback_count'], 2)
        self.assertEqual([row['id'] for row in report['least_exposed']], [2, 3])


    def test_improvement_candidates_count_stale_exposure_id_by_current_name(self):
        rows = [
            {'id': 133, 'name': '制服', 'guessed': 10, 'correct': 0, 'wrong': 0, 'feedback_total': 0},
            {'id': 2, 'name': '白衣', 'guessed': 0, 'correct': 0, 'wrong': 0, 'feedback_total': 0},
        ]
        events = [result_exposure.build_event(10000, '制服'), result_exposure.build_event(133, '制服')]

        report = improvement_candidates.low_learning_candidates(rows, events, limit=2)

        self.assertEqual(report['sample_count'], 2)
        exposed = {row['id']: row['exposed'] for row in report['least_exposed']}
        self.assertEqual(exposed[133], 2)
        self.assertEqual(exposed[2], 0)


    def test_event_storage_status_reports_paths_and_writability(self):
        with tempfile.TemporaryDirectory() as tmp:
            share_path = os.path.join(tmp, 'share_events.jsonl')
            question_path = os.path.join(tmp, 'question_events.jsonl')
            share_events.record_event('result_page_view', result_name='NTR', channel='result_page', success=True, path=share_path)
            question_events.record_event('question_shown', question_id=1, path=question_path)

            share_status = share_events.storage_status(path=share_path)
            question_status = question_events.storage_status(path=question_path)

        self.assertEqual(share_status['path'], share_path)
        self.assertEqual(question_status['path'], question_path)
        self.assertTrue(share_status['parent_writable'])
        self.assertTrue(question_status['file_writable'])
        self.assertEqual(share_status['count'], 1)
        self.assertEqual(question_status['count'], 1)


    def test_question_events_report_counts_rates_categories_and_warnings(self):
        class Engine:
            questions = [
                {'text': 'Q0', 'category': 'relation', 'axis': 'abstract'},
                {'text': 'Q1', 'category': 'attachment', 'axis': 'abstract'},
                {'text': 'Q2', 'category': 'world', 'axis': 'abstract'},
            ]

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'question_events.jsonl')
            for _ in range(6):
                question_events.record_event('question_shown', question_id=0, category='relation', path=path)
            for _ in range(4):
                question_events.record_event('question_shown', question_id=1, category='attachment', path=path)
            question_events.record_event('question_answered', question_id=0, answer=1.0, category='relation', path=path)
            question_events.record_event('question_answered', question_id=0, answer=-1.0, category='relation', path=path)
            question_events.record_event('question_answered', question_id=2, answer=1.0, category='world', path=path)
            question_events.record_event('question_dropoff', question_id=0, answered_count=1, category='relation', path=path)
            question_events.record_event('question_result_contribution', question_id=0, result_name='共依存', answer=1.0, path=path)
            report = question_events.event_report(Engine(), path=path)
        self.assertEqual(report['total'], 15)
        self.assertEqual(report['loaded'], 15)
        self.assertEqual(report['total_available'], 15)
        self.assertEqual(report['metrics']['shown'], 10)
        self.assertEqual(report['metrics']['answered'], 3)
        self.assertEqual(report['metrics']['relation_attachment_share'], 90.9)
        q2 = next(row for row in report['questions'] if row['question_id'] == 2)
        self.assertEqual(q2['shown'], 1)
        self.assertEqual(q2['answered'], 1)
        self.assertEqual(report['questions'][0]['yes_rate'], 50.0)
        self.assertEqual(report['contribution_ranking'][0]['top_results'][0]['result_name'], '共依存')
        self.assertEqual(report['warnings'][0]['type'], 'relation_attachment_bias')

    def test_question_events_report_exposes_available_total_when_limited(self):
        class Engine:
            questions = [{'text': 'Q0', 'category': 'relation', 'axis': 'abstract'}]

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'question_events.jsonl')
            for _ in range(3):
                question_events.record_event('question_shown', question_id=0, category='relation', path=path)
            report = question_events.event_report(Engine(), path=path, limit=2)

        self.assertEqual(report['total'], 2)
        self.assertEqual(report['loaded'], 2)
        self.assertEqual(report['limit'], 2)
        self.assertEqual(report['total_available'], 3)

    def test_question_events_report_excludes_suspicious_same_second_burst(self):
        class Engine:
            questions = [{'text': 'Q0', 'category': 'relation', 'axis': 'abstract'}]

        def fixed_now(value):
            return type('Now', (), {
                'astimezone': lambda self, tz: self,
                'isoformat': lambda self, timespec='seconds': value,
            })()

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'question_events.jsonl')
            timestamp = '2026-06-21T00:00:00+00:00'
            question_events.record_event('question_shown', question_id=0, category='relation', path=path, now_fn=lambda: fixed_now(timestamp))
            for _ in range(12):
                question_events.record_event('question_answered', question_id=0, answer=1.0, category='relation', path=path, now_fn=lambda: fixed_now(timestamp))
            report = question_events.event_report(Engine(), path=path)
            unfiltered = question_events.event_report(Engine(), path=path, exclude_suspicious=False)

        self.assertEqual(report['raw_loaded'], 13)
        self.assertEqual(report['total'], 0)
        self.assertEqual(report['quality']['suspicious_timestamp_count'], 1)
        self.assertEqual(report['quality']['excluded_suspicious_events'], 13)
        self.assertEqual(report['warnings'][0]['type'], 'suspicious_question_event_burst')
        self.assertEqual(unfiltered['total'], 13)
        self.assertEqual(unfiltered['quality']['suspicious_event_count'], 13)
        self.assertEqual(unfiltered['quality']['excluded_suspicious_events'], 0)

    def test_question_events_report_filters_by_jst_date(self):
        class Engine:
            questions = [{'text': 'Q0', 'category': 'relation', 'axis': 'abstract'}]

        def fixed_now(value):
            return type('Now', (), {
                'astimezone': lambda self, tz: self,
                'isoformat': lambda self, timespec='seconds': value,
            })()

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'question_events.jsonl')
            question_events.record_event('question_shown', question_id=0, category='relation', path=path, now_fn=lambda: fixed_now('2026-06-20T14:59:00+00:00'))
            question_events.record_event('question_shown', question_id=0, category='relation', path=path, now_fn=lambda: fixed_now('2026-06-20T15:00:00+00:00'))
            question_events.record_event('question_answered', question_id=0, answer=1.0, category='relation', path=path, now_fn=lambda: fixed_now('2026-06-21T14:59:00+00:00'))
            question_events.record_event('question_shown', question_id=0, category='relation', path=path, now_fn=lambda: fixed_now('2026-06-21T15:00:00+00:00'))
            report = question_events.event_report(Engine(), path=path, date='2026-06-21')

        self.assertEqual(report['date'], '2026-06-21')
        self.assertEqual(report['total_available'], 2)
        self.assertEqual(report['metrics']['shown'], 1)
        self.assertEqual(report['metrics']['answered'], 1)

    def test_question_events_report_uses_engine_axis_fallback_when_question_axis_missing(self):
        class Engine:
            questions = [{'text': 'Q0', 'category': 'world'}]

            def _question_axis(self, question_id):
                return 'content' if question_id == 0 else None

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'question_events.jsonl')
            question_events.record_event('question_shown', question_id=0, category='world', path=path)
            report = question_events.event_report(Engine(), path=path)

        self.assertEqual(report['questions'][0]['axis'], 'content')

    def test_game_question_event_records_axis_from_engine_fallback(self):
        events = []

        class Engine:
            questions = [{'text': 'Q0', 'category': 'world'}]

            def _question_axis(self, question_id):
                return 'personality' if question_id == 0 else None

        ctx = type('Ctx', (), {})()
        ctx.engine = Engine()
        ctx.record_question_event = lambda event_name, **kwargs: events.append(question_events.build_event(event_name, **kwargs))

        game_routes._record_question_event(ctx, 'question_shown', 0)

        self.assertEqual(events[0]['axis'], 'personality')

    def test_share_events_csv_escapes_formula_result_names(self):
        report = {'ranking': [{'result_name': '=HYPERLINK("x")', 'total': 1}], 'filters': {}}
        body = share_events.ranking_csv(report)
        self.assertIn("'=HYPERLINK", body)

    def test_share_events_builds_minimal_sanitized_event(self):
        now = type('Now', (), {'astimezone': lambda self, tz: self, 'isoformat': lambda self, timespec='seconds': '2026-05-23T00:00:00+00:00'})()
        event = share_events.build_event(
            'share_button_click',
            result_name='A' * 120,
            channel='button',
            success=True,
            now_fn=lambda: now,
        )
        self.assertEqual(set(event), {'timestamp', 'event_name', 'result_name', 'channel', 'success'})
        self.assertEqual(event['timestamp'], '2026-05-23T00:00:00+00:00')
        self.assertEqual(event['event_name'], 'share_button_click')
        self.assertEqual(len(event['result_name']), 80)
        self.assertEqual(event['channel'], 'button')
        self.assertTrue(event['success'])

    def test_share_events_blanks_sensitive_result_names(self):
        event = share_events.build_event(
            'result_page_view',
            result_name='alice@example.com',
            channel='result_page',
            success=True,
        )
        self.assertEqual(event['result_name'], '')
        token_event = share_events.build_event(
            'ogp_png_view',
            result_name='secret-token-123456789012345678901234567890',
            channel='ogp',
            success=True,
        )
        self.assertEqual(token_event['result_name'], '')

    def test_share_events_read_events_keeps_only_tail_without_full_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'events.jsonl')
            for idx in range(8):
                share_events.record_event('result_page_view', result_name=f'R{idx}', channel='result_page', success=True, path=path)
            events = share_events.read_events(path=path, limit=3)
        self.assertEqual([event['result_name'] for event in events], ['R5', 'R6', 'R7'])

    def test_share_events_report_counts_event_channel_and_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'events.jsonl')
            share_events.record_event('copy_success', result_name='A', channel='clipboard', success=True, path=path)
            share_events.record_event('copy_failure', result_name='A', channel='clipboard', success=False, path=path)
            report = share_events.event_report(path=path, limit=10)
        self.assertEqual(report['total'], 2)
        self.assertEqual(report['by_event']['copy_success'], 1)
        self.assertEqual(report['by_channel']['clipboard'], 2)
        self.assertEqual(report['success']['true'], 1)
        self.assertEqual(report['success']['false'], 1)
        self.assertEqual(report['metrics']['copy_successes'], 1)
        self.assertEqual(report['metrics']['copy_failures'], 1)
        self.assertEqual(report['daily'][0]['copy_successes'], 1)

    def test_share_events_daily_summary_groups_key_metrics(self):
        events = [
            {'timestamp': '2026-05-23T01:00:00+00:00', 'event_name': 'result_page_view'},
            {'timestamp': '2026-05-23T02:00:00+00:00', 'event_name': 'ogp_png_view'},
            {'timestamp': '2026-05-24T01:00:00+00:00', 'event_name': 'x_share_click'},
            {'timestamp': '2026-05-24T02:00:00+00:00', 'event_name': 'web_share_success'},
            {'timestamp': '2026-05-24T03:00:00+00:00', 'event_name': 'copy_success'},
            {'timestamp': '2026-05-24T04:00:00+00:00', 'event_name': 'work_click'},
        ]
        rows = share_events.daily_summary(events, days=7)
        self.assertEqual([row['date'] for row in rows], ['2026-05-23', '2026-05-24'])
        self.assertEqual(rows[0]['result_page_views'], 1)
        self.assertEqual(rows[0]['ogp_views'], 1)
        self.assertEqual(rows[1]['x_clicks'], 1)
        self.assertEqual(rows[1]['web_share_successes'], 1)
        self.assertEqual(rows[1]['copy_successes'], 1)
        self.assertEqual(rows[1]['work_clicks'], 1)

    def test_share_events_filter_and_csv_helpers(self):
        events = [
            {'timestamp': '2026-05-20T00:00:00+00:00', 'result_name': 'Old', 'event_name': 'share_button_click'},
            {'timestamp': '2026-05-23T00:00:00+00:00', 'result_name': 'New', 'event_name': 'result_page_view'},
            {'timestamp': '2026-05-24T00:00:00+00:00', 'result_name': 'New', 'event_name': 'copy_success'},
        ]
        filtered = share_events.filter_events(events, since='2026-05-23', until='2026-05-24')
        self.assertEqual([event['result_name'] for event in filtered], ['New', 'New'])
        recent = share_events.filter_events(events, days=2)
        self.assertEqual([event['result_name'] for event in recent], ['New', 'New'])
        report = {
            'ranking': share_events.result_ranking(filtered),
            'daily': share_events.daily_summary(filtered),
            'filters': {'since': '2026-05-23', 'until': '2026-05-24', 'days': '', 'compare_since': '', 'compare_until': ''},
        }
        ranking_csv = share_events.ranking_csv(report)
        daily_csv = share_events.daily_csv(report)
        self.assertIn('result_name,total,share_button_clicks', ranking_csv.splitlines()[0])
        self.assertIn('New', ranking_csv)
        self.assertIn('filter_since,filter_until', ranking_csv.splitlines()[0])
        self.assertIn('2026-05-23', ranking_csv)
        self.assertIn('date,total,share_button_clicks', daily_csv.splitlines()[0])
        self.assertIn('filter_since,filter_until', daily_csv.splitlines()[0])
        self.assertIn('2026-05-23', daily_csv)

    def test_share_events_comparison_metrics_and_growth(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'events.jsonl')
            old_now = type('Now', (), {'astimezone': lambda self, tz: self, 'isoformat': lambda self, timespec='seconds': '2026-05-20T00:00:00+00:00'})()
            new_now = type('Now', (), {'astimezone': lambda self, tz: self, 'isoformat': lambda self, timespec='seconds': '2026-05-24T00:00:00+00:00'})()
            share_events.record_event('share_button_click', result_name='A', channel='button', success=True, path=path, now_fn=lambda: old_now)
            share_events.record_event('share_button_click', result_name='A', channel='button', success=True, path=path, now_fn=lambda: new_now)
            share_events.record_event('x_share_click', result_name='A', channel='x', success=True, path=path, now_fn=lambda: new_now)
            report = share_events.event_report(
                path=path,
                since='2026-05-24',
                until='2026-05-24',
                compare_since='2026-05-20',
                compare_until='2026-05-20',
            )
        self.assertTrue(report['comparison']['enabled'])
        self.assertEqual(report['comparison']['metrics']['total']['current'], 2)
        self.assertEqual(report['comparison']['metrics']['total']['previous'], 1)
        self.assertEqual(report['comparison']['metrics']['share_actions']['delta'], 1)
        self.assertEqual(report['ranking'][0]['previous_share_actions'], 0)
        self.assertEqual(report['ranking'][0]['share_actions_delta'], 1)
        csv_body = share_events.comparison_csv(report)
        self.assertIn('metric,current,previous,delta,growth_rate', csv_body.splitlines()[0])
        self.assertIn('filter_since,filter_until,compare_since,compare_until', csv_body.splitlines()[0])
        self.assertIn('share_actions', csv_body)

    def test_test_play_flag_helpers_are_session_scoped(self):
        session = {}
        self.assertFalse(test_play.is_learning_disabled(session))
        self.assertFalse(test_play.preserve_flag(session))
        test_play.enable(session)
        self.assertTrue(test_play.is_learning_disabled(session))
        preserved = test_play.preserve_flag(session)
        session.clear()
        test_play.restore_flag(session, preserved)
        self.assertTrue(test_play.is_learning_disabled(session))
        test_play.disable(session)
        self.assertFalse(test_play.is_learning_disabled(session))

    def test_share_notes_save_load_and_delete(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'share_notes.json')
            now = type('Now', (), {
                'astimezone': lambda self, tz: self,
                'isoformat': lambda self, timespec='seconds': '2026-05-24T00:00:00+00:00',
            })()
            saved = share_notes.save_note('NTR', '<script>alert(1)</script>', path=path, now_fn=lambda: now)
            self.assertEqual(saved['note'], '<script>alert(1)</script>')
            self.assertEqual(saved['updated_at'], '2026-05-24T00:00:00+00:00')
            loaded = share_notes.load_notes(path=path)
            self.assertEqual(loaded['NTR']['note'], '<script>alert(1)</script>')
            share_notes.save_note('NTR', '', path=path, now_fn=lambda: now)
            self.assertEqual(share_notes.load_notes(path=path), {})

    def test_share_events_work_clicks_are_ranked_by_work_and_date(self):
        events = [
            {'timestamp': '2026-05-24T00:00:00+00:00', 'event_name': 'work_click', 'result_name': '白衣', 'channel': 'work', 'work_title': '作品A'},
            {'timestamp': '2026-05-24T01:00:00+00:00', 'event_name': 'work_click', 'result_name': '白衣', 'channel': 'work', 'work_title': '作品A'},
            {'timestamp': '2026-05-25T00:00:00+00:00', 'event_name': 'work_click', 'result_name': '眼鏡', 'channel': 'fetish_page', 'work_title': '作品B'},
        ]

        direct = {'metrics': share_events._summary_metrics({'work_click': 3}), 'daily': share_events.daily_summary(events), 'work_ranking': share_events.work_ranking(events)}

        self.assertEqual(direct['metrics']['work_clicks'], 3)
        self.assertEqual(direct['daily'][0]['work_clicks'], 2)
        self.assertEqual(direct['work_ranking'][0]['work_title'], '作品A')
        self.assertEqual(direct['work_ranking'][0]['clicks'], 2)

    def test_share_events_result_ranking_groups_by_result_name(self):
        events = [
            {'result_name': 'A', 'event_name': 'share_button_click'},
            {'result_name': 'A', 'event_name': 'web_share_success'},
            {'result_name': 'A', 'event_name': 'x_share_click'},
            {'result_name': 'A', 'event_name': 'ogp_png_view'},
            {'result_name': 'A', 'event_name': 'result_page_view'},
            {'result_name': 'B', 'event_name': 'result_page_view'},
            {'result_name': 'B', 'event_name': 'web_share_success'},
            {'result_name': '', 'event_name': 'share_button_click'},
        ]
        ranking = share_events.result_ranking(events, limit=10)
        self.assertEqual(ranking[0]['result_name'], 'A')
        self.assertEqual(ranking[0]['share_button_clicks'], 1)
        self.assertEqual(ranking[0]['x_clicks'], 1)
        self.assertEqual(ranking[0]['ogp_views'], 1)
        self.assertEqual(ranking[0]['share_actions'], 2)
        self.assertEqual(ranking[0]['share_successes'], 1)
        self.assertEqual(ranking[0]['ogp_to_result_rate'], 100.0)
        self.assertEqual(ranking[0]['result_to_share_rate'], 100.0)
        self.assertEqual(ranking[0]['share_success_rate'], 100.0)
        self.assertEqual(ranking[1]['result_name'], 'B')
        self.assertEqual(ranking[1]['result_page_views'], 1)
        self.assertEqual(ranking[1]['web_share_successes'], 1)

    def test_share_events_record_event_can_skip_unknown_result_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'share_events.jsonl')
            skipped = share_events.record_event(
                'result_page_view',
                result_name='health',
                channel='result_page',
                success=True,
                path=path,
                allowed_result_names={'白衣'},
            )
            recorded = share_events.record_event(
                'result_page_view',
                result_name='白衣',
                channel='result_page',
                success=True,
                path=path,
                allowed_result_names={'白衣'},
            )
            events = share_events.read_events(path=path, limit=10)

        self.assertIsNone(skipped)
        self.assertEqual(recorded['result_name'], '白衣')
        self.assertEqual([event['result_name'] for event in events], ['白衣'])

    def test_share_events_result_ranking_can_filter_unknown_result_names(self):
        events = [
            {'result_name': '白衣', 'event_name': 'result_page_view'},
            {'result_name': 'health', 'event_name': 'result_page_view'},
            {'result_name': 'abc', 'event_name': 'share_button_click'},
            {'result_name': 'へきネイター', 'event_name': 'ogp_png_view'},
            {'result_name': '白衣', 'event_name': 'work_click', 'work_title': '作品A'},
            {'result_name': 'abc', 'event_name': 'work_click', 'work_title': '作品B'},
        ]

        report = share_events._report_for_events(events, allowed_result_names={'白衣'})

        self.assertEqual([row['result_name'] for row in report['ranking']], ['白衣'])
        self.assertEqual(report['ranking'][0]['total'], 2)
        self.assertEqual([row['work_title'] for row in report['work_ranking']], ['作品A'])

    def test_name_matching_finds_close_names_without_exact_self_match(self):
        fetishes = [
            {'id': 1, 'name': 'ヤンデレ'},
            {'id': 2, 'name': 'ツンデレ'},
            {'id': 3, 'name': 'メガネ'},
        ]
        result = name_matching.find_similar('ヤンデレ系', fetishes)
        self.assertEqual(result[0]['id'], 1)
        exact_results = name_matching.find_similar('ヤンデレ', fetishes)
        self.assertNotIn(1, [item['id'] for item in exact_results])

    def test_app_version_changes_with_file_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'app.py')
            with open(path, 'w', encoding='utf-8') as f:
                f.write('a')
            first = app_meta.app_version(tmp, paths=('app.py',))
            with open(path, 'w', encoding='utf-8') as f:
                f.write('b')
            second = app_meta.app_version(tmp, paths=('app.py',))
        self.assertNotEqual(first, second)

    def test_work_maintenance_summary_reports_quality_counts(self):
        fetishes = [
            {'id': 1, 'name': 'A', 'works': [
                {'title': '重複作品', 'url': 'https://www.amazon.co.jp/dp/B000000000'},
                {'title': '検索作品', 'url': 'https://www.amazon.co.jp/s?k=x'},
            ]},
            {'id': 2, 'name': 'B', 'works': [
                {'title': '重複作品', 'url': 'https://www.amazon.co.jp/dp/B000000001'},
                {'title': 'ASINなし', 'url': 'https://www.amazon.co.jp/gp/product/noasin'},
                'URLなし',
            ]},
        ]

        summary = works_links.build_work_maintenance_summary(
            fetishes,
            work_title_fn=lambda work: work.get('title', '') if isinstance(work, dict) else str(work),
            safe_work_url_fn=lambda url: str(url).startswith('https://www.amazon.co.jp/'),
            sample_limit=5,
        )

        self.assertEqual(summary['total_works'], 5)
        self.assertEqual(summary['direct_url_work_count'], 2)
        self.assertEqual(summary['search_url_work_count'], 1)
        self.assertEqual(summary['missing_asin_work_count'], 1)
        self.assertEqual(summary['missing_url_work_count'], 1)
        self.assertEqual(summary['duplicate_work_title_count'], 1)
        self.assertEqual(summary['duplicate_works'][0]['title'], '重複作品')
        self.assertEqual(summary['duplicate_works'][0]['count'], 2)

    def test_app_version_default_includes_pwa_assets(self):
        self.assertIn('static/icon-192.png', app_meta.APP_VERSION_PATHS)
        self.assertIn('static/icon-512.png', app_meta.APP_VERSION_PATHS)
        self.assertIn('templates/sw.js', app_meta.APP_VERSION_PATHS)

    def test_app_version_default_includes_main_client_assets(self):
        expected = (
            'static/app.css',
            'static/app.js',
            'static/game_flow.js',
            'static/share.js',
            'static/feedback.js',
            'static/teach.js',
            'static/events.js',
        )
        for path in expected:
            self.assertIn(path, app_meta.APP_VERSION_PATHS)

    def test_app_bootstrap_canonicalizes_legacy_adsense_client(self):
        config = bootstrap.app_bootstrap(
            base_dir='/app',
            environ={'ADSENSE_CLIENT': 'ca-pub-8835165458837368'},
            app_version_fn=lambda base_dir: 'version',
        )
        self.assertEqual(config.adsense_client, 'ca-pub-8683516545883768')

    def test_app_bootstrap_groups_static_config(self):
        config = bootstrap.app_bootstrap(
            base_dir='/app',
            environ={'AMAZON_ASSOCIATE_ID': 'assoc'},
            app_version_fn=lambda base_dir: 'version',
        )
        self.assertEqual(config.app_version, 'version')
        self.assertEqual(config.display_version, 'v1.9.2')
        self.assertEqual(config.amazon_associate_id, 'assoc')
        self.assertEqual(config.guess_threshold, 0.75)
        self.assertEqual(config.soft_max_questions, 20)
        self.assertEqual(config.hard_max_questions, 30)
        self.assertEqual(config.max_questions, 20)

    def test_secret_key_requires_value_in_production_env(self):
        with open(os.devnull, 'w') as stderr:
            with self.assertRaises(RuntimeError):
                app_meta.secret_key({'APP_ENV': 'production'}, stderr=stderr)

    def test_secret_key_requires_value_with_database_url(self):
        with open(os.devnull, 'w') as stderr:
            with self.assertRaises(RuntimeError):
                app_meta.secret_key({'DATABASE_URL': 'postgres://db'}, stderr=stderr)

    def test_secret_key_uses_dev_fallback_with_warning(self):
        warnings = []
        with open(os.devnull, 'w') as stderr:
            secret = app_meta.secret_key({}, stderr=stderr, warn_fn=lambda *args, **kwargs: warnings.append(args))
        self.assertEqual(secret, app_meta.DEV_SECRET_KEY)
        self.assertEqual(warnings[0][0], app_meta.SECRET_KEY_MISSING_WARNING)

    def test_secret_key_returns_configured_value(self):
        with open(os.devnull, 'w') as stderr:
            secret = app_meta.secret_key({'SECRET_KEY': 'long_enough_secret'}, stderr=stderr)
        self.assertEqual(secret, 'long_enough_secret')

    def test_confirm_text_accepts_body_or_header(self):
        self.assertEqual(
            admin_security.confirmation_text(DummyRequest(json_data={'confirm_text': 'OK'})),
            'OK',
        )
        self.assertEqual(
            admin_security.confirmation_text(DummyRequest(headers={'X-Confirm-Text': 'HDR'})),
            'HDR',
        )

    def test_csrf_token_reuses_unexpired_token(self):
        session = {'admin_csrf_token': 'token', 'admin_csrf_issued_at': 100}
        token = admin_security.csrf_token(
            session,
            {'ADMIN_CSRF_TTL_SECONDS': '7200'},
            now_fn=lambda: 200,
            token_fn=lambda size: 'new-token',
        )
        self.assertEqual(token, 'token')
        self.assertEqual(session['admin_csrf_token'], 'token')

    def test_csrf_token_refreshes_expired_token(self):
        session = {'admin_csrf_token': 'token', 'admin_csrf_issued_at': 0}
        token = admin_security.csrf_token(
            session,
            {'ADMIN_CSRF_TTL_SECONDS': '1'},
            now_fn=lambda: 100,
            token_fn=lambda size: 'new-token',
        )
        self.assertEqual(token, 'new-token')
        self.assertEqual(session['admin_csrf_issued_at'], 100)

    def test_rate_limit_uses_forwarded_for_only_for_trusted_proxy(self):
        req = DummyRequest(headers={'X-Forwarded-For': '203.0.113.9, 10.0.0.1'})
        req.remote_addr = '127.0.0.1'
        self.assertEqual(
            rate_limit.client_ip(req, {'TRUSTED_PROXY_IPS': '127.0.0.1'}),
            '203.0.113.9',
        )
        self.assertEqual(rate_limit.client_ip(req, {'TRUSTED_PROXY_IPS': ''}), '127.0.0.1')

    def test_rate_limit_returns_retry_after_response(self):
        req = DummyRequest()
        req.remote_addr = '127.0.0.1'
        buckets = {}
        guard = lambda name: True
        first = rate_limit.rate_limit(
            'api_start', 1, req, {}, buckets, dummy_jsonify, guard,
            window_seconds=60, time_fn=lambda: 100,
        )
        second = rate_limit.rate_limit(
            'api_start', 1, req, {}, buckets, dummy_jsonify, guard,
            window_seconds=60, time_fn=lambda: 101,
        )
        self.assertIsNone(first)
        self.assertEqual(second[1], 429)
        self.assertEqual(second[2]['Retry-After'], '59')


    def test_runtime_guards_keep_testing_overrides(self):
        self.assertFalse(runtime_guards.should_enforce({'TESTING': True}, 'other'))
        self.assertFalse(runtime_guards.should_enforce({'TESTING': True}, 'csrf'))
        self.assertTrue(runtime_guards.should_enforce({'TESTING': True, 'ENFORCE_CSRF': True}, 'csrf'))
        self.assertTrue(runtime_guards.should_enforce({'TESTING': True, 'ENFORCE_RATE_LIMIT': True}, 'rate_limit'))
        self.assertTrue(runtime_guards.should_enforce({'TESTING': False}, 'rate_limit'))


    def test_flask_runtime_bundle_exposes_security_and_rate_limit_helpers(self):
        req = DummyRequest(json_data={'confirm_text': 'OK'})
        req.remote_addr = '127.0.0.1'
        req.path = '/api/admin/test'
        req.authorization = DummyAuth('admin', 'pass')
        session = {}
        runtime = runtime_service.flask_runtime(
            request=req,
            session=session,
            response_cls=lambda body, status=200, headers=None: (body, status, headers),
            jsonify=dummy_jsonify,
            app_config={'TESTING': True, 'ENFORCE_RATE_LIMIT': True},
            environ={'ADMIN_PASS': 'pass'},
            buckets={},
            time_fn=lambda: 100,
        )
        self.assertIsNone(runtime.require_confirm('OK'))
        self.assertEqual(runtime.csrf_token(), session['admin_csrf_token'])
        self.assertFalse(runtime.should_enforce_runtime_guard('csrf'))
        self.assertIsNone(runtime.rate_limit('api_start', 1))
        limited = runtime.rate_limit('api_start', 1)
        self.assertEqual(limited[1], 429)
        self.assertIsNone(runtime.admin_guard_response())


    def test_public_base_url_prefers_configured_site_base_url(self):
        request = type('Request', (), {'host_url': 'http://localhost:5000/'})()
        self.assertEqual(
            share.public_base_url({'SITE_BASE_URL': 'https://example.com/'}, request),
            'https://example.com',
        )
        self.assertEqual(share.public_base_url({}, request), 'http://localhost:5000')
        self.assertEqual(
            share.public_base_url({'APP_ENV': 'production', 'SITE_BASE_URL': 'https://prod.example/'}, request),
            'https://prod.example',
        )
        self.assertIn('SITE_BASE_URL', share.public_base_url.__doc__)

    def test_public_base_url_uses_known_origin_in_production_without_site_base_url(self):
        request = type('Request', (), {'host_url': 'https://untrusted.example/'})()
        self.assertEqual(
            share.public_base_url({'APP_ENV': 'production'}, request),
            'https://hekineitor.onrender.com',
        )
        self.assertEqual(
            share.public_base_url({'RENDER': 'true', 'RENDER_EXTERNAL_URL': 'https://public.example/'}, request),
            'https://public.example',
        )


    def test_context_merge_keeps_later_domains_overriding_earlier_values(self):
        first = context.domain(value='old', keep=True)
        second = context.domain(value='new')
        merged = context.build_game_context(first, second, extra='ok')
        self.assertEqual(merged.value, 'new')
        self.assertTrue(merged.keep)
        self.assertEqual(merged.extra, 'ok')


    def test_admin_context_builder_groups_route_dependencies(self):
        class Engine:
            fetishes = []

        class MatrixOps:
            def list_backups(self, limit=50):
                return ['backup']

            def snapshot_current_matrix(self, reason):
                return reason

            def completeness_error(self, report):
                return None

            def expected_rows(self):
                return 0

        ctx = admin_context.build(
            engine=Engine(),
            flask_runtime=dummy_runtime(session={'admin_csrf_token': 'csrf', 'admin_csrf_issued_at': 100}),
            render_template=lambda *args, **kwargs: '',
            recent_audit=lambda limit: [],
            json_dumps=lambda data, **kwargs: str(data),
            perf_counter=lambda: 0,
            work_title=lambda work: str(work),
            safe_work_url=lambda url: url,
            use_db=lambda: False,
            matrix_ops=MatrixOps(),
            cleanup_sessions=lambda: 0,
            player_fetish_base_id=1000,
            strftime=lambda fmt, t: 'now',
            gmtime=lambda: None,
            parse_works_list=lambda raw: raw,
            list_compound_works=lambda: [],
            set_compound_works=lambda a, b, works: 'key',
            delete_compound_works=lambda a, b: True,
            write_audit=lambda *args: None,
            filesystem=filesystem_context.filesystem_context(
                app_dir='/app',
                os_module=type('Os', (), {'path': type('Path', (), {
                    'join': staticmethod(lambda *parts: '/'.join(parts)),
                    'exists': staticmethod(lambda path: True),
                    'getmtime': staticmethod(lambda path: 0),
                    'relpath': staticmethod(lambda path, base: path),
                    'basename': staticmethod(lambda path: path),
                })})(),
                re_module=type('Re', (), {'search': staticmethod(lambda pattern, value: None)})(),
                html_escape=lambda value, quote=True: value,
                data_path=lambda name: name,
                atomic_write_json=lambda path, data, **kwargs: None,
                load_json_file=lambda path, default=None: default,
            ),
            share_event_report=lambda **kwargs: {'total': 0},
            question_event_report=lambda **kwargs: {'total': 0},
            share_event_count=lambda: 0,
            question_event_count=lambda: 0,
            share_event_storage_status=lambda: {'path': '/tmp/share_events.jsonl'},
            question_event_storage_status=lambda: {'path': '/tmp/question_events.jsonl'},
            load_share_notes=lambda: {},
            save_share_note=lambda result_name, note: {'note': note, 'updated_at': 'now'},
            enable_test_play=lambda: None,
            disable_test_play=lambda: None,
            is_test_play=lambda: False,
        )
        self.assertEqual(ctx.csrf_token(), 'csrf')
        self.assertEqual(ctx.list_matrix_import_backups(), ['backup'])
        self.assertEqual(ctx.matrix_import_expected_rows(), 0)
        self.assertEqual(ctx.player_fetish_base_id, 1000)

    def test_system_context_builder_groups_runtime_and_storage_dependencies(self):
        class Engine:
            pass

        ctx = system_context.build(
            engine=Engine(),
            jsonify=dummy_jsonify,
            response_cls=object,
            render_template=lambda *args, **kwargs: '',
            static_folder='/static',
            app_version='abc',
            environ={},
            adsense_client="",
            error_counts={'4xx': 0, '5xx': 0},
            app_started_at=10,
            time_fn=lambda: 15,
            local_session_count=lambda: 2,
            recent_audit=lambda limit: [],
            use_db=lambda: False,
            get_conn=lambda: None,
            put_conn=lambda conn: None,
            filesystem=filesystem_context.filesystem_context(
                app_dir='/app',
                os_module=type('Os', (), {'path': type('Path', (), {
                    'join': staticmethod(lambda *parts: '/'.join(parts)),
                    'exists': staticmethod(lambda path: False),
                    'getmtime': staticmethod(lambda path: 0),
                    'relpath': staticmethod(lambda path, base: path),
                    'basename': staticmethod(lambda path: path),
                })})(),
                re_module=type('Re', (), {'search': staticmethod(lambda pattern, value: None)})(),
                html_escape=lambda value, quote=True: value,
                data_path=lambda name: name,
                atomic_write_json=lambda path, data, **kwargs: None,
                load_json_file=lambda path, default=None: default,
            ),
        )
        self.assertEqual(ctx.static_folder, '/static')
        self.assertEqual(ctx.app_version, 'abc')
        self.assertEqual(ctx.local_session_count(), 2)
        self.assertEqual(ctx.app_dir, '/app')


    def test_game_context_builder_groups_game_dependencies(self):
        class Engine:
            fetishes = [{'id': 7, 'name': 'A', 'desc': '', 'works': []}]
            questions = [{'text': 'Q'}]
            config = {}

            def best_question(self, answers, asked, *, idk_streak=0):
                return 0

            def best_disambiguating_question(self, answers, asked, *, candidate_count=3, idk_streak=0):
                return 0

            def posteriors(self, answers):
                return [0.9]

            def increment_play_count(self):
                pass

            def get_related(self, source_db_id):
                return []

            def get_answer_contributions(self, answers, fetish_idx):
                return []

            def log_guessed(self, fetish_id):
                pass

        ctx = game_context.build(
            engine=Engine(),
            flask_runtime=dummy_runtime(),
            random_choice=lambda values: values[0],
            logger=type('Logger', (), {'exception': lambda self, message: None})(),
            player_fetish_base_id=1000,
            soft_max_questions=20,
            hard_max_questions=30,
            guess_threshold=0.75,
            focus_threshold=0.5,
            work_title=lambda work: str(work),
            get_compound_works=lambda a, b: [],
            record_share_event=lambda *args, **kwargs: None,
            record_question_event=lambda *args, **kwargs: None,
            preserve_test_play_flag=lambda: False,
            restore_test_play_flag=lambda enabled: None,
            learning_disabled=lambda: False,
        )
        self.assertEqual(ctx.question_total_for_count(20), 30)
        self.assertEqual(ctx.select_next_question({}, [], idk_streak=0), 0)
        self.assertEqual(ctx.parse_id_list(['1', 'bad']), {1})
        self.assertEqual(ctx.player_fetish_base_id, 1000)


    def test_seo_context_builder_groups_share_and_ogp_dependencies(self):
        ctx = seo_context.build(
            engine=object(),
            request=DummyRequest(),
            response_cls=object,
            render_template=lambda *args, **kwargs: '',
            public_base_url=lambda: 'https://example.com',
            work_title=lambda work: str(work),
            player_fetish_base_id=1000,
            display_version='v-test',
            app_version='asset-version',
            safe_work_url=lambda url: url,
            amazon_associate_id='assoc',
            fetish_relations={1: [2]},
            error_page='error',
            record_share_event=lambda *args, **kwargs: None,
            learning_disabled=lambda: False,
        )
        self.assertEqual(ctx.public_base_url(), 'https://example.com')
        self.assertEqual(ctx.clean_probability('88.0'), '88')
        self.assertIn("あなたの『癖』は……", ctx.result_share_text('A', '88'))
        self.assertEqual(ctx.result_title('88'), "あなたの『癖』は……")
        self.assertEqual(ctx.result_rarity('88'), 'AI観測ログ')
        self.assertEqual(ctx.player_fetish_base_id, 1000)
        self.assertEqual(ctx.fetish_relations, {1: [2]})


    def test_response_hooks_set_security_headers_and_count_errors(self):
        class Response:
            status_code = 404
            headers = {}

        counts = {'4xx': 0, '5xx': 0}
        response_hooks.record_status_counts(Response, counts)
        response_hooks.apply_security_headers(Response, type('Request', (), {'path': '/'})())
        self.assertEqual(counts['4xx'], 1)
        self.assertEqual(Response.headers['X-Content-Type-Options'], 'nosniff')
        csp = Response.headers['Content-Security-Policy']
        self.assertIn("default-src 'self'", csp)
        self.assertIn('https://pagead2.googlesyndication.com', csp)
        self.assertIn('https://ep1.adtrafficquality.google', csp)
        self.assertIn('https://ep2.adtrafficquality.google', csp)
        self.assertIn('https://googleads.g.doubleclick.net', csp)
        self.assertIn('https://www.google.com', csp)

    def test_response_hooks_audit_admin_mutations_only(self):
        calls = []
        req = DummyRequest(method='POST')
        req.path = '/api/admin/cleanup_sessions'
        response = type('Response', (), {'status_code': 200})()
        response_hooks.write_admin_audit(
            response, req, lambda *args: calls.append(args),
        )
        self.assertEqual(calls[0][0], 'admin_api')
        self.assertEqual(calls[0][1], 'ok')

        calls.clear()
        req.path = '/api/admin/import_matrix'
        response_hooks.write_admin_audit(response, req, lambda *args: calls.append(args))
        self.assertEqual(calls, [])


    def test_matrix_backup_completeness_error_shape(self):
        result = matrix_backups.completeness_error(
            {'skipped_rows': 0, 'valid_rows': 1},
            2,
            dummy_jsonify,
        )
        self.assertEqual(result[1], 400)
        self.assertEqual(result[0]['expected_rows'], 2)

    def test_matrix_backup_prune_keeps_configured_count(self):
        removed = []

        class DummyPath:
            @staticmethod
            def join(*parts):
                return '/'.join(parts)

        class DummyOs:
            path = DummyPath

            @staticmethod
            def remove(path):
                removed.append(path)

        matrix_backups.prune_backups(
            environ={'MATRIX_IMPORT_BACKUP_KEEP': '2'},
            data_path=lambda name: name,
            os_module=DummyOs,
            list_fn=lambda limit=None: [{'name': f'b{i}.json'} for i in range(4)],
        )
        self.assertEqual(removed, ['matrix_import_backups/b2.json', 'matrix_import_backups/b3.json'])


    def test_filesystem_context_exposes_storage_and_path_helpers(self):
        class DummyPath:
            @staticmethod
            def join(*parts):
                return '/'.join(parts)

            @staticmethod
            def exists(path):
                return path == 'exists'

            @staticmethod
            def getmtime(path):
                return 123

            @staticmethod
            def relpath(path, base):
                return path.replace(base + '/', '')

            @staticmethod
            def basename(path):
                return path.split('/')[-1]

        class DummyOs:
            path = DummyPath

        class DummyRe:
            @staticmethod
            def search(pattern, value):
                return None

        fs = filesystem_context.filesystem_context(
            app_dir='/app',
            os_module=DummyOs,
            re_module=DummyRe,
            html_escape=lambda value, quote=True: value,
            data_path=lambda name: f'data/{name}',
            atomic_write_json=lambda path, data, **kwargs: None,
            load_json_file=lambda path, default=None: default,
        )
        self.assertEqual(fs.join_path('a', 'b'), 'a/b')
        self.assertTrue(fs.path_exists('exists'))
        self.assertEqual(fs.path_getmtime('x'), 123)
        self.assertEqual(fs.relpath('/app/data/x', '/app'), 'data/x')
        self.assertEqual(fs.basename('/app/data/x.json'), 'x.json')
        self.assertEqual(fs.data_path('matrix.json'), 'data/matrix.json')


    def test_matrix_backup_operations_bind_dependencies(self):
        class Engine:
            fetishes = [{'id': 1, 'name': 'A'}]
            questions = [{'text': 'Q'}]
            matrix = {'yes': [[0.75]], 'total': [[1.0]]}

        writes = []
        removed = []

        class DummyPath:
            @staticmethod
            def join(*parts):
                return '/'.join(parts)

            @staticmethod
            def isdir(path):
                return True

        class DummyOs:
            path = DummyPath

            @staticmethod
            def makedirs(path, exist_ok=False):
                pass

            @staticmethod
            def listdir(path):
                return ['b0.json', 'b1.json']

            @staticmethod
            def stat(path):
                return type('Stat', (), {'st_mtime': 1, 'st_size': 2})()

            @staticmethod
            def remove(path):
                removed.append(path)

        class DummyTime:
            @staticmethod
            def time():
                return 123

            @staticmethod
            def time_ns():
                return 123000

        ops = matrix_backups.operations(
            engine=Engine(),
            data_path=lambda name: name,
            atomic_write_json=lambda path, data, **kwargs: writes.append((path, data)),
            time_module=DummyTime,
            os_module=DummyOs,
            jsonify=dummy_jsonify,
            environ={'MATRIX_IMPORT_BACKUP_KEEP': '1'},
        )
        self.assertEqual(ops.expected_rows(), 1)
        path = ops.snapshot_current_matrix('test')
        self.assertEqual(path, 'matrix_import_backups/matrix_before_123000.json')
        self.assertEqual(writes[0][1]['matrix_rows'][0]['fetish_id'], 1)
        self.assertEqual(removed, ['matrix_import_backups/b0.json'])
        self.assertIsNone(ops.completeness_error({'skipped_rows': 0, 'valid_rows': 1}))
        self.assertEqual(ops.completeness_error({'skipped_rows': 0, 'valid_rows': 0})[1], 400)


    def test_matrix_backup_operations_use_time_ns_for_unique_snapshot_names(self):
        class Engine:
            fetishes = [{'id': 1, 'name': 'A'}]
            questions = [{'text': 'Q'}]
            matrix = {'yes': [[0.75]], 'total': [[1.0]]}

        writes = []

        class DummyPath:
            @staticmethod
            def join(*parts):
                return '/'.join(parts)

            @staticmethod
            def isdir(path):
                return False

        class DummyOs:
            path = DummyPath

            @staticmethod
            def makedirs(path, exist_ok=False):
                pass

        class DummyTime:
            values = iter([1234000000000, 1234000000001])

            @staticmethod
            def time():
                return 1234

            @staticmethod
            def time_ns():
                return next(DummyTime.values)

        ops = matrix_backups.operations(
            engine=Engine(),
            data_path=lambda name: name,
            atomic_write_json=lambda path, data, **kwargs: writes.append(path),
            time_module=DummyTime,
            os_module=DummyOs,
            jsonify=dummy_jsonify,
            environ={},
        )
        first = ops.snapshot_current_matrix('test')
        second = ops.snapshot_current_matrix('test')
        self.assertNotEqual(first, second)
        self.assertEqual(writes, [first, second])


    def test_quality_stats_records_guess_and_feedback_keys(self):
        calls = []

        class Engine:
            def _record_daily_stat(self, key):
                calls.append(key)

        session = {'low_confidence_extended': True}
        quality_stats.mark_guess_quality(Engine(), session, {str(i): 1 for i in range(22)}, 20)
        self.assertEqual(session['last_guess_quality'], {
            'low_confidence_extended': True,
            'additional_questions': 2,
        })
        self.assertIn('q_low_conf_guess', calls)
        self.assertIn('q_additional_guess', calls)
        self.assertEqual(calls.count('q_additional_question'), 2)

        quality_stats.record_guess_quality_feedback(Engine(), session, correct=False)
        self.assertNotIn('last_guess_quality', session)
        self.assertIn('q_low_conf_wrong', calls)
        self.assertIn('q_additional_wrong', calls)


    def test_quality_feedback_recorder_binds_engine_and_session(self):
        calls = []

        class Engine:
            def _record_daily_stat(self, key):
                calls.append(key)

        session = {'last_guess_quality': {'low_confidence_extended': True, 'additional_questions': 0}}
        recorder = quality_stats.make_guess_quality_feedback_recorder(Engine(), session)
        recorder(True)
        self.assertIn('q_low_conf_correct', calls)
        self.assertNotIn('last_guess_quality', session)


    def test_result_exposure_backfill_plans_from_fetish_log_without_applying(self):
        fetishes = [{'id': 1, 'name': '激重感情'}, {'id': 2, 'name': '白衣'}]
        log = {1: {'guessed': 80}, 2: {'guessed': 20}}

        report = result_exposure.backfill_from_fetish_log(fetishes, log, max_events=10, apply=False)

        self.assertEqual(report['mode'], 'dry_run')
        self.assertEqual(report['raw_total'], 100)
        self.assertEqual(report['planned_total'], 10)
        by_id = {row['fetish_id']: row for row in report['candidates']}
        self.assertEqual(by_id[1]['backfill_count'], 8)
        self.assertEqual(by_id[2]['backfill_count'], 2)

    def test_result_exposure_backfill_events_are_excluded_from_public_ranking_by_default(self):
        events = [
            result_exposure.build_event(1, '激重感情', source=result_exposure.BACKFILL_SOURCE),
            result_exposure.build_event(2, '白衣'),
        ]

        default_report = result_exposure.ranking_from_events(events)
        included_report = result_exposure.ranking_from_events(events, include_backfill=True)

        self.assertEqual(default_report['total'], 1)
        self.assertEqual(default_report['ranking'][0]['fetish_name'], '白衣')
        self.assertEqual(included_report['total'], 2)

    def test_result_exposure_ranking_counts_displayed_rank_one_results(self):
        events = [
            result_exposure.build_event(1, '激重感情', 91, rank=1),
            result_exposure.build_event(1, '激重感情', 88, rank=1),
            result_exposure.build_event(2, '白衣', 77, rank=1),
            result_exposure.build_event(3, '眼鏡', 55, rank=2),
        ]

        report = result_exposure.ranking_from_events(events, top_n=5)

        self.assertEqual(report['total'], 3)
        self.assertEqual(report['ranking'][0]['fetish_name'], '激重感情')
        self.assertEqual(report['ranking'][0]['count'], 2)
        self.assertEqual(report['ranking'][0]['source'], 'result_exposures')
        self.assertEqual(report['ranking'][1]['fetish_name'], '白衣')

    def test_result_exposure_factors_ignore_top_chart_candidates(self):
        class Engine:
            fetishes = [
                {'id': 1, 'name': '制服'},
                {'id': 2, 'name': '激重感情'},
            ]

        events = [result_exposure.build_event(2, '激重感情', 80, rank=101, source=result_exposure.TOP_CHART_SOURCE) for _ in range(20)]
        events.append(result_exposure.build_event(1, '制服', 90, rank=1))

        factors = result_exposure.exposure_factors(Engine.fetishes, events=events)

        self.assertLess(factors[1], 1.0)
        self.assertGreater(factors[2], 1.0)

    def test_result_exposure_ranking_excludes_top_chart_candidates_by_default(self):
        events = [
            result_exposure.build_event(133, '制服', 91, rank=1),
            result_exposure.build_event(1, '激重感情', 88, rank=101, source=result_exposure.TOP_CHART_SOURCE),
        ]

        default_report = result_exposure.ranking_from_events(events, top_n=5, include_secondary=True)
        candidate_report = result_exposure.ranking_from_events(events, top_n=5, include_secondary=True, include_candidates=True)

        self.assertEqual(default_report['total'], 1)
        self.assertEqual(default_report['ranking'][0]['fetish_name'], '制服')
        self.assertEqual(candidate_report['total'], 2)
        self.assertEqual({row['fetish_name']: row['count'] for row in candidate_report['ranking']}, {'制服': 1, '激重感情': 1})

    def test_result_exposure_ranking_can_count_secondary_displayed_results(self):
        events = [
            result_exposure.build_event(133, '制服', 91, rank=1),
            result_exposure.build_event(1, '激重感情', 88, rank=2),
            result_exposure.build_event(133, '制服', 77, rank=1),
            result_exposure.build_event(1, '激重感情', 55, rank=2),
        ]

        report = result_exposure.ranking_from_events(events, top_n=5, include_secondary=True)

        self.assertEqual(report['total'], 4)
        self.assertEqual({row['fetish_name']: row['count'] for row in report['ranking']}, {'制服': 2, '激重感情': 2})

    def test_result_exposure_ranking_can_normalize_current_fetish_names(self):
        events = [
            result_exposure.build_event(132, '古い名前', 91, rank=1),
            result_exposure.build_event(132, 'さらに古い名前', 88, rank=1),
        ]

        report = result_exposure.ranking_from_events(
            events,
            top_n=5,
            fetish_names={132: '現在の名前'},
        )

        self.assertEqual(report['total'], 2)
        self.assertEqual(report['ranking'][0]['fetish_id'], 132)
        self.assertEqual(report['ranking'][0]['fetish_name'], '現在の名前')
        self.assertEqual(report['ranking'][0]['count'], 2)

    def test_result_exposure_ranking_merges_stale_promoted_id_by_current_name(self):
        events = [
            result_exposure.build_event(10000, '制服', 91, rank=1),
            result_exposure.build_event(133, '制服', 88, rank=1),
            result_exposure.build_event(2, '白衣', 77, rank=1),
        ]

        report = result_exposure.ranking_from_events(
            events,
            top_n=5,
            fetish_names={133: '制服', 2: '白衣'},
        )

        self.assertEqual(report['total'], 3)
        self.assertEqual(report['ranking'][0]['fetish_id'], 133)
        self.assertEqual(report['ranking'][0]['fetish_name'], '制服')
        self.assertEqual(report['ranking'][0]['count'], 2)

    def test_result_exposure_recent_report_returns_safe_tail_events(self):
        events = [
            {
                **result_exposure.build_event(1, '激重感情', 91, rank=1),
                'remote_addr': '203.0.113.1',
                'user_agent': 'secret ua',
                'session_id': 'secret session',
            },
            result_exposure.build_event(2, '白衣', 77, rank=1),
            result_exposure.build_event(3, '眼鏡', 55, rank=2, source=result_exposure.BACKFILL_SOURCE),
        ]

        with patch('services.result_exposure.read_events', return_value=events):
            report = result_exposure.recent_events_report(limit=5, include_backfill=False)

        self.assertEqual(report['status'], 'ok')
        self.assertEqual(len(report['events']), 2)
        self.assertEqual(report['events'][0]['fetish_name'], '白衣')
        self.assertEqual(report['events'][1]['fetish_name'], '激重感情')
        body = json.dumps(report, ensure_ascii=False)
        self.assertNotIn('remote_addr', body)
        self.assertNotIn('user_agent', body)
        self.assertNotIn('session_id', body)

    def test_result_exposure_filter_events_uses_jst_report_date_string(self):
        events = [
            {'timestamp': '2026-05-26T00:00:00+00:00', 'event_name': 'result_exposed', 'fetish_id': 1, 'fetish_name': '共依存'},
            {'timestamp': '2026-05-27T00:00:00+00:00', 'event_name': 'result_exposed', 'fetish_id': 2, 'fetish_name': '白衣'},
        ]

        filtered = result_exposure.filter_events(events, days=1, date='2026-05-27')

        self.assertEqual([event['fetish_name'] for event in filtered], ['白衣'])

    def test_result_exposure_balancing_downweights_overexposed_result(self):
        class Engine:
            fetishes = [
                {'id': 1, 'name': '激重感情'},
                {'id': 2, 'name': '白衣'},
                {'id': 3, 'name': '眼鏡'},
            ]

        events = [result_exposure.build_event(1, '激重感情', 90) for _ in range(80)]
        events.extend(result_exposure.build_event(2, '白衣', 80) for _ in range(5))
        factors = result_exposure.exposure_factors(Engine.fetishes, events=events)

        self.assertLess(factors[1], 0.35)
        self.assertGreater(factors[2], 1.0)
        self.assertGreater(factors[3], factors[2])



    def test_result_exposure_balancing_counts_stale_id_by_current_name(self):
        class Engine:
            fetishes = [
                {'id': 133, 'name': '制服'},
                {'id': 2, 'name': '白衣'},
                {'id': 3, 'name': '眼鏡'},
            ]

        events = [result_exposure.build_event(10000, '制服', 90) for _ in range(80)]
        events.extend(result_exposure.build_event(2, '白衣', 80) for _ in range(5))
        factors = result_exposure.exposure_factors(Engine.fetishes, events=events)

        self.assertLess(factors[133], 0.35)
        self.assertGreater(factors[3], 1.0)


    def test_result_exposure_ratio_correction_penalizes_current_spike(self):
        class Engine:
            fetishes = [{'id': index, 'name': f'F{index}'} for index in range(132)] + [
                {'id': 133, 'name': '制服'},
            ]

        events = [result_exposure.build_event(133, '制服', 90) for _ in range(21)]
        events.extend(result_exposure.build_event(index % 132, f'F{index % 132}', 80) for index in range(279))
        factors = result_exposure.exposure_factors(Engine.fetishes, events=events)

        self.assertLess(factors[133], 0.35)
        self.assertGreater(factors[0], factors[133])

    def test_result_exposure_ratio_correction_works_with_small_samples(self):
        class Engine:
            fetishes = [
                {'id': 133, 'name': '制服'},
                {'id': 2, 'name': '白衣'},
                {'id': 3, 'name': '眼鏡'},
            ]

        events = [result_exposure.build_event(133, '制服', 90) for _ in range(5)]
        factors = result_exposure.exposure_factors(Engine.fetishes, events=events)

        self.assertLess(factors[133], 1.0)
        self.assertGreater(factors[2], 1.0)


    def test_result_exposure_reassign_fetish_id_updates_jsonl_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'result_exposures.jsonl')
            result_exposure.record_result(10000, '制服', 90, path=path)
            result_exposure.record_result(2, '白衣', 80, path=path)

            report = result_exposure.reassign_fetish_id(10000, 133, fetish_name='制服', path=path)
            events = result_exposure.read_events(path=path, limit=10)

        self.assertEqual(report['status'], 'ok')
        self.assertEqual(report['updated_count'], 1)
        self.assertEqual(events[0]['fetish_id'], 133)
        self.assertEqual(events[0]['fetish_name'], '制服')
        self.assertEqual(events[1]['fetish_id'], 2)


    def test_result_exposure_factor_report_summarizes_correction_without_raw_events(self):
        class Engine:
            fetishes = [
                {'id': 1, 'name': '激重感情'},
                {'id': 2, 'name': '白衣'},
                {'id': 3, 'name': '眼鏡'},
            ]

        events = [result_exposure.build_event(1, '激重感情', 90) for _ in range(80)]
        events.extend(result_exposure.build_event(2, '白衣', 80) for _ in range(5))
        report = result_exposure.factor_report(Engine.fetishes, events=events, top_n=5)

        self.assertEqual(report['status'], 'ok')
        self.assertEqual(report['sample']['main_total'], 85)
        self.assertTrue(report['sample']['active'])
        self.assertNotIn('candidate_pool', report['config'])
        self.assertNotIn('low_exposure_rescue_limit', report['config'])
        self.assertEqual(report['config']['diversity_alpha'], 3.0)
        self.assertNotIn('min_factor', report['config'])
        self.assertNotIn('max_factor', report['config'])
        self.assertAlmostEqual(report['sample']['expected_per_result'], 85 / 3, places=4)
        heavy = {row['fetish_name']: row for row in report['heavy_results']}
        self.assertLess(heavy['激重感情']['factor'], 0.35)
        self.assertIn('most_downweighted', report)
        self.assertIn('most_boosted', report)
        self.assertNotIn('events', report)

    def test_result_exposure_uses_same_ratio_rule_for_heavy_names(self):
        class Engine:
            fetishes = [
                {'id': 1, 'name': '激重感情'},
                {'id': 2, 'name': '白衣'},
                {'id': 3, 'name': '眼鏡'},
            ]

        events = [result_exposure.build_event(1, '激重感情', 90) for _ in range(8)]
        events.extend(result_exposure.build_event(2, '白衣', 80) for _ in range(52))
        factors = result_exposure.exposure_factors(Engine.fetishes, events=events)

        self.assertGreater(factors[1], 1.0)
        self.assertLess(factors[2], 1.0)

    def test_result_exposure_factors_count_secondary_displayed_results(self):
        class Engine:
            fetishes = [
                {'id': 1, 'name': '激重感情'},
                {'id': 2, 'name': '制服'},
                {'id': 3, 'name': '眼鏡'},
            ]

        events = [result_exposure.build_event(2, '制服', 90, rank=1) for _ in range(8)]
        events.extend(result_exposure.build_event(1, '激重感情', 80, rank=2) for _ in range(8))
        factors = result_exposure.exposure_factors(Engine.fetishes, events=events)

        self.assertLess(factors[1], 1.0)
        self.assertLess(factors[2], 1.0)
        self.assertGreater(factors[3], 1.0)

    def test_result_exposure_hard_quota_blocks_non_dominant_heavy_result(self):
        class Engine:
            fetishes = [
                {'id': 1, 'name': '激重感情'},
                {'id': 2, 'name': '白衣'},
                {'id': 3, 'name': '眼鏡'},
            ]

        events = [result_exposure.build_event(1, '激重感情', 90) for _ in range(80)]
        events.extend(result_exposure.build_event(2, '白衣', 80) for _ in range(5))
        ranked = result_exposure.adjust_ranked(Engine(), [0.95, 0.50, 0.2], [0, 1, 2], events=events)

        self.assertEqual(ranked[0], 1)

    def test_result_exposure_adjustment_can_promote_close_low_exposure_candidate(self):
        class Engine:
            fetishes = [
                {'id': 1, 'name': '激重感情'},
                {'id': 2, 'name': '白衣'},
                {'id': 3, 'name': '眼鏡'},
            ]

        events = [result_exposure.build_event(1, '激重感情', 90) for _ in range(80)]
        events.extend(result_exposure.build_event(2, '白衣', 80) for _ in range(5))
        ranked = result_exposure.adjust_ranked(Engine(), [0.62, 0.58, 0.1], [0, 1, 2], events=events)

        self.assertEqual(ranked[0], 1)


    def test_result_exposure_adjusted_scores_are_clamped_to_probability_range(self):
        class Engine:
            fetishes = [
                {'id': 1, 'name': '未露出'},
                {'id': 2, 'name': '露出済み'},
            ]

        events = [result_exposure.build_event(2, '露出済み') for _ in range(100)]
        scores = result_exposure.adjusted_scores(Engine(), [0.50, 0.10], [0, 1], events=events)

        self.assertLessEqual(scores[0]['adjusted_score'], 1.0)
        self.assertEqual(scores[0]['adjusted_score'], 1.0)
        self.assertGreater(scores[0]['factor'], 1.0)


    def test_result_exposure_adjustment_extends_pool_for_low_exposure_candidates(self):
        class Engine:
            fetishes = [{'id': index + 1, 'name': f'F{index + 1}'} for index in range(60)]

        # Fill enough samples and overexpose the first candidates so later low-exposure
        # candidates receive the positive factor while still being plausible.
        events = []
        for fetish_id in range(1, 21):
            events.extend(result_exposure.build_event(fetish_id, f'F{fetish_id}') for _ in range(5))
        probs = [0.90] + [0.55 - index * 0.003 for index in range(1, 60)]
        ranked = list(range(60))
        ranked[1], ranked[37] = ranked[37], ranked[1]

        adjusted = result_exposure.adjust_ranked(Engine(), probs, ranked, events=events)

        self.assertIn(37, adjusted[:20])
        self.assertLess(adjusted.index(37), adjusted.index(1))

    def test_result_exposure_no_longer_protects_dominant_overexposed_top_result(self):
        class Engine:
            fetishes = [
                {'id': 1, 'name': '激重感情'},
                {'id': 2, 'name': '白衣'},
                {'id': 3, 'name': '眼鏡'},
            ]

        events = [result_exposure.build_event(1, '激重感情', 90) for _ in range(80)]
        events.extend(result_exposure.build_event(2, '白衣', 80) for _ in range(5))
        ranked = result_exposure.adjust_ranked(Engine(), [0.90, 0.58, 0.1], [0, 1, 2], events=events)

        self.assertEqual(ranked[0], 1)


    def test_result_exposure_explores_deeper_low_exposure_candidates_globally(self):
        class Engine:
            fetishes = [{'id': index + 1, 'name': f'F{index + 1}'} for index in range(120)]

        events = [result_exposure.build_event(1, 'F1') for _ in range(100)]
        probs = [0.90] + [0.20 - index * 0.001 for index in range(1, 120)]
        probs[80] = 0.33
        ranked = list(range(120))
        ranked[80], ranked[99] = ranked[99], ranked[80]

        adjusted = result_exposure.adjust_ranked(Engine(), probs, ranked, events=events)

        self.assertEqual(adjusted[0], 80)

    def test_result_exposure_adjustment_scores_every_ranked_candidate(self):
        class Engine:
            fetishes = [{'id': index + 1, 'name': f'F{index + 1}'} for index in range(80)]

        events = []
        for fetish_id in range(1, 50):
            events.extend(result_exposure.build_event(fetish_id, f'F{fetish_id}') for _ in range(3))
        probs = [0.60] + [0.30 - index * 0.001 for index in range(1, 80)]
        probs[70] = 0.28
        ranked = list(range(80))

        adjusted = result_exposure.adjust_ranked(Engine(), probs, ranked, events=events)

        self.assertLess(adjusted.index(70), adjusted.index(1))
        self.assertLess(adjusted.index(70), 25)


    def test_question_selection_low_confidence_extension_bounds(self):
        self.assertFalse(question_selection.should_extend_low_confidence(19, 0.1, 0.09, 0.75, 20, 30))
        self.assertTrue(question_selection.should_extend_low_confidence(20, 0.7, 0.6, 0.75, 20, 30))
        self.assertTrue(question_selection.should_extend_low_confidence(20, 0.8, 0.7, 0.75, 20, 30))
        self.assertFalse(question_selection.should_extend_low_confidence(30, 0.7, 0.6, 0.75, 20, 30))


    def test_question_selection_factories_bind_route_defaults(self):
        total = question_selection.make_question_total_for_count(20, 30)
        extend = question_selection.make_low_confidence_extender(20, 30)
        self.assertEqual(total(19), 20)
        self.assertEqual(total(20), 30)
        self.assertTrue(extend(20, 0.7, 0.6, 0.75))

        class Engine:
            def best_question(self, answers, asked, *, idk_streak=0):
                return ('best', tuple(sorted(asked)), idk_streak)

            def best_disambiguating_question(self, answers, asked, *, candidate_count=3, idk_streak=0):
                return ('disambig', tuple(sorted(asked)), candidate_count, idk_streak)

        selector = question_selection.make_next_question_selector(Engine())
        self.assertEqual(selector({}, [2, 1], idk_streak=1), ('best', (1, 2), 1))
        self.assertEqual(selector({}, [2], idk_streak=3, disambiguate=True), ('disambig', (2,), 3, 3))


    def test_ids_parse_id_list_ignores_invalid_values(self):
        self.assertEqual(ids.parse_id_list(['1', 2, 'bad', None]), {1, 2})
        self.assertEqual(ids.parse_id_list('1,2'), set())


    def test_inference_make_guess_records_side_effects(self):
        calls = []

        class Engine:
            fetishes = [{'id': 7, 'name': 'A', 'desc': '', 'works': []}]
            questions = []
            config = {}

            def increment_play_count(self):
                calls.append('increment')

            def posteriors(self, answers):
                return [0.9]

            def get_related(self, source_db_id):
                return []

            def get_answer_contributions(self, answers, fetish_idx):
                return []

            def log_guessed(self, fetish_id):
                calls.append(('guessed', fetish_id))

        ctx = type('Ctx', (), {})()
        ctx.engine = Engine()
        ctx.session = {}
        ctx.soft_max_questions = 20
        ctx.mark_guess_quality = lambda engine, session, answers, soft: calls.append('quality')
        ctx.inference_context = lambda: type('InferenceCtx', (), {
            'engine': ctx.engine,
            'session': ctx.session,
            'work_title': staticmethod(lambda work: str(work)),
            'get_compound_works': staticmethod(lambda a, b: []),
            'profile_min_ratio': 0.25,
            'profile_min_prob': 0.08,
            'compound_ratio': 0.55,
            'triple_ratio': 0.45,
        })()
        ctx.jsonify = lambda payload: payload

        result = inference.make_guess(ctx, {})
        self.assertEqual(result['fetish_id'], 7)
        self.assertEqual(calls, ['increment', 'quality', ('guessed', 7)])

    def test_inference_result_contribution_events_use_ans_answer(self):
        events = []

        class Engine:
            fetishes = [{'id': 7, 'name': 'A', 'desc': '', 'works': []}]
            questions = [{'text': 'Q0'}]
            config = {}

            def increment_play_count(self):
                pass

            def posteriors(self, answers):
                return [0.9]

            def get_related(self, source_db_id):
                return []

            def get_answer_contributions(self, answers, fetish_idx):
                return [{'q_id': 0, 'text': 'Q0', 'ans': -0.5}]

            def log_guessed(self, fetish_id):
                pass

        ctx = type('Ctx', (), {})()
        ctx.engine = Engine()
        ctx.session = {}
        ctx.soft_max_questions = 20
        ctx.mark_guess_quality = lambda engine, session, answers, soft: None
        ctx.record_question_event = lambda event_name, **kwargs: events.append(question_events.build_event(event_name, **kwargs))
        ctx.inference_context = lambda: type('InferenceCtx', (), {
            'engine': ctx.engine,
            'session': ctx.session,
            'work_title': staticmethod(lambda work: str(work)),
            'get_compound_works': staticmethod(lambda a, b: []),
            'profile_min_ratio': 0.25,
            'profile_min_prob': 0.08,
            'compound_ratio': 0.55,
            'triple_ratio': 0.45,
        })()
        ctx.jsonify = lambda payload: payload

        inference.make_guess(ctx, {'0': -0.5})

        self.assertEqual(events[0]['event_name'], 'question_result_contribution')
        self.assertEqual(events[0]['answer'], -0.5)
        self.assertEqual(events[0]['answer_bucket'], 'no')


    def test_analytics_events_use_postgres_store_when_enabled(self):
        stored = []
        with patch.object(share_events.event_store, 'enabled', return_value=True), \
                patch.object(share_events.event_store, 'record_event', side_effect=lambda event_type, event: stored.append((event_type, event)) or event), \
                patch.object(question_events.event_store, 'enabled', return_value=True), \
                patch.object(question_events.event_store, 'record_event', side_effect=lambda event_type, event: stored.append((event_type, event)) or event), \
                patch.object(result_exposure.event_store, 'enabled', return_value=True), \
                patch.object(result_exposure.event_store, 'record_event', side_effect=lambda event_type, event: stored.append((event_type, event)) or event):
            share_events.record_event('result_page_view', result_name='眼鏡', channel='result_page', success=True)
            question_events.record_event('question_shown', question_id=1, question_text='少人数の方が楽？')
            result_exposure.record_result(7, '白衣', 88, rank=1)

        self.assertEqual([row[0] for row in stored], ['share', 'question', 'result_exposure'])
        self.assertEqual(stored[0][1]['result_name'], '眼鏡')
        self.assertEqual(stored[1][1]['question_id'], 1)
        self.assertEqual(stored[2][1]['fetish_name'], '白衣')

    def test_analytics_events_read_from_postgres_store_when_enabled(self):
        def fake_read(event_type, **kwargs):
            return {
                'share': [{'event_name': 'result_page_view', 'result_name': '眼鏡'}],
                'question': [{'event_name': 'question_shown', 'question_id': 3}],
                'result_exposure': [{'event_name': 'result_exposed', 'fetish_id': 7}],
            }[event_type]

        with patch.object(event_store, 'enabled', return_value=True), \
                patch.object(event_store, 'read_events', side_effect=fake_read):
            self.assertEqual(share_events.read_events(limit=10)[0]['result_name'], '眼鏡')
            self.assertEqual(question_events.read_events(limit=10)[0]['question_id'], 3)
            self.assertEqual(result_exposure.read_events(limit=10)[0]['fetish_id'], 7)

    def test_analytics_storage_status_reports_postgres_without_secrets(self):
        with patch.object(share_events.event_store, 'enabled', return_value=True), \
                patch.object(share_events.event_store, 'storage_status', return_value={'path': 'postgres:analytics_events:share', 'storage': 'postgres', 'count': 2, 'parent_writable': True, 'file_writable': True}):
            status = share_events.storage_status()
        self.assertEqual(status['storage'], 'postgres')
        self.assertEqual(status['count'], 2)
        self.assertNotIn('DATABASE_URL', status['path'])

    def test_inference_make_guess_records_visible_top_chart_candidates(self):
        calls = []

        class Engine:
            fetishes = [
                {'id': 1, 'name': '制服', 'desc': 'uniform', 'works': []},
                {'id': 2, 'name': '激重感情', 'desc': 'heavy', 'works': []},
                {'id': 3, 'name': '白衣', 'desc': 'lab', 'works': []},
            ]
            questions = []
            config = {'compound_ratio': 0.95, 'triple_ratio': 0.9}

            def increment_play_count(self):
                pass

            def posteriors(self, answers):
                return [0.80, 0.50, 0.40]

            def get_related(self, source_db_id):
                return []

            def get_answer_contributions(self, answers, fetish_idx):
                return []

            def log_guessed(self, fetish_id):
                pass

            def index_of(self, fetish_id):
                for index, fetish in enumerate(self.fetishes):
                    if fetish['id'] == fetish_id:
                        return index
                return None

        ctx = type('Ctx', (), {})()
        ctx.engine = Engine()
        ctx.session = {}
        ctx.soft_max_questions = 20
        ctx.mark_guess_quality = lambda engine, session, answers, soft: None
        ctx.record_result_exposure = lambda fetish_id, name, probability, **kwargs: calls.append((fetish_id, name, probability, kwargs))
        ctx.inference_context = lambda: type('InferenceCtx', (), {
            'engine': ctx.engine,
            'session': ctx.session,
            'work_title': staticmethod(lambda work: str(work)),
            'get_compound_works': staticmethod(lambda a, b: []),
            'profile_min_ratio': 0.25,
            'profile_min_prob': 0.08,
            'compound_ratio': 0.95,
            'triple_ratio': 0.9,
        })()
        ctx.jsonify = lambda payload: payload

        result = inference.make_guess(ctx, {})

        self.assertEqual(result['top_chart'][1]['fetish_id'], 2)
        self.assertIn((1, '制服', 80.0, {'rank': 1}), calls)
        self.assertIn((2, '激重感情', 50.0, {'rank': 102, 'source': result_exposure.TOP_CHART_SOURCE}), calls)
        self.assertIn((3, '白衣', 40.0, {'rank': 103, 'source': result_exposure.TOP_CHART_SOURCE}), calls)

    def test_inference_uses_adjusted_scores_for_displayed_candidates(self):
        class Engine:
            fetishes = [
                {'id': 1, 'name': '制服', 'desc': 'uniform', 'works': []},
                {'id': 2, 'name': '白衣', 'desc': 'lab', 'works': []},
                {'id': 3, 'name': '眼鏡', 'desc': 'glasses', 'works': []},
            ]
            questions = []
            config = {'compound_ratio': 0.8, 'triple_ratio': 0.7}

            def posteriors(self, answers):
                return [0.80, 0.50, 0.30]

            def get_related(self, source_db_id):
                return []

            def get_answer_contributions(self, answers, fetish_idx):
                return []

            def index_of(self, fetish_id):
                return None

        ctx = type('Ctx', (), {
            'engine': Engine(),
            'session': {},
            'work_title': staticmethod(lambda work: str(work)),
            'get_compound_works': staticmethod(lambda a, b: []),
            'profile_min_ratio': 0.25,
            'profile_min_prob': 0.08,
            'compound_ratio': 0.8,
            'triple_ratio': 0.7,
            'adjusted_score_provider': staticmethod(lambda probs, ranked: {
                0: {'raw_probability': 0.80, 'factor': 0.2, 'adjusted_score': 0.16},
                1: {'raw_probability': 0.50, 'factor': 1.0, 'adjusted_score': 0.50},
                2: {'raw_probability': 0.30, 'factor': 1.5, 'adjusted_score': 0.45},
            }),
        })()

        result = inference.compute_guess(ctx, {})

        self.assertEqual(result['fetish_id'], 2)
        self.assertEqual(result['probability'], 50.0)
        self.assertEqual(result['raw_probability'], 50.0)
        self.assertEqual(result['top_chart'][0]['fetish_name'], '白衣')
        self.assertEqual(result['top_chart'][1]['fetish_name'], '眼鏡')
        self.assertEqual(result['top_chart'][1]['probability'], 45.0)
        self.assertEqual(result['top_chart'][1]['raw_probability'], 30.0)
        self.assertEqual(result['compound'][0]['fetish_name'], '眼鏡')
        self.assertEqual(result['compound'][0]['probability'], 45.0)

    def test_inference_applies_adjusted_scores_when_excluding_results(self):
        class Engine:
            fetishes = [
                {'id': 1, 'name': '除外候補', 'desc': 'excluded', 'works': []},
                {'id': 2, 'name': '白衣', 'desc': 'lab', 'works': []},
                {'id': 3, 'name': '眼鏡', 'desc': 'glasses', 'works': []},
            ]
            questions = []
            config = {'compound_ratio': 0.8, 'triple_ratio': 0.7}

            def posteriors(self, answers):
                return [0.80, 0.50, 0.30]

            def get_related(self, source_db_id):
                return []

            def get_answer_contributions(self, answers, fetish_idx):
                return []

            def index_of(self, fetish_id):
                return None

        ctx = type('Ctx', (), {
            'engine': Engine(),
            'session': {'exclude_ids': [1]},
            'work_title': staticmethod(lambda work: str(work)),
            'get_compound_works': staticmethod(lambda a, b: []),
            'profile_min_ratio': 0.25,
            'profile_min_prob': 0.08,
            'compound_ratio': 0.8,
            'triple_ratio': 0.7,
            'adjusted_score_provider': staticmethod(lambda probs, ranked: {
                0: {'raw_probability': 0.80, 'factor': 1.2, 'adjusted_score': 0.96},
                1: {'raw_probability': 0.50, 'factor': 1.4, 'adjusted_score': 0.70},
                2: {'raw_probability': 0.30, 'factor': 1.0, 'adjusted_score': 0.30},
            }),
        })()

        result = inference.compute_guess(ctx, {})

        self.assertEqual(result['fetish_id'], 2)
        self.assertEqual(result['probability'], 70.0)
        self.assertEqual(result['raw_probability'], 50.0)
        self.assertEqual(result['top_chart'][0]['fetish_id'], 2)
        self.assertEqual(result['top_chart'][0]['diversity_factor'], 1.4)

    def test_inference_exposure_adjusted_result_drives_side_effects(self):
        calls = []

        class Engine:
            fetishes = [
                {'id': 1, 'name': '激重感情', 'desc': 'heavy', 'works': []},
                {'id': 2, 'name': '白衣', 'desc': 'lab', 'works': []},
            ]
            questions = []
            config = {'compound_ratio': 0.95, 'triple_ratio': 0.9}

            def increment_play_count(self):
                calls.append('increment')

            def posteriors(self, answers):
                return [0.62, 0.58]

            def get_related(self, source_db_id):
                return []

            def get_answer_contributions(self, answers, fetish_idx):
                return [{'q_id': 3, 'answer': 1, 'question': 'q'}]

            def log_guessed(self, fetish_id):
                calls.append(('guessed', fetish_id))

            def index_of(self, fetish_id):
                for index, fetish in enumerate(self.fetishes):
                    if fetish['id'] == fetish_id:
                        return index
                return None

        ctx = type('Ctx', (), {})()
        ctx.engine = Engine()
        ctx.session = {}
        ctx.soft_max_questions = 20
        ctx.mark_guess_quality = lambda engine, session, answers, soft: calls.append('quality')
        ctx.record_question_event = lambda event_name, **kwargs: calls.append((event_name, kwargs.get('result_name')))
        ctx.record_result_exposure = lambda fetish_id, name, probability, **kwargs: calls.append(('exposure', fetish_id, name, probability, kwargs.get('rank')))
        ctx.inference_context = lambda: type('InferenceCtx', (), {
            'engine': ctx.engine,
            'session': ctx.session,
            'work_title': staticmethod(lambda work: str(work)),
            'get_compound_works': staticmethod(lambda a, b: []),
            'profile_min_ratio': 0.25,
            'profile_min_prob': 0.08,
            'compound_ratio': 0.95,
            'triple_ratio': 0.9,
            'adjusted_score_provider': staticmethod(lambda probs, ranked: {
                0: {'raw_probability': 0.62, 'factor': 0.9032, 'adjusted_score': 0.56},
                1: {'raw_probability': 0.58, 'factor': 1.0, 'adjusted_score': 0.58},
            }),
        })()
        ctx.jsonify = lambda payload: payload

        result = inference.make_guess(ctx, {})
        self.assertEqual(result['fetish_id'], 2)
        self.assertEqual(result['fetish_name'], '白衣')
        self.assertEqual(ctx.session['last_guess_fetish_id'], 2)
        self.assertEqual(result['probability'], 58.0)
        self.assertEqual(result['raw_probability'], 58.0)
        self.assertEqual(result['diversity_factor'], 1.0)
        self.assertEqual(result['compound'][0]['probability'], 56.0)
        self.assertEqual(result['compound'][0]['raw_probability'], 62.0)
        self.assertIn(('exposure', 2, '白衣', 58.0, 1), calls)
        self.assertIn(('exposure', 1, '激重感情', 56.0, 2), calls)
        self.assertIn(('guessed', 2), calls)
        self.assertIn(('guessed', 1), calls)
        self.assertIn(('question_result_contribution', '白衣'), calls)

    def test_admin_read_token_guard_method_matrix(self):
        for method in ('POST', 'PUT', 'PATCH', 'DELETE'):
            req = DummyRequest(headers={'Authorization': 'Bearer token'}, method=method)
            response = admin_security.read_token_guard_response(
                req,
                {'ADMIN_READ_TOKEN': 'token'},
                lambda body, status=200, headers=None: (body, status, headers),
                lambda scope, limit: None,
            )
            self.assertEqual(response[1], 403)
        head_req = DummyRequest(headers={'Authorization': 'Bearer token'}, method='HEAD')
        self.assertIsNone(admin_security.read_token_guard_response(
            head_req,
            {'ADMIN_READ_TOKEN': 'token'},
            lambda body, status=200, headers=None: (body, status, headers),
            lambda scope, limit: None,
        ))

    def test_improvement_candidates_summarize_actionable_signals(self):
        report = {
            'questions': [
                {'question_id': 1, 'question_text': '広い質問', 'category': 'value', 'shown': 20, 'answered': 20, 'yes_rate': 95.0, 'no_rate': 5.0, 'dropoff_rate': 0, 'dropoff': 0, 'contribution': 2, 'top_results': []},
                {'question_id': 2, 'question_text': '狭い質問', 'category': 'world', 'shown': 20, 'answered': 20, 'yes_rate': 5.0, 'no_rate': 95.0, 'dropoff_rate': 0, 'dropoff': 0, 'contribution': 2, 'top_results': []},
                {'question_id': 3, 'question_text': '離脱質問', 'category': 'relation', 'shown': 20, 'answered': 10, 'yes_rate': 50.0, 'no_rate': 50.0, 'dropoff_rate': 45.0, 'dropoff': 9, 'contribution': 8, 'top_results': [{'result_name': '激重感情', 'count': 7}]},
            ]
        }
        events = [result_exposure.build_event(1, '激重感情') for _ in range(25)]
        events.extend(result_exposure.build_event(2, '白衣') for _ in range(10))
        candidates = improvement_candidates.build_candidates(report, exposure_events=events, limit=3)
        self.assertEqual(candidates['yes_rate_high'][0]['question_id'], 1)
        self.assertEqual(candidates['yes_rate_low'][0]['question_id'], 2)
        self.assertEqual(candidates['dropoff_top'][0]['question_id'], 3)
        self.assertEqual(candidates['heavy_result_contributors'][0]['question_id'], 3)
        self.assertEqual(candidates['result_diversity']['status'], 'needs_review')



if __name__ == '__main__':
    unittest.main()

class TestShareLinks(unittest.TestCase):
    def test_share_link_round_trip_uses_longer_base62_id_and_no_personal_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'share_links.json')
            seq = iter(['7f3kQ9Lm'])
            share_id, payload = share_links.create_link(
                {
                    'name': '感覚遮断落とし穴',
                    'probability': '93',
                    'desc': 'テスト',
                    'title': "あなたの『癖』は……",
                    'rank': 'AI観測ログ',
                    'ip': '127.0.0.1',
                    'user_agent': 'secret',
                },
                path=path,
                token_fn=lambda length: next(seq),
            )
            self.assertEqual(share_id, '7f3kQ9Lm')
            self.assertEqual(payload['name'], '感覚遮断落とし穴')
            resolved = share_links.resolve_link('7f3kQ9Lm', path=path)
            self.assertEqual(resolved['probability'], '93')
            self.assertEqual(share_links.count_links(path=path), 1)
            self.assertNotIn('ip', resolved)
            self.assertNotIn('user_agent', resolved)

    def test_resolve_link_accepts_existing_four_character_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'share_links.json')
            with open(path, 'w', encoding='utf-8') as file_obj:
                json.dump({'7f3k': {'name': '旧共有', 'probability': '93'}}, file_obj, ensure_ascii=False)
            resolved = share_links.resolve_link('7f3k', path=path)
        self.assertEqual(resolved['name'], '旧共有')
        self.assertEqual(resolved['probability'], '93')


    def test_share_links_use_postgres_when_available(self):
        executed = []

        class Cursor:
            def __init__(self):
                self.rows = []
                self.payload = None

            def execute(self, sql, params=None):
                executed.append((sql, params))
                if sql.startswith('SELECT share_id FROM share_links'):
                    self.rows = []
                elif sql.startswith('SELECT payload FROM share_links'):
                    self.rows = [(self.payload,)] if self.payload else []
                elif sql.startswith('SELECT COUNT'):
                    self.rows = [(1,)]
                elif sql.startswith('INSERT INTO share_links'):
                    self.payload = params[1]

            def fetchall(self):
                return self.rows

            def fetchone(self):
                return self.rows[0] if self.rows else None

        class Conn:
            def __init__(self):
                self.cursor_obj = Cursor()

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def cursor(self):
                return self.cursor_obj

        conn = Conn()
        with patch.object(share_links, 'use_db', return_value=True), \
                patch.object(share_links, 'get_conn', return_value=conn), \
                patch.object(share_links, 'put_conn'):
            share_id, payload = share_links.create_link(
                {'name': '眼鏡', 'probability': '88', 'desc': 'テスト'},
                token_fn=lambda length: 'Ab12Cd34',
            )
            resolved = share_links.resolve_link(share_id)
            count = share_links.count_links()

        self.assertEqual(share_id, 'Ab12Cd34')
        self.assertEqual(payload['name'], '眼鏡')
        self.assertEqual(resolved['probability'], '88')
        self.assertEqual(count, 1)
        self.assertTrue(any('CREATE TABLE IF NOT EXISTS share_links' in sql for sql, _params in executed))
        self.assertTrue(any(sql.startswith('INSERT INTO share_links') for sql, _params in executed))

    def test_share_link_rejects_invalid_id_and_missing_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'share_links.json')
            self.assertIsNone(share_links.resolve_link('../bad', path=path))
            with self.assertRaises(ValueError):
                share_links.create_link({'probability': '88'}, path=path)
