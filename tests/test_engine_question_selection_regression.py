import math
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from engine import Engine
from engine import question_selection as engine_question_selection


class _DisambiguationEngine:
    """Small deterministic engine for testing one ranking penalty at a time."""

    def __init__(self, probabilities, *, categories=None, axes=None):
        self._probabilities = probabilities
        self.fetishes = [{'id': index + 1} for index in range(len(probabilities[0]))]
        self.questions = [
            {'category': (categories or {}).get(index, f'category-{index}')} for index in range(len(probabilities))
        ]
        self.disabled_questions = set()
        self._axes = axes or {}

    def posteriors(self, _answers):
        return [1.0 / len(self.fetishes)] * len(self.fetishes)

    def _prob(self, fetish_index, question_id):
        return self._probabilities[question_id][fetish_index]

    def _question_category(self, question_id):
        return self.questions[question_id]['category']

    def _question_axis(self, question_id):
        return self._axes.get(question_id, f'axis-{question_id}')

    def _question_balance_stats(self):
        return {}

    def best_question(self, _answers, _asked, *, idk_streak=0):
        raise AssertionError(f'unexpected fallback (idk_streak={idk_streak})')


class _IdkRecoveryEngine:
    def __init__(self, axes):
        self._axes = axes
        self.fetishes = [{'id': 1}, {'id': 2}]
        categories = ['relation', 'attachment', 'value', 'aesthetic', 'world']
        self.questions = [{'category': categories[index]} for index in range(len(axes))]
        self.disabled_questions = set()
        self.matrix = {'total': [[1.0] * len(axes), [1.0] * len(axes)]}

    def posteriors(self, _answers):
        return [0.5, 0.5]

    def _prob(self, fetish_index, question_id):
        return (0.8, 0.2)[fetish_index] if question_id % 2 else (0.7, 0.3)[fetish_index]

    def _entropy(self, probabilities):
        return -sum(value * math.log(value) for value in probabilities if value > 0)

    def _question_axis(self, question_id):
        return self._axes[question_id]

    def _question_category(self, question_id):
        return self.questions[question_id]['category']

    def best_question(self, _answers, asked, *, idk_streak=0):
        return next(
            (question_id for question_id in range(len(self.questions)) if question_id not in asked),
            None,
        )


class TestIdkRecoverySelection(unittest.TestCase):
    def test_hard_excludes_every_axis_in_the_recent_idk_streak(self):
        from services import question_selection

        engine = _IdkRecoveryEngine(['abstract', 'content', 'abstract', 'personality', 'content'])
        answers = {'0': 0, '1': 0, '2': 0}

        selection = question_selection.idk_recovery_selection(engine, answers, [0, 1, 2])

        self.assertFalse(selection['fallback'])
        self.assertEqual(selection['avoided_axes'], ['abstract', 'content'])
        self.assertEqual(engine._question_axis(selection['question_id']), 'personality')

    def test_marks_fallback_only_when_no_alternate_axis_question_exists(self):
        from services import question_selection

        engine = _IdkRecoveryEngine(['abstract', 'abstract', 'abstract'])
        answers = {'0': 0, '1': 0}

        selection = question_selection.idk_recovery_selection(engine, answers, [0, 1])

        self.assertTrue(selection['fallback'])
        self.assertEqual(selection['question_id'], 2)
        self.assertEqual(selection['avoided_axes'], ['abstract'])

    def test_information_gain_rejection_cannot_break_the_axis_guarantee(self):
        from services import question_selection

        engine = _IdkRecoveryEngine(['abstract', 'abstract', 'personality'])
        engine._prob = lambda _fetish_index, _question_id: 1.0

        selection = question_selection.idk_recovery_selection(engine, {'0': 0, '1': 0}, [0, 1])

        self.assertFalse(selection['fallback'])
        self.assertEqual(selection['question_id'], 2)


class TestEngineQuestionSelectionRegression(unittest.TestCase):
    def setUp(self):
        self._patches = [
            patch.object(Engine, '_save_matrix_file', return_value=None),
            patch.object(Engine, '_save_fetishes_file', return_value=None),
            patch.object(Engine, '_save_to_db', return_value=None),
            patch.object(Engine, '_load_matrix_file', new=lambda self: self._init_matrix_file()),
            patch.object(Engine, 'get_fetish_log', return_value={}),
            patch.object(Engine, '_question_balance_stats', return_value={}),
            patch('engine_question_selection.random.choice', side_effect=lambda pool: pool[0]),
        ]
        for patcher in self._patches:
            patcher.start()
        self.engine = Engine()

    def tearDown(self):
        for patcher in self._patches:
            patcher.stop()

    def test_yes_rate_balance_multiplier_penalizes_extreme_rates_only_with_enough_answers(self):
        self.assertEqual(
            engine_question_selection.question_yes_balance_multiplier({'answered': 19, 'yes_rate': 100}),
            1.0,
        )
        self.assertAlmostEqual(
            engine_question_selection.question_yes_balance_multiplier({'answered': 20, 'yes_rate': 50}),
            1.0,
        )
        self.assertAlmostEqual(
            engine_question_selection.question_yes_balance_multiplier({'answered': 20, 'yes_rate': 100}),
            0.4,
        )
        self.assertAlmostEqual(
            engine_question_selection.question_yes_balance_multiplier({'answered': 20, 'yes_rate': 90}),
            0.52,
        )

    def test_best_question_penalizes_high_yes_rate_question_when_alternatives_exist(self):
        answers = {'60': 1, '2': 1, '91': 1}
        asked = {60, 2, 91}
        baseline = self.engine.best_question(answers, asked)
        stats = {baseline: {'answered': 30, 'yes_rate': 100.0}}
        with patch.object(self.engine, '_question_balance_stats', return_value=stats):
            balanced = self.engine.best_question(answers, asked)
        self.assertNotEqual(balanced, baseline)
        self.assertNotIn(balanced, asked)

    def test_best_question_snapshots_with_deterministic_randomness(self):
        cases = [
            ({}, set(), 0, 88),
            ({'0': 0, '1': 0}, {0, 1}, 2, 136),
            ({'8': 1, '6': 1, '0': 1, '40': 1}, {0, 6, 8, 40}, 0, 18),
        ]
        for answers, asked, idk_streak, expected_question in cases:
            with self.subTest(expected_question=expected_question):
                self.assertEqual(
                    self.engine.best_question(answers, asked, idk_streak=idk_streak),
                    expected_question,
                )

    def test_early_questions_prefer_abstract_axis(self):
        for asked in [set(), {91}, {91, 105}]:
            with self.subTest(asked=asked):
                question_id = self.engine.best_question({}, asked)
                self.assertEqual(self.engine._question_axis(question_id), 'abstract')

    def test_early_questions_spread_relation_and_attachment_categories(self):
        asked = set()
        categories = []
        for _ in range(4):
            question_id = self.engine.best_question({}, asked)
            categories.append(self.engine._question_category(question_id))
            asked.add(question_id)
        self.assertLessEqual(sum(category in {'relation', 'attachment'} for category in categories[:3]), 2)
        self.assertGreaterEqual(len(set(categories[:4])), 3)

    def test_recent_category_is_not_repeated_when_alternatives_exist(self):
        asked = {55, 91}
        question_id = self.engine.best_question({}, asked)
        self.assertNotEqual(self.engine._question_category(question_id), 'attachment')

    def test_direct_heavy_questions_are_not_asked_in_first_five(self):
        asked = set()
        first_questions = []
        for _ in range(5):
            question_id = self.engine.best_question({}, asked)
            first_questions.append(question_id)
            asked.add(question_id)
        for question_id in (2, 55, 60, 87, 91, 105, 120, 126, 132):
            self.assertNotIn(question_id, first_questions)

    def test_yes_streak_does_not_overconcentrate_heavy_relation_results(self):
        asked = set()
        answers = {}
        for _ in range(8):
            question_id = self.engine.best_question(answers, asked)
            asked.add(question_id)
            answers[str(question_id)] = 1
        probs = self.engine.posteriors(answers)
        ranked_names = [
            self.engine.fetishes[index]['name']
            for index in sorted(range(len(probs)), key=lambda i: probs[i], reverse=True)[:4]
        ]
        heavy_names = {'共依存', '激重感情', '共生関係', '執着'}
        self.assertLessEqual(sum(name in heavy_names for name in ranked_names), 1)

    def test_heavy_emotion_cluster_prefers_diversifying_categories(self):
        answers = {'60': 1, '2': 1, '91': 1}
        asked = {60, 2, 91}
        question_id = self.engine.best_question(answers, asked)
        self.assertIn(self.engine._question_category(question_id), {'attribute', 'world', 'aesthetic', 'value', 'role'})
        self.assertNotIn(question_id, {55, 87, 105, 120, 126, 132})

    def test_attribute_world_aesthetic_pattern_surfaces_non_heavy_candidates(self):
        answers = {'136': 1, '141': 1, '123': 1, '70': -1, '60': -1, '2': -1}
        probs = self.engine.posteriors(answers)
        ranked_names = [
            self.engine.fetishes[index]['name']
            for index in sorted(range(len(probs)), key=lambda i: probs[i], reverse=True)[:5]
        ]
        self.assertTrue({'眼鏡', '白衣', '敬語'} & set(ranked_names))

    def test_low_exposure_axis_probe_triggers_for_heavy_cluster(self):
        from services import question_selection

        answers = {'60': 1, '2': 1, '91': 1}
        asked = {60, 2, 91}
        probs = self.engine.posteriors(answers)
        ranked = sorted(range(len(probs)), key=lambda index: probs[index], reverse=True)
        top_p = probs[ranked[0]]
        second_p = probs[ranked[1]]
        self.assertTrue(
            question_selection.should_probe_low_exposure_axis(
                self.engine,
                answers,
                asked,
                count=4,
                top_p=top_p,
                second_p=second_p,
                hard_max_questions=30,
            )
        )
        question_id = question_selection.best_low_exposure_axis_question(self.engine, answers, asked)
        self.assertIsNotNone(question_id)
        self.assertIn(self.engine._question_category(question_id), {'attribute', 'world', 'aesthetic', 'value', 'role'})

    def test_best_disambiguating_question_snapshots(self):
        cases = [
            ({}, set(), 0, 2),
            ({'0': 0, '1': 0}, {0, 1}, 2, 91),
            ({'8': 1, '6': 1, '0': 1, '40': 1}, {0, 6, 8, 40}, 0, 7),
        ]
        for answers, asked, idk_streak, expected_question in cases:
            with self.subTest(expected_question=expected_question):
                self.assertEqual(
                    self.engine.best_disambiguating_question(
                        answers,
                        asked,
                        candidate_count=3,
                        idk_streak=idk_streak,
                    ),
                    expected_question,
                )

    def test_exclusion_normalizes_remaining_candidates_and_falls_back_when_all_are_excluded(self):
        probabilities = [0.6, 0.3, 0.1]
        first_id = self.engine.fetishes[0]['id']
        second_id = self.engine.fetishes[1]['id']
        third_id = self.engine.fetishes[2]['id']
        normalized = engine_question_selection._exclude_and_normalize(
            self.engine,
            probabilities,
            {first_id},
        )
        self.assertEqual(normalized[0], 0.0)
        self.assertAlmostEqual(sum(normalized), 1.0)
        self.assertAlmostEqual(normalized[1], 0.75)
        self.assertAlmostEqual(normalized[2], 0.25)
        fallback = engine_question_selection._exclude_and_normalize(
            self.engine,
            probabilities,
            {fetish['id'] for fetish in self.engine.fetishes},
        )
        self.assertEqual(fallback, probabilities)
        self.assertNotIn(second_id, {first_id, third_id})


class TestBestDisambiguatingQuestionPenalties(unittest.TestCase):
    def test_penalizes_similarity_to_an_asked_question(self):
        engine = _DisambiguationEngine(
            [
                [0.9, 0.1],  # already asked
                [0.9, 0.1],  # equally discriminating, but repeats the same direction
                [0.1, 0.9],  # equally discriminating in the opposite direction
            ]
        )

        question_id = engine_question_selection.best_disambiguating_question(
            engine,
            {},
            [0],
            candidate_count=2,
        )

        self.assertEqual(question_id, 2)

    def test_penalizes_a_recently_repeated_category(self):
        engine = _DisambiguationEngine(
            [
                [0.5, 0.5],  # neutral asked questions avoid a similarity side effect
                [0.5, 0.5],
                [0.9, 0.1],  # same raw score as question 3, repeated category
                [0.9, 0.1],  # fresh category
            ],
            categories={0: 'relation', 1: 'relation', 2: 'relation', 3: 'world'},
        )

        question_id = engine_question_selection.best_disambiguating_question(
            engine,
            {},
            [0, 1],
            candidate_count=2,
        )

        self.assertEqual(question_id, 3)

    def test_penalizes_extreme_answer_balance_stats(self):
        engine = _DisambiguationEngine(
            [
                [0.9, 0.1],  # same raw score, but observed answers are one-sided
                [0.9, 0.1],
            ]
        )

        question_id = engine_question_selection.best_disambiguating_question(
            engine,
            {},
            [],
            candidate_count=2,
            question_balance_stats={
                0: {'answered': 20, 'yes_rate': 100.0},
                1: {'answered': 20, 'yes_rate': 50.0},
            },
        )

        self.assertEqual(question_id, 1)

    def test_avoids_the_axis_of_a_recent_idk_streak(self):
        engine = _DisambiguationEngine(
            [
                [0.5, 0.5],  # neutral asked questions avoid a similarity side effect
                [0.5, 0.5],
                [0.9, 0.1],  # same raw score, same axis as the idk streak
                [0.9, 0.1],  # fresh axis
            ],
            categories={0: 'asked-a', 1: 'asked-b', 2: 'candidate-a', 3: 'candidate-b'},
            axes={0: 'content', 1: 'content', 2: 'content', 3: 'personality'},
        )

        question_id = engine_question_selection.best_disambiguating_question(
            engine,
            {'0': 0, '1': 0},
            [0, 1],
            candidate_count=2,
            idk_streak=2,
        )

        self.assertEqual(question_id, 3)
