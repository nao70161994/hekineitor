import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from engine import Engine

MATRIX_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'matrix.json')


class TestEngineQuestionSelectionRegression(unittest.TestCase):
    def setUp(self):
        self._matrix_backup = None
        if os.path.exists(MATRIX_PATH):
            with open(MATRIX_PATH, 'rb') as f:
                self._matrix_backup = f.read()
            os.remove(MATRIX_PATH)

        self._patches = [
            patch.object(Engine, '_save_matrix_file', return_value=None),
            patch.object(Engine, '_save_fetishes_file', return_value=None),
            patch.object(Engine, '_save_to_db', return_value=None),
            patch.object(Engine, 'get_fetish_log', return_value={}),
            patch('engine_question_selection.random.choice', side_effect=lambda pool: pool[0]),
        ]
        for patcher in self._patches:
            patcher.start()
        self.engine = Engine()

    def tearDown(self):
        for patcher in self._patches:
            patcher.stop()
        if self._matrix_backup is not None:
            with open(MATRIX_PATH, 'wb') as f:
                f.write(self._matrix_backup)

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
        self.assertTrue(question_selection.should_probe_low_exposure_axis(
            self.engine, answers, asked, count=4, top_p=top_p, second_p=second_p, hard_max_questions=30,
        ))
        question_id = question_selection.best_low_exposure_axis_question(self.engine, answers, asked)
        self.assertIsNotNone(question_id)
        self.assertIn(self.engine._question_category(question_id), {'attribute', 'world', 'aesthetic', 'value', 'role'})

    def test_best_disambiguating_question_snapshots(self):
        cases = [
            ({}, set(), 0, 2),
            ({'0': 0, '1': 0}, {0, 1}, 2, 2),
            ({'8': 1, '6': 1, '0': 1, '40': 1}, {0, 6, 8, 40}, 0, 2),
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
