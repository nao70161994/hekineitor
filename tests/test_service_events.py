from tests._service_test_support import (
    game_routes,
    improvement_candidates,
    name_matching,
    os,
    question_events,
    result_exposure,
    share_events,
    share_notes,
    tempfile,
    test_play,
    unittest,
)


class TestServiceEvents(unittest.TestCase):
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
            share_events.record_event(
                'result_page_view', result_name='NTR', channel='result_page', success=True, path=share_path
            )
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
            question_events.record_event(
                'question_answered', question_id=0, answer=-1.0, category='relation', path=path
            )
            question_events.record_event('question_answered', question_id=2, answer=1.0, category='world', path=path)
            question_events.record_event(
                'question_dropoff', question_id=0, answered_count=1, category='relation', path=path
            )
            question_events.record_event(
                'question_result_contribution', question_id=0, result_name='共依存', answer=1.0, path=path
            )
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

    def test_question_events_report_tracks_cold_start_maturity(self):
        class Engine:
            questions = [
                {'text': 'neutral', 'category': 'world', 'learning_scale_neutral': True},
                {'text': 'learned', 'category': 'value', 'learning_scale_neutral': True},
            ]

            def get_question_stats(self):
                return [
                    {'id': 0, 'disc': 0.0, 'ask_count': 512.0},
                    {'id': 1, 'disc': 0.06, 'ask_count': 540.0},
                ]

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'question_events.jsonl')
            for _ in range(20):
                question_events.record_event(
                    'question_feedback_learned',
                    question_id=0,
                    answer=1.0,
                    feedback_kind='positive',
                    target_count=2,
                    discrimination=_ / 1000,
                    path=path,
                )
            report = question_events.event_report(Engine(), path=path, exclude_suspicious=False)

        stalled = next(row for row in report['cold_start_questions'] if row['question_id'] == 0)
        mature = next(row for row in report['cold_start_questions'] if row['question_id'] == 1)
        self.assertEqual(stalled['feedback'], 20)
        self.assertEqual(stalled['positive_feedback'], 20)
        self.assertEqual(stalled['feedback_targets'], 40)
        self.assertEqual(stalled['feedback_discrimination_first'], 0.0)
        self.assertEqual(stalled['feedback_discrimination_latest'], 0.019)
        self.assertEqual(stalled['feedback_discrimination_delta'], 0.019)
        self.assertEqual(stalled['maturity'], 'needs_review')
        self.assertEqual(mature['maturity'], 'mature')
        self.assertEqual(report['cold_start_summary']['needs_review'], 1)
        self.assertEqual(report['metrics']['feedback_learning'], 20)
        self.assertIn('cold_start_questions_stalled', [item['type'] for item in report['warnings']])

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
            return type(
                'Now',
                (),
                {
                    'astimezone': lambda self, tz: self,
                    'isoformat': lambda self, timespec='seconds': value,
                },
            )()

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'question_events.jsonl')
            timestamp = '2026-06-21T00:00:00+00:00'
            question_events.record_event(
                'question_shown', question_id=0, category='relation', path=path, now_fn=lambda: fixed_now(timestamp)
            )
            for _ in range(12):
                question_events.record_event(
                    'question_answered',
                    question_id=0,
                    answer=1.0,
                    category='relation',
                    path=path,
                    now_fn=lambda: fixed_now(timestamp),
                )
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
            return type(
                'Now',
                (),
                {
                    'astimezone': lambda self, tz: self,
                    'isoformat': lambda self, timespec='seconds': value,
                },
            )()

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'question_events.jsonl')
            question_events.record_event(
                'question_shown',
                question_id=0,
                category='relation',
                path=path,
                now_fn=lambda: fixed_now('2026-06-20T14:59:00+00:00'),
            )
            question_events.record_event(
                'question_shown',
                question_id=0,
                category='relation',
                path=path,
                now_fn=lambda: fixed_now('2026-06-20T15:00:00+00:00'),
            )
            question_events.record_event(
                'question_answered',
                question_id=0,
                answer=1.0,
                category='relation',
                path=path,
                now_fn=lambda: fixed_now('2026-06-21T14:59:00+00:00'),
            )
            question_events.record_event(
                'question_shown',
                question_id=0,
                category='relation',
                path=path,
                now_fn=lambda: fixed_now('2026-06-21T15:00:00+00:00'),
            )
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
        ctx.record_question_event = lambda event_name, **kwargs: events.append(
            question_events.build_event(event_name, **kwargs)
        )

        game_routes._record_question_event(ctx, 'question_shown', 0)

        self.assertEqual(events[0]['axis'], 'personality')

    def test_share_events_csv_escapes_formula_result_names(self):
        report = {'ranking': [{'result_name': '=HYPERLINK("x")', 'total': 1}], 'filters': {}}
        body = share_events.ranking_csv(report)
        self.assertIn("'=HYPERLINK", body)

    def test_share_events_builds_minimal_sanitized_event(self):
        now = type(
            'Now',
            (),
            {
                'astimezone': lambda self, tz: self,
                'isoformat': lambda self, timespec='seconds': '2026-05-23T00:00:00+00:00',
            },
        )()
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
                share_events.record_event(
                    'result_page_view', result_name=f'R{idx}', channel='result_page', success=True, path=path
                )
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
            'filters': {
                'since': '2026-05-23',
                'until': '2026-05-24',
                'days': '',
                'compare_since': '',
                'compare_until': '',
            },
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
            old_now = type(
                'Now',
                (),
                {
                    'astimezone': lambda self, tz: self,
                    'isoformat': lambda self, timespec='seconds': '2026-05-20T00:00:00+00:00',
                },
            )()
            new_now = type(
                'Now',
                (),
                {
                    'astimezone': lambda self, tz: self,
                    'isoformat': lambda self, timespec='seconds': '2026-05-24T00:00:00+00:00',
                },
            )()
            share_events.record_event(
                'share_button_click', result_name='A', channel='button', success=True, path=path, now_fn=lambda: old_now
            )
            share_events.record_event(
                'share_button_click', result_name='A', channel='button', success=True, path=path, now_fn=lambda: new_now
            )
            share_events.record_event(
                'x_share_click', result_name='A', channel='x', success=True, path=path, now_fn=lambda: new_now
            )
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
            now = type(
                'Now',
                (),
                {
                    'astimezone': lambda self, tz: self,
                    'isoformat': lambda self, timespec='seconds': '2026-05-24T00:00:00+00:00',
                },
            )()
            saved = share_notes.save_note('NTR', '<script>alert(1)</script>', path=path, now_fn=lambda: now)
            self.assertEqual(saved['note'], '<script>alert(1)</script>')
            self.assertEqual(saved['updated_at'], '2026-05-24T00:00:00+00:00')
            loaded = share_notes.load_notes(path=path)
            self.assertEqual(loaded['NTR']['note'], '<script>alert(1)</script>')
            share_notes.save_note('NTR', '', path=path, now_fn=lambda: now)
            self.assertEqual(share_notes.load_notes(path=path), {})

    def test_share_events_work_clicks_are_ranked_by_work_and_date(self):
        events = [
            {
                'timestamp': '2026-05-24T00:00:00+00:00',
                'event_name': 'work_click',
                'result_name': '白衣',
                'channel': 'work',
                'work_title': '作品A',
            },
            {
                'timestamp': '2026-05-24T01:00:00+00:00',
                'event_name': 'work_click',
                'result_name': '白衣',
                'channel': 'work',
                'work_title': '作品A',
            },
            {
                'timestamp': '2026-05-25T00:00:00+00:00',
                'event_name': 'work_click',
                'result_name': '眼鏡',
                'channel': 'fetish_page',
                'work_title': '作品B',
            },
        ]

        direct = {
            'metrics': share_events._summary_metrics({'work_click': 3}),
            'daily': share_events.daily_summary(events),
            'work_ranking': share_events.work_ranking(events),
        }

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

    def test_improvement_candidates_summarize_actionable_signals(self):
        report = {
            'questions': [
                {
                    'question_id': 1,
                    'question_text': '広い質問',
                    'category': 'value',
                    'shown': 20,
                    'answered': 20,
                    'yes_rate': 95.0,
                    'no_rate': 5.0,
                    'dropoff_rate': 0,
                    'dropoff': 0,
                    'contribution': 2,
                    'top_results': [],
                },
                {
                    'question_id': 2,
                    'question_text': '狭い質問',
                    'category': 'world',
                    'shown': 20,
                    'answered': 20,
                    'yes_rate': 5.0,
                    'no_rate': 95.0,
                    'dropoff_rate': 0,
                    'dropoff': 0,
                    'contribution': 2,
                    'top_results': [],
                },
                {
                    'question_id': 3,
                    'question_text': '離脱質問',
                    'category': 'relation',
                    'shown': 20,
                    'answered': 10,
                    'yes_rate': 50.0,
                    'no_rate': 50.0,
                    'dropoff_rate': 45.0,
                    'dropoff': 9,
                    'contribution': 8,
                    'top_results': [{'result_name': '激重感情', 'count': 7}],
                },
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
