import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ.setdefault('SECRET_KEY', 'test_secret_key_for_testing')

from app import app


class TestAPI(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        self.client = app.test_client()
        self.client.post('/api/start')

    def _start(self):
        res = self.client.post('/api/start')
        return res.get_json()

    def test_start_returns_question(self):
        data = self._start()
        self.assertIn('question_id', data)
        self.assertIn('question', data)
        self.assertEqual(data['count'], 0)

    def test_answer_yes(self):
        start = self._start()
        res = self.client.post('/api/answer',
            json={'question_id': start['question_id'], 'answer': 1.0})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn(data.get('action'), ('question', 'guess'))

    def test_answer_invalid_value(self):
        start = self._start()
        res = self.client.post('/api/answer',
            json={'question_id': start['question_id'], 'answer': 999})
        self.assertEqual(res.status_code, 400)

    def test_answer_missing_fields(self):
        res = self.client.post('/api/answer', json={'question_id': 0})
        self.assertEqual(res.status_code, 400)

    def test_answer_invalid_question_id(self):
        res = self.client.post('/api/answer',
            json={'question_id': 99999, 'answer': 1.0})
        self.assertEqual(res.status_code, 400)

    def test_back_no_history(self):
        self._start()
        res = self.client.post('/api/back')
        data = res.get_json()
        self.assertEqual(data['status'], 'no_history')

    def test_back_after_answer(self):
        start = self._start()
        self.client.post('/api/answer',
            json={'question_id': start['question_id'], 'answer': 1.0})
        res = self.client.post('/api/back')
        data = res.get_json()
        self.assertIn('question_id', data)
        self.assertIn('question', data)

    def test_back_no_duplicate_question(self):
        """back後に同じ質問が重複しないことを確認"""
        start = self._start()
        q0 = start['question_id']
        res1 = self.client.post('/api/answer',
            json={'question_id': q0, 'answer': 1.0})
        q1 = res1.get_json().get('question_id')
        self.client.post('/api/back')
        res2 = self.client.post('/api/answer',
            json={'question_id': q0, 'answer': 1.0})
        data2 = res2.get_json()
        if data2.get('action') == 'question':
            self.assertNotEqual(data2['question_id'], q0)

    def test_confirm_missing_fields(self):
        res = self.client.post('/api/confirm', json={'correct': True})
        self.assertEqual(res.status_code, 400)

    def test_confirm_invalid_fetish_id(self):
        res = self.client.post('/api/confirm',
            json={'correct': False, 'fetish_id': 99999})
        self.assertEqual(res.status_code, 400)

    def test_teach_invalid_fetish_id(self):
        res = self.client.post('/api/teach', json={'fetish_id': 99999})
        self.assertEqual(res.status_code, 400)

    def test_add_fetish_empty_name(self):
        res = self.client.post('/api/add_fetish', json={'name': ''})
        self.assertEqual(res.status_code, 400)

    def test_add_fetish_name_too_long(self):
        res = self.client.post('/api/add_fetish', json={'name': 'a' * 101})
        self.assertEqual(res.status_code, 400)

    def test_sw_js_served(self):
        res = self.client.get('/sw.js')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'hekineitor', res.data)

    def test_manifest_served(self):
        res = self.client.get('/manifest.json')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'standalone', res.data)


if __name__ == '__main__':
    unittest.main()
