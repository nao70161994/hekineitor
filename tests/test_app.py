import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ.setdefault('SECRET_KEY', 'test_secret_key_for_testing')

from app import app
import engine as eng_module
from engine import PLAYER_FETISH_BASE_ID


class TestAPI(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        self.client = app.test_client()
        self.client.post('/api/start')

    def _start(self):
        res = self.client.post('/api/start')
        return res.get_json()

    def _force_guess(self):
        """20問すべてに yes と答えて強制診断を得る"""
        start = self._start()
        q = start['question_id']
        for _ in range(20):
            res = self.client.post('/api/answer',
                json={'question_id': q, 'answer': 1.0})
            data = res.get_json()
            if data.get('action') == 'guess':
                return data
            q = data.get('question_id', q)
        return data

    # ── 基本フロー ─────────────────────────────────────────
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
        start = self._start()
        q0 = start['question_id']
        res1 = self.client.post('/api/answer',
            json={'question_id': q0, 'answer': 1.0})
        self.client.post('/api/back')
        res2 = self.client.post('/api/answer',
            json={'question_id': q0, 'answer': 1.0})
        data2 = res2.get_json()
        if data2.get('action') == 'question':
            self.assertNotEqual(data2['question_id'], q0)

    # ── confirm ────────────────────────────────────────────
    def test_confirm_missing_fields(self):
        res = self.client.post('/api/confirm', json={'correct': True})
        self.assertEqual(res.status_code, 400)

    def test_confirm_invalid_fetish_id(self):
        res = self.client.post('/api/confirm',
            json={'correct': False, 'fetish_id': 99999})
        self.assertEqual(res.status_code, 400)

    def test_confirm_correct_true_learns(self):
        res = self.client.post('/api/confirm',
            json={'correct': True, 'fetish_id': 0})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()['status'], 'learned')

    def test_confirm_correct_with_compound_ids(self):
        res = self.client.post('/api/confirm',
            json={'correct': True, 'fetish_id': 0, 'compound_ids': [10, 23]})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()['status'], 'learned')

    def test_confirm_wrong_returns_fetish_list(self):
        res = self.client.post('/api/confirm',
            json={'correct': False, 'fetish_id': 0, 'compound_ids': []})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['status'], 'wrong')
        self.assertIsInstance(data['fetishes'], list)
        self.assertLessEqual(len(data['fetishes']), 20)
        ids = [f['id'] for f in data['fetishes']]
        self.assertNotIn(0, ids)  # 診断済みは除外

    def test_confirm_wrong_excludes_compound(self):
        res = self.client.post('/api/confirm',
            json={'correct': False, 'fetish_id': 0, 'compound_ids': [10]})
        data = res.get_json()
        ids = [f['id'] for f in data['fetishes']]
        self.assertNotIn(0, ids)
        self.assertNotIn(10, ids)

    # ── teach ──────────────────────────────────────────────
    def test_teach_invalid_fetish_id(self):
        res = self.client.post('/api/teach', json={'fetish_id': 99999})
        self.assertEqual(res.status_code, 400)

    def test_teach_valid(self):
        res = self.client.post('/api/teach', json={'fetish_id': 0})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()['status'], 'learned')

    # ── add_fetish ─────────────────────────────────────────
    def test_add_fetish_empty_name(self):
        res = self.client.post('/api/add_fetish', json={'name': ''})
        self.assertEqual(res.status_code, 400)

    def test_add_fetish_name_too_long(self):
        res = self.client.post('/api/add_fetish', json={'name': 'a' * 101})
        self.assertEqual(res.status_code, 400)

    def test_add_fetish_existing_returns_learned(self):
        res = self.client.post('/api/add_fetish', json={'name': 'ヤンデレ'})
        data = res.get_json()
        self.assertEqual(data['status'], 'learned')
        self.assertEqual(data['fetish_name'], 'ヤンデレ')
        self.assertFalse(data['is_new'])

    def test_add_fetish_new_needs_desc_or_confirmed(self):
        res = self.client.post('/api/add_fetish', json={'name': 'テスト性癖XYZ_unique'})
        data = res.get_json()
        self.assertIn(data['status'], ('needs_desc', 'similar', 'learned'))

    def test_add_fetish_confirmed_creates_entry(self):
        from app import engine as app_engine
        before_count = len(app_engine.fetishes)
        name = f'テスト性癖確定_{before_count}'
        res = self.client.post('/api/add_fetish',
            json={'name': name, 'desc': 'テスト用', 'confirmed': True})
        data = res.get_json()
        self.assertEqual(data['status'], 'learned')
        self.assertTrue(data['is_new'])
        self.assertGreaterEqual(data['fetish_id'], PLAYER_FETISH_BASE_ID)
        # テスト後ロールバック（DB・JSONファイルも含む完全削除）
        app_engine.delete_fetish(data['fetish_id'])

    # ── finalize_added ─────────────────────────────────────
    def test_finalize_added_existing_fetish(self):
        res = self.client.post('/api/finalize_added',
            json={'items': [{'id': 0, 'is_new': False}]})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()['status'], 'done')

    def test_finalize_added_invalid_id_skipped(self):
        res = self.client.post('/api/finalize_added',
            json={'items': [{'id': 99999, 'is_new': False}]})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()['status'], 'done')

    def test_finalize_added_empty_items(self):
        res = self.client.post('/api/finalize_added', json={'items': []})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()['status'], 'done')

    # ── static ─────────────────────────────────────────────
    def test_sw_js_served(self):
        res = self.client.get('/sw.js')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'hekineitor', res.data)

    def test_manifest_served(self):
        res = self.client.get('/manifest.json')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'standalone', res.data)

    # ── exclude_ids ────────────────────────────────────────
    def test_start_with_exclude_ids(self):
        res = self.client.post('/api/start', json={'exclude_ids': [0, 1]})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn('question_id', data)

    def test_guess_excludes_ids(self):
        """exclude_ids に指定された性癖が1位になっていないことを診断で確認。"""
        from app import engine as app_engine
        excl = [app_engine.fetishes[0]['id']]
        # exclude_ids を指定してスタート（_start() は使わず直接呼ぶ）
        res = self.client.post('/api/start', json={'exclude_ids': excl})
        q = res.get_json()['question_id']
        data = None
        for _ in range(20):
            res = self.client.post('/api/answer',
                json={'question_id': q, 'answer': 1.0})
            data = res.get_json()
            if data.get('action') == 'guess':
                break
            q = data.get('question_id', q)
        if data and data.get('action') == 'guess':
            self.assertNotIn(data.get('fetish_id'), excl)

    # ── top_chart ──────────────────────────────────────────
    def test_guess_returns_top_chart(self):
        data = self._force_guess()
        if data.get('action') == 'guess':
            self.assertIn('top_chart', data)
            self.assertIsInstance(data['top_chart'], list)
            self.assertGreaterEqual(len(data['top_chart']), 1)
            self.assertIn('fetish_name', data['top_chart'][0])
            self.assertIn('probability', data['top_chart'][0])

    # ── early stop ratio ──────────────────────────────────
    def test_answer_loop_terminates(self):
        """20問以内に必ず guess が返ること。"""
        data = self._force_guess()
        self.assertEqual(data.get('action'), 'guess')

    # ── session expiry ────────────────────────────────────
    def test_answer_without_start_returns_440(self):
        """セッション未開始で answer を呼ぶと 440 が返ること。"""
        fresh = app.test_client()  # 新しいクライアント（セッションなし）
        res = fresh.post('/api/answer', json={'question_id': 0, 'answer': 1.0})
        self.assertEqual(res.status_code, 440)

    def test_back_without_start_returns_440(self):
        fresh = app.test_client()
        res = fresh.post('/api/back')
        self.assertEqual(res.status_code, 440)

    # ── question disable ──────────────────────────────────
    def test_disabled_question_not_asked(self):
        """無効化した質問が asked リストに含まれないこと。"""
        from app import engine as app_engine
        # Q0 を無効化
        app_engine.disabled_questions.add(0)
        try:
            start = self._start()
            q = start['question_id']
            asked = [q]
            for _ in range(10):
                res = self.client.post('/api/answer',
                    json={'question_id': q, 'answer': 1.0})
                d = res.get_json()
                if d.get('action') == 'guess':
                    break
                q = d.get('question_id', q)
                asked.append(q)
            self.assertNotIn(0, asked)
        finally:
            app_engine.disabled_questions.discard(0)

    # ── diagnosis log ─────────────────────────────────────
    def test_log_guessed_increments(self):
        from app import engine as app_engine
        log_before = app_engine.get_fetish_log()
        data = self._force_guess()
        if data.get('action') == 'guess':
            fid = data['fetish_id']
            log_after = app_engine.get_fetish_log()
            before = log_before.get(fid, {}).get('guessed', 0)
            after  = log_after.get(fid, {}).get('guessed', 0)
            self.assertGreater(after, before)

    def test_log_correct_increments(self):
        from app import engine as app_engine
        self._force_guess()
        log_before = app_engine.get_fetish_log()
        self.client.post('/api/confirm', json={'correct': True, 'fetish_id': 0})
        log_after = app_engine.get_fetish_log()
        before = log_before.get(0, {}).get('correct', 0)
        after  = log_after.get(0, {}).get('correct', 0)
        self.assertGreater(after, before)

    # ── finalize_added cooccurrence ───────────────────────
    def test_finalize_added_cooccurrence_learns_multiple(self):
        """finalize_added で複数性癖を渡すと両方が学習されること。"""
        from app import engine as app_engine
        start = self._start()
        q = start['question_id']
        self.client.post('/api/answer', json={'question_id': q, 'answer': 1.0})
        f0_id = app_engine.fetishes[0]['id']
        f1_id = app_engine.fetishes[1]['id']
        before0 = sum(app_engine.matrix['total'][0])
        before1 = sum(app_engine.matrix['total'][1])
        res = self.client.post('/api/finalize_added', json={
            'items': [{'id': f0_id, 'is_new': False}, {'id': f1_id, 'is_new': False}]
        })
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()['status'], 'done')
        self.assertGreater(sum(app_engine.matrix['total'][0]), before0)
        self.assertGreater(sum(app_engine.matrix['total'][1]), before1)

    # ── cooccurrence ──────────────────────────────────────
    def test_confirm_compound_correct_learns(self):
        """複合正解で2性癖が同時に学習されること。"""
        res = self.client.post('/api/confirm',
            json={'correct': True, 'fetish_id': 0, 'compound_ids': [1]})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()['status'], 'learned')

    def test_cooccurrence_does_not_crash(self):
        from app import engine as app_engine
        answers = {'0': 1.0, '1': -1.0}
        # same index → no-op
        app_engine.learn_cooccurrence(answers, 0, 0)
        # valid pair
        app_engine.learn_cooccurrence(answers, 0, 1)

    # ── server-side session ───────────────────────────────
    def test_session_persists_across_requests(self):
        """start → answer で answered question が引き継がれること。"""
        start = self._start()
        q = start['question_id']
        res = self.client.post('/api/answer',
            json={'question_id': q, 'answer': 1.0})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn(data.get('action'), ('question', 'guess'))


if __name__ == '__main__':
    unittest.main()
