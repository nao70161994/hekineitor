from tests._service_test_support import (
    event_store,
    ids,
    inference,
    patch,
    question_events,
    question_selection,
    result_exposure,
    share_events,
    unittest,
)


class TestServiceInference(unittest.TestCase):
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
                return ('best', tuple(asked), idk_streak)

            def best_disambiguating_question(self, answers, asked, *, candidate_count=3, idk_streak=0):
                return ('disambig', tuple(asked), candidate_count, idk_streak)

        selector = question_selection.make_next_question_selector(Engine())
        self.assertEqual(selector({}, [2, 1], idk_streak=1), ('best', (2, 1), 1))
        self.assertEqual(selector({}, [2], idk_streak=3, disambiguate=True), ('disambig', (2,), 3, 3))
        self.assertEqual(
            selector({}, [2, 1], idk_streak=3, disambiguate=True),
            ('disambig', (2, 1), 3, 3),
        )

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
        ctx.inference_context = lambda: type(
            'InferenceCtx',
            (),
            {
                'engine': ctx.engine,
                'session': ctx.session,
                'work_title': staticmethod(lambda work: str(work)),
                'get_compound_works': staticmethod(lambda a, b: []),
                'profile_min_ratio': 0.25,
                'profile_min_prob': 0.08,
                'compound_ratio': 0.55,
                'triple_ratio': 0.45,
            },
        )()
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
        ctx.record_question_event = lambda event_name, **kwargs: events.append(
            question_events.build_event(event_name, **kwargs)
        )
        ctx.inference_context = lambda: type(
            'InferenceCtx',
            (),
            {
                'engine': ctx.engine,
                'session': ctx.session,
                'work_title': staticmethod(lambda work: str(work)),
                'get_compound_works': staticmethod(lambda a, b: []),
                'profile_min_ratio': 0.25,
                'profile_min_prob': 0.08,
                'compound_ratio': 0.55,
                'triple_ratio': 0.45,
            },
        )()
        ctx.jsonify = lambda payload: payload

        inference.make_guess(ctx, {'0': -0.5})

        self.assertEqual(events[0]['event_name'], 'question_result_contribution')
        self.assertEqual(events[0]['answer'], -0.5)
        self.assertEqual(events[0]['answer_bucket'], 'no')

    def test_analytics_events_use_postgres_store_when_enabled(self):
        stored = []
        with (
            patch.object(share_events.event_store, 'enabled', return_value=True),
            patch.object(
                share_events.event_store,
                'record_event',
                side_effect=lambda event_type, event: stored.append((event_type, event)) or event,
            ),
            patch.object(question_events.event_store, 'enabled', return_value=True),
            patch.object(
                question_events.event_store,
                'record_event',
                side_effect=lambda event_type, event: stored.append((event_type, event)) or event,
            ),
            patch.object(result_exposure.event_store, 'enabled', return_value=True),
            patch.object(
                result_exposure.event_store,
                'record_event',
                side_effect=lambda event_type, event: stored.append((event_type, event)) or event,
            ),
        ):
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

        with (
            patch.object(event_store, 'enabled', return_value=True),
            patch.object(event_store, 'read_events', side_effect=fake_read),
        ):
            self.assertEqual(share_events.read_events(limit=10)[0]['result_name'], '眼鏡')
            self.assertEqual(question_events.read_events(limit=10)[0]['question_id'], 3)
            self.assertEqual(result_exposure.read_events(limit=10)[0]['fetish_id'], 7)

    def test_analytics_storage_status_reports_postgres_without_secrets(self):
        with (
            patch.object(share_events.event_store, 'enabled', return_value=True),
            patch.object(
                share_events.event_store,
                'storage_status',
                return_value={
                    'path': 'postgres:analytics_events:share',
                    'storage': 'postgres',
                    'count': 2,
                    'parent_writable': True,
                    'file_writable': True,
                },
            ),
        ):
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
        ctx.record_result_exposure = lambda fetish_id, name, probability, **kwargs: calls.append(
            (fetish_id, name, probability, kwargs)
        )
        ctx.inference_context = lambda: type(
            'InferenceCtx',
            (),
            {
                'engine': ctx.engine,
                'session': ctx.session,
                'work_title': staticmethod(lambda work: str(work)),
                'get_compound_works': staticmethod(lambda a, b: []),
                'profile_min_ratio': 0.25,
                'profile_min_prob': 0.08,
                'compound_ratio': 0.95,
                'triple_ratio': 0.9,
            },
        )()
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

        ctx = type(
            'Ctx',
            (),
            {
                'engine': Engine(),
                'session': {},
                'work_title': staticmethod(lambda work: str(work)),
                'get_compound_works': staticmethod(lambda a, b: []),
                'profile_min_ratio': 0.25,
                'profile_min_prob': 0.08,
                'compound_ratio': 0.8,
                'triple_ratio': 0.7,
                'adjusted_score_provider': staticmethod(
                    lambda probs, ranked: {
                        0: {'raw_probability': 0.80, 'factor': 0.2, 'adjusted_score': 0.16},
                        1: {'raw_probability': 0.50, 'factor': 1.0, 'adjusted_score': 0.50},
                        2: {'raw_probability': 0.30, 'factor': 1.5, 'adjusted_score': 0.45},
                    }
                ),
            },
        )()

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

        ctx = type(
            'Ctx',
            (),
            {
                'engine': Engine(),
                'session': {'exclude_ids': [1]},
                'work_title': staticmethod(lambda work: str(work)),
                'get_compound_works': staticmethod(lambda a, b: []),
                'profile_min_ratio': 0.25,
                'profile_min_prob': 0.08,
                'compound_ratio': 0.8,
                'triple_ratio': 0.7,
                'adjusted_score_provider': staticmethod(
                    lambda probs, ranked: {
                        0: {'raw_probability': 0.80, 'factor': 1.2, 'adjusted_score': 0.96},
                        1: {'raw_probability': 0.50, 'factor': 1.4, 'adjusted_score': 0.70},
                        2: {'raw_probability': 0.30, 'factor': 1.0, 'adjusted_score': 0.30},
                    }
                ),
            },
        )()

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
        ctx.record_result_exposure = lambda fetish_id, name, probability, **kwargs: calls.append(
            ('exposure', fetish_id, name, probability, kwargs.get('rank'))
        )
        ctx.inference_context = lambda: type(
            'InferenceCtx',
            (),
            {
                'engine': ctx.engine,
                'session': ctx.session,
                'work_title': staticmethod(lambda work: str(work)),
                'get_compound_works': staticmethod(lambda a, b: []),
                'profile_min_ratio': 0.25,
                'profile_min_prob': 0.08,
                'compound_ratio': 0.95,
                'triple_ratio': 0.9,
                'adjusted_score_provider': staticmethod(
                    lambda probs, ranked: {
                        0: {'raw_probability': 0.62, 'factor': 0.9032, 'adjusted_score': 0.56},
                        1: {'raw_probability': 0.58, 'factor': 1.0, 'adjusted_score': 0.58},
                    }
                ),
            },
        )()
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
