import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ.setdefault('SECRET_KEY', 'test_secret_key_for_testing')

from app import app


class TestE2ESmoke(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        from app import engine as app_engine
        self._patches = [
            patch.object(app_engine, '_save_async', return_value=None),
            patch.object(app_engine, '_save_matrix_file', return_value=None),
            patch.object(app_engine, '_save_to_db', return_value=None),
            patch.object(app_engine, 'log_guessed', return_value=None),
            patch.object(app_engine, 'increment_play_count', return_value=None),
        ]
        for p in self._patches:
            p.start()
        self.client = app.test_client()

    def tearDown(self):
        for p in reversed(self._patches):
            p.stop()

    def test_start_answer_result_flow(self):
        res = self.client.get('/')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'data-action="start-game"', res.data)

        res = self.client.post('/api/start')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn('question_id', data)

        qid = data['question_id']
        for _ in range(25):
            res = self.client.post('/api/answer', json={'question_id': qid, 'answer': 1})
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            if data.get('action') == 'guess':
                self.assertIn('fetish_id', data)
                self.assertIn('fetish_name', data)
                return
            self.assertEqual(data.get('action'), 'question')
            qid = data['question_id']
        self.fail('diagnosis did not reach a result')


if __name__ == '__main__':
    unittest.main()
