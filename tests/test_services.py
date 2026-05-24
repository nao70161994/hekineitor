import sys
import os
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services import admin_context, admin_helpers, admin_security, bootstrap, context, filesystem_context, game_context, seo_context, app_meta, ids, inference, matrix_backups, name_matching, quality_stats, question_selection, rate_limit, response_hooks, runtime_guards, runtime as runtime_service, share, share_events, share_notes, system_context, test_play


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
        ]
        rows = share_events.daily_summary(events, days=7)
        self.assertEqual([row['date'] for row in rows], ['2026-05-23', '2026-05-24'])
        self.assertEqual(rows[0]['result_page_views'], 1)
        self.assertEqual(rows[0]['ogp_views'], 1)
        self.assertEqual(rows[1]['x_clicks'], 1)
        self.assertEqual(rows[1]['web_share_successes'], 1)
        self.assertEqual(rows[1]['copy_successes'], 1)

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

    def test_app_version_default_includes_pwa_assets(self):
        self.assertIn('static/icon-192.png', app_meta.APP_VERSION_PATHS)
        self.assertIn('static/icon-512.png', app_meta.APP_VERSION_PATHS)
        self.assertIn('templates/sw.js', app_meta.APP_VERSION_PATHS)

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
            safe_work_url=lambda url: url,
            amazon_associate_id='assoc',
            fetish_relations={1: [2]},
            error_page='error',
            record_share_event=lambda *args, **kwargs: None,
            learning_disabled=lambda: False,
        )
        self.assertEqual(ctx.public_base_url(), 'https://example.com')
        self.assertEqual(ctx.clean_probability('88.0'), '88')
        self.assertIn('へきネイター', ctx.result_share_text('A', '88'))
        self.assertEqual(ctx.result_title('88'), '濃厚反応タイプ')
        self.assertEqual(ctx.result_rarity('88'), 'SR')
        self.assertEqual(ctx.player_fetish_base_id, 1000)
        self.assertEqual(ctx.fetish_relations, {1: [2]})


    def test_response_hooks_set_security_headers_and_count_errors(self):
        class Response:
            status_code = 404
            headers = {}

        counts = {'4xx': 0, '5xx': 0}
        response_hooks.record_status_counts(Response, counts)
        response_hooks.apply_security_headers(Response)
        self.assertEqual(counts['4xx'], 1)
        self.assertEqual(Response.headers['X-Content-Type-Options'], 'nosniff')
        self.assertIn("default-src 'self'", Response.headers['Content-Security-Policy'])

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
            'work_title': lambda work: str(work),
            'get_compound_works': lambda a, b: [],
            'profile_min_ratio': 0.25,
            'profile_min_prob': 0.08,
            'compound_ratio': 0.55,
            'triple_ratio': 0.45,
        })()
        ctx.jsonify = lambda payload: payload

        result = inference.make_guess(ctx, {})
        self.assertEqual(result['fetish_id'], 7)
        self.assertEqual(calls, ['increment', 'quality', ('guessed', 7)])



if __name__ == '__main__':
    unittest.main()
