from tests._service_test_support import (
    DummyAuth,
    DummyLogEngine,
    DummyRequest,
    admin_context,
    admin_helpers,
    admin_security,
    audit,
    context,
    csv_safety,
    dummy_jsonify,
    dummy_runtime,
    filesystem_context,
    game_context,
    matrix_backups,
    rate_limit,
    response_hooks,
    runtime_guards,
    runtime_service,
    seo_context,
    system_context,
    unittest,
)


class TestServiceRuntimeAdmin(unittest.TestCase):
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
        self.assertEqual(
            audit._sanitize_detail({'token': 'secret', 'nested': {'password': 'x'}}),
            {
                'token': '[redacted]',
                'nested': {'password': '[redacted]'},
            },
        )

    def test_csv_safety_prefixes_formula_values(self):
        self.assertEqual(csv_safety.safe_csv_cell('=cmd'), "'=cmd")
        self.assertEqual(csv_safety.safe_csv_cell(' +SUM(A1)'), "' +SUM(A1)")
        self.assertEqual(csv_safety.safe_csv_cell('plain'), 'plain')

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
            rate_limit.client_ip(req, {'TRUSTED_PROXY_IPS': '127.0.0.1,10.0.0.0/8'}),
            '203.0.113.9',
        )
        self.assertEqual(rate_limit.client_ip(req, {'TRUSTED_PROXY_IPS': ''}), '127.0.0.1')

    def test_rate_limit_returns_retry_after_response(self):
        req = DummyRequest()
        req.remote_addr = '127.0.0.1'
        buckets = {}
        guard = lambda name: True
        first = rate_limit.rate_limit(
            'api_start',
            1,
            req,
            {},
            buckets,
            dummy_jsonify,
            guard,
            window_seconds=60,
            time_fn=lambda: 100,
        )
        second = rate_limit.rate_limit(
            'api_start',
            1,
            req,
            {},
            buckets,
            dummy_jsonify,
            guard,
            window_seconds=60,
            time_fn=lambda: 101,
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
            get_compound_works=lambda a, b: [],
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
                os_module=type(
                    'Os',
                    (),
                    {
                        'path': type(
                            'Path',
                            (),
                            {
                                'join': staticmethod(lambda *parts: '/'.join(parts)),
                                'exists': staticmethod(lambda path: True),
                                'getmtime': staticmethod(lambda path: 0),
                                'relpath': staticmethod(lambda path, base: path),
                                'basename': staticmethod(lambda path: path),
                            },
                        )
                    },
                )(),
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
            adsense_client='',
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
                os_module=type(
                    'Os',
                    (),
                    {
                        'path': type(
                            'Path',
                            (),
                            {
                                'join': staticmethod(lambda *parts: '/'.join(parts)),
                                'exists': staticmethod(lambda path: False),
                                'getmtime': staticmethod(lambda path: 0),
                                'relpath': staticmethod(lambda path, base: path),
                                'basename': staticmethod(lambda path: path),
                            },
                        )
                    },
                )(),
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
        self.assertIn('あなたの『癖』は……', ctx.result_share_text('A', '88'))
        self.assertEqual(ctx.result_title('88'), 'あなたの『癖』は……')
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
            response,
            req,
            lambda *args: calls.append(args),
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
        self.assertIsNone(
            admin_security.read_token_guard_response(
                head_req,
                {'ADMIN_READ_TOKEN': 'token'},
                lambda body, status=200, headers=None: (body, status, headers),
                lambda scope, limit: None,
            )
        )
