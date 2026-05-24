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
        self.assertIn('タイトルに戻る'.encode('utf-8'), res.data)

        res = self.client.post('/api/start')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn('question_id', data)

        qid = data['question_id']
        for _ in range(35):
            res = self.client.post('/api/answer', json={'question_id': qid, 'answer': 1})
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            if data.get('action') == 'guess':
                self.assertIn('fetish_id', data)
                self.assertIn('fetish_name', data)
                return
            self.assertEqual(data.get('action'), 'question')
            qid = data['question_id']
        self.fail('diagnosis did not reach a result within hard question limit')

    def test_resume_back_and_continue_flow(self):
        res = self.client.post('/api/start')
        self.assertEqual(res.status_code, 200)
        first = res.get_json()
        qid = first['question_id']

        res = self.client.post('/api/answer', json={'question_id': qid, 'answer': 1})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn(data.get('action'), {'question', 'guess'})

        resumed = app.test_client()
        res = resumed.post('/api/resume', json={'pairs': [{'q_id': qid, 'answer': 1}]})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn(data.get('action'), {'question', 'guess'})
        if data.get('action') == 'question':
            self.assertIn('question_id', data)
            back = resumed.post('/api/back')
            self.assertIn(back.status_code, {200, 440})
            cont = resumed.post('/api/continue')
            self.assertIn(cont.status_code, {200, 440})

    def test_feedback_share_and_pwa_browser_paths(self):
        from app import engine as app_engine
        res = self.client.get('/')
        self.assertEqual(res.status_code, 200)
        body = res.data.decode('utf-8')
        self.assertIn('id="quick-feedback"', body)
        self.assertIn('data-action="share-result"', body)
        self.assertIn('id="install-banner"', body)

        start = self.client.post('/api/start')
        self.assertEqual(start.status_code, 200)
        qid = start.get_json()['question_id']
        answer = self.client.post('/api/answer', json={'question_id': qid, 'answer': 1})
        self.assertEqual(answer.status_code, 200)
        feedback = self.client.post('/api/confirm', json={
            'correct': False,
            'fetish_id': app_engine.fetishes[0]['id'],
            'add_only': True,
        })
        self.assertEqual(feedback.status_code, 200)
        self.assertEqual(feedback.get_json().get('status'), 'wrong')

        share = self.client.get('/r?f=Browser&p=88&d=E2E')
        self.assertEqual(share.status_code, 200)
        self.assertIn(b'/ogp.png?f=Browser', share.data)

        ogp = self.client.get('/ogp.png?f=Browser&p=88')
        self.assertEqual(ogp.status_code, 200)
        self.assertEqual(ogp.mimetype, 'image/png')

        manifest = self.client.get('/manifest.json')
        self.assertEqual(manifest.status_code, 200)
        self.assertEqual(manifest.mimetype, 'application/manifest+json')

        sw = self.client.get('/sw.js')
        self.assertEqual(sw.status_code, 200)
        self.assertIn(b'self.addEventListener', sw.data)

        offline = self.client.get('/offline')
        self.assertEqual(offline.status_code, 200)


if __name__ == '__main__':
    unittest.main()
