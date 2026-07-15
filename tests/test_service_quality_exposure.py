from tests._service_test_support import (
    json,
    os,
    patch,
    quality_stats,
    result_exposure,
    tempfile,
    unittest,
)


class TestServiceQualityExposure(unittest.TestCase):
    def test_quality_stats_records_guess_and_feedback_keys(self):
        calls = []

        class Engine:
            def _record_daily_stat(self, key):
                calls.append(key)

        session = {'low_confidence_extended': True}
        quality_stats.mark_guess_quality(Engine(), session, {str(i): 1 for i in range(22)}, 20)
        self.assertEqual(
            session['last_guess_quality'],
            {
                'low_confidence_extended': True,
                'additional_questions': 2,
            },
        )
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

        events = [
            result_exposure.build_event(2, '激重感情', 80, rank=101, source=result_exposure.TOP_CHART_SOURCE)
            for _ in range(20)
        ]
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
        candidate_report = result_exposure.ranking_from_events(
            events, top_n=5, include_secondary=True, include_candidates=True
        )

        self.assertEqual(default_report['total'], 1)
        self.assertEqual(default_report['ranking'][0]['fetish_name'], '制服')
        self.assertEqual(candidate_report['total'], 2)
        self.assertEqual(
            {row['fetish_name']: row['count'] for row in candidate_report['ranking']}, {'制服': 1, '激重感情': 1}
        )

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
            {
                'timestamp': '2026-05-26T00:00:00+00:00',
                'event_name': 'result_exposed',
                'fetish_id': 1,
                'fetish_name': '共依存',
            },
            {
                'timestamp': '2026-05-27T00:00:00+00:00',
                'event_name': 'result_exposed',
                'fetish_id': 2,
                'fetish_name': '白衣',
            },
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
