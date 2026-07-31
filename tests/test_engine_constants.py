import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import engine
import engine_constants
import engine_data


class TestEngineConstantsCompatibility(unittest.TestCase):
    def test_engine_reexports_scalar_constants(self):
        names = [
            'PLAYER_FETISH_BASE_ID',
            'PSEUDO',
            'AXIS_INDIRECT_BONUS',
            'FOCUS_THRESHOLD',
            'FOCUS_TOP_N',
            'EARLY_RANDOM_DEPTH',
            'EARLY_RANDOM_TOP_K',
            'UCB_EXPLORE_C',
        ]
        for name in names:
            self.assertIs(getattr(engine, name), getattr(engine_constants, name))

    def test_constant_values_remain_stable(self):
        self.assertEqual(engine_constants.PLAYER_FETISH_BASE_ID, 10000)
        self.assertEqual(engine_constants.PSEUDO, 20)
        self.assertEqual(engine_constants.FOCUS_THRESHOLD, 0.40)
        self.assertEqual(engine_constants.FOCUS_TOP_N, 6)
        self.assertEqual(engine_constants.EARLY_RANDOM_DEPTH, 3)
        self.assertEqual(engine_constants.EARLY_RANDOM_TOP_K, 5)
        self.assertEqual(engine_constants.UCB_EXPLORE_C, 0.05)
        self.assertEqual(
            engine_constants.AXIS_INDIRECT_BONUS,
            {'content': 1.0, 'abstract': 1.01, 'personality': 1.02},
        )


class TestEngineLargeDataCompatibility(unittest.TestCase):
    def test_engine_reexports_large_data_constants(self):
        names = [
            'QUESTION_AXES',
            'DOMAIN_PRIORS',
            'FETISH_RELATIONS',
            'FETISH_PRIOR_WEIGHTS',
        ]
        for name in names:
            self.assertIs(getattr(engine, name), getattr(engine_data, name))

    def test_large_data_constant_shapes_remain_stable(self):
        self.assertEqual(len(engine_data.QUESTION_AXES), 8)
        self.assertGreater(len(engine_data.DOMAIN_PRIORS), 100)
        self.assertGreater(len(engine_data.FETISH_RELATIONS), 100)
        self.assertGreater(len(engine_data.FETISH_PRIOR_WEIGHTS), 50)
        self.assertEqual(engine_data.QUESTION_AXES[0], ('content', range(0, 55)))
        self.assertEqual(engine_data.QUESTION_AXES[-1], ('abstract', range(105, 153)))
        self.assertIn((0, 8, 0.95), engine_data.DOMAIN_PRIORS)
        self.assertEqual(engine_data.FETISH_RELATIONS[0], [20])
        self.assertEqual(engine_data.FETISH_PRIOR_WEIGHTS[0], 3.0)
        self.assertEqual(engine_data.FETISH_PRIOR_WEIGHTS[10], 3.0)
        self.assertEqual(engine_data.FETISH_PRIOR_WEIGHTS[23], 3.0)
        self.assertEqual(engine_data.FETISH_PRIOR_WEIGHTS[126], 1.0)
        self.assertEqual(engine_data.FETISH_PRIOR_WEIGHTS[127], 1.0)


class TestQuestionCategoryMetadata(unittest.TestCase):
    def test_all_questions_have_supported_categories(self):
        path = os.path.join(os.path.dirname(__file__), '..', 'data', 'questions.json')
        with open(path, encoding='utf-8') as file_obj:
            questions = json.load(file_obj)
        supported = {'relation', 'attachment', 'attribute', 'world', 'tone', 'value', 'role', 'aesthetic'}
        self.assertEqual(len(questions), 153)
        self.assertTrue(all(question.get('category') in supported for question in questions))
        counts = {category: 0 for category in supported}
        for question in questions:
            counts[question['category']] += 1
        for category in supported:
            self.assertGreater(counts[category], 0, category)
        supported_frames = {
            '作品・設定の好みとして',
            '人物・関係性の好みとして',
            '普段の感覚・行動として',
        }
        self.assertTrue(all(question.get('answer_frame') in supported_frames for question in questions))
        self.assertEqual({question['answer_frame'] for question in questions}, supported_frames)
        self.assertGreaterEqual(counts['attribute'], 1)
        self.assertGreaterEqual(counts['world'], 10)
        self.assertGreaterEqual(counts['aesthetic'], 10)

    def test_revised_indirect_questions_are_distinct_and_balanced(self):
        path = os.path.join(os.path.dirname(__file__), '..', 'data', 'questions.json')
        with open(path, encoding='utf-8') as file_obj:
            questions = json.load(file_obj)

        self.assertNotEqual(questions[2]['text'], questions[127]['text'])
        self.assertNotEqual(questions[138]['text'], questions[143]['text'])
        self.assertIn('終わり方が曖昧', questions[127]['text'])
        self.assertIn('行動の一貫性', questions[143]['text'])
        self.assertIn('片方が前に出る', questions[88]['text'])
        self.assertIn('穏やかな時間より困難', questions[92]['text'])
        self.assertIn('時間を置いて選ばれた言葉', questions[152]['text'])
        self.assertTrue(all('hint' not in question for question in questions))

        rewritten_ids = set(range(40, 55)) | set(range(93, 105)) | {
            13, 15, 25, 29, 108, 112, 126, 133, 142, 143, 144, 151, 152,
        }
        direct_result_terms = (
            'NTR', '寝取', '露出', '時間停止', 'クローン', '媚薬', '魔法少女',
            'ヤクザ', 'マフィア', '後宮', '宮廷', 'タイムループ', 'スパイ',
            '契約結婚', '探偵', 'ヤンキー', '社畜',
        )
        for question_id in rewritten_ids:
            self.assertFalse(
                any(term in questions[question_id]['text'] for term in direct_result_terms),
                questions[question_id]['text'],
            )
