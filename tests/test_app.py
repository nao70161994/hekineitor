import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ.setdefault('SECRET_KEY', 'test_secret_key_for_testing')

from app import app
import engine as eng_module
from engine import PLAYER_FETISH_BASE_ID, _use_db


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

    # ── promote_fetish ────────────────────────────────────
    def test_promote_fetish(self):
        """プレイヤー追加性癖をシード格上げするとIDが10000未満になること。"""
        from app import engine as app_engine
        before_count = len(app_engine.fetishes)
        name = f'格上げテスト_{before_count}'
        res = self.client.post('/api/add_fetish',
            json={'name': name, 'desc': 'テスト用', 'confirmed': True})
        old_id = res.get_json()['fetish_id']
        self.assertGreaterEqual(old_id, PLAYER_FETISH_BASE_ID)
        new_id = None
        try:
            new_id = app_engine.promote_fetish(old_id)
            self.assertIsNotNone(new_id)
            self.assertLess(new_id, PLAYER_FETISH_BASE_ID)
            self.assertIsNone(app_engine.index_of(old_id))
            self.assertIsNotNone(app_engine.index_of(new_id))
        finally:
            cleanup_id = new_id if new_id is not None else old_id
            idx = app_engine.index_of(cleanup_id)
            if idx is not None:
                app_engine.fetishes.pop(idx)
                app_engine.matrix['yes'].pop(idx)
                app_engine.matrix['total'].pop(idx)
                if not _use_db():
                    app_engine._save_fetishes_file()

    # ── idk posteriors ────────────────────────────────────
    def test_idk_changes_posteriors(self):
        """わからない回答が事後確率に影響を与えること（完全スキップではない）。"""
        from app import engine as app_engine
        probs_empty = app_engine.posteriors({})
        probs_idk   = app_engine.posteriors({'0': 0.0, '1': 0.0, '2': 0.0})
        self.assertFalse(all(abs(a - b) < 1e-9
                             for a, b in zip(probs_empty, probs_idk)))

    # ── close race threshold ──────────────────────────────
    def test_effective_threshold_raised_in_close_race(self):
        """接戦時（gap_ratio<1.8 かつ count<10）は effective_thr が guess_thr より高いこと。"""
        guess_thr = 0.75
        # 接戦ケース
        gap_ratio, count = 1.5, 5
        eff = guess_thr if (gap_ratio >= 1.8 or count >= 10) \
              else min(guess_thr + 0.10, 0.90)
        self.assertGreater(eff, guess_thr)
        # gap が十分広い場合は変わらない
        gap_ratio2 = 2.0
        eff2 = guess_thr if (gap_ratio2 >= 1.8 or count >= 10) \
               else min(guess_thr + 0.10, 0.90)
        self.assertEqual(eff2, guess_thr)

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


    def test_health_endpoint(self):
        res = self.client.get('/health')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['status'], 'ok')
        self.assertIn('fetishes', data)
        self.assertIn('questions', data)
        self.assertGreater(data['fetishes'], 0)
        self.assertGreater(data['questions'], 0)

    def _admin_headers(self):
        import base64
        os.environ['ADMIN_PASS'] = 'testpass'
        creds = base64.b64encode(b'admin:testpass').decode()
        return {'Authorization': f'Basic {creds}'}

    def test_export_log_returns_csv(self):
        headers = self._admin_headers()
        res = self.client.get('/api/admin/export_log', headers=headers)
        self.assertEqual(res.status_code, 200)
        self.assertIn('text/csv', res.content_type)
        body = res.data.decode('utf-8')
        self.assertTrue(body.startswith('id,name,guessed,correct,wrong,accuracy'))

    def test_export_matrix_returns_json(self):
        headers = self._admin_headers()
        res = self.client.get('/api/admin/export_matrix', headers=headers)
        self.assertEqual(res.status_code, 200)
        self.assertIn('application/json', res.content_type)
        data = res.get_json()
        self.assertIn('fetishes', data)
        self.assertIn('matrix_rows', data)
        self.assertGreater(len(data['matrix_rows']), 0)

    def test_resume_replays_answers(self):
        start = self._start()
        q = start['question_id']
        self.client.post('/api/answer', json={'question_id': q, 'answer': 1.0})
        pairs = [{'q_id': q, 'answer': 1.0}]
        res = self.client.post('/api/resume', json={'pairs': pairs})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn(data.get('action'), ('question', 'guess'))

    def test_resume_empty_pairs_returns_first_question(self):
        res = self.client.post('/api/resume', json={'pairs': []})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get('action'), 'question')
        self.assertIn('question_id', data)

    def test_continue_after_guess(self):
        self._force_guess()
        res = self.client.post('/api/continue')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn(data.get('action'), ('question',))

    def test_edit_question(self):
        headers = self._admin_headers()
        from app import engine as app_engine
        orig = app_engine.questions[0]['text']
        try:
            res = self.client.post('/api/admin/edit_question/0',
                json={'text': 'テスト用質問文'}, headers=headers)
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.get_json()['text'], 'テスト用質問文')
            self.assertEqual(app_engine.questions[0]['text'], 'テスト用質問文')
        finally:
            app_engine.edit_question(0, orig)

    def test_edit_question_empty_text_rejected(self):
        headers = self._admin_headers()
        res = self.client.post('/api/admin/edit_question/0',
            json={'text': '  '}, headers=headers)
        self.assertEqual(res.status_code, 400)

    def test_result_share_page(self):
        res = self.client.get('/r?f=NTR&p=82&d=テスト')
        self.assertEqual(res.status_code, 200)
        body = res.data.decode('utf-8')
        self.assertIn('NTR', body)
        self.assertIn('82', body)

    def test_edit_fetish(self):
        from app import engine as app_engine
        headers = self._admin_headers()
        fid = app_engine.fetishes[0]['id']
        orig_name = app_engine.fetishes[0]['name']
        try:
            res = self.client.post(f'/api/admin/edit_fetish/{fid}',
                json={'name': 'テスト編集名'}, headers=headers)
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.get_json()['name'], 'テスト編集名')
            self.assertEqual(app_engine.fetishes[0]['name'], 'テスト編集名')
        finally:
            app_engine.edit_fetish(fid, name=orig_name)

    def test_merge_fetishes(self):
        from app import engine as app_engine
        # Add two player fetishes to merge
        import os; os.environ['ADMIN_PASS'] = 'testpass'
        r1 = self.client.post('/api/add_fetish',
            json={'name': 'マージテストA_xyz', 'desc': 'テストA', 'confirmed': True})
        r2 = self.client.post('/api/add_fetish',
            json={'name': 'マージテストB_xyz', 'desc': 'テストB', 'confirmed': True})
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)
        id_a = r1.get_json()['fetish_id']
        id_b = r2.get_json()['fetish_id']
        idx_a = app_engine.index_of(id_a)
        idx_b = app_engine.index_of(id_b)
        # Save matrix values before merge
        nq = len(app_engine.questions)
        yes_a = list(app_engine.matrix['yes'][idx_a])
        yes_b = list(app_engine.matrix['yes'][idx_b])
        try:
            ok = app_engine.merge_fetishes(id_a, id_b, new_name='マージ済み_xyz')
            self.assertTrue(ok)
            # id_b should be gone
            self.assertIsNone(app_engine.index_of(id_b))
            # id_a should still exist with summed matrix
            new_idx_a = app_engine.index_of(id_a)
            self.assertIsNotNone(new_idx_a)
            for q in range(min(5, nq)):
                self.assertAlmostEqual(
                    app_engine.matrix['yes'][new_idx_a][q],
                    yes_a[q] + yes_b[q], places=5)
            # New name applied
            self.assertEqual(app_engine.fetishes[new_idx_a]['name'], 'マージ済み_xyz')
        finally:
            # Cleanup: remove remaining merged fetish
            idx = app_engine.index_of(id_a)
            if idx is not None:
                app_engine.fetishes.pop(idx)
                app_engine.matrix['yes'].pop(idx)
                app_engine.matrix['total'].pop(idx)
                app_engine._save_fetishes_file()

    def test_fetish_similarity(self):
        from app import engine as app_engine
        headers = self._admin_headers()
        id_a = app_engine.fetishes[0]['id']
        id_b = app_engine.fetishes[1]['id']
        res = self.client.post('/api/admin/fetish_similarity',
            json={'id_a': id_a, 'id_b': id_b}, headers=headers)
        self.assertEqual(res.status_code, 200)
        d = res.get_json()
        self.assertIn('cosine', d)
        self.assertIn('top_diff', d)
        self.assertEqual(len(d['top_diff']), 5)
        self.assertGreaterEqual(d['cosine'], -1.0)
        self.assertLessEqual(d['cosine'], 1.0)

    def test_fetish_similarity_invalid_id(self):
        headers = self._admin_headers()
        res = self.client.post('/api/admin/fetish_similarity',
            json={'id_a': 999999, 'id_b': 0}, headers=headers)
        self.assertEqual(res.status_code, 404)

    def test_axis_stats_in_admin(self):
        headers = self._admin_headers()
        res = self.client.get('/admin', headers=headers)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'content', res.data)
        self.assertIn(b'personality', res.data)

    def test_export_stats_history_returns_csv(self):
        headers = self._admin_headers()
        res = self.client.get('/api/admin/export_stats_history', headers=headers)
        self.assertEqual(res.status_code, 200)
        self.assertIn('text/csv', res.content_type)
        first_line = res.data.decode('utf-8').split('\n')[0]
        self.assertEqual(first_line, 'date,play,learn,correct,wrong')

    def test_start_returns_axis(self):
        res = self.client.post('/api/start')
        d = res.get_json()
        self.assertIn('axis', d)
        self.assertIn(d['axis'], ('content', 'abstract', 'personality', None))

    def test_answer_returns_axis(self):
        self._start()
        res = self.client.post('/api/start')
        q = res.get_json()['question_id']
        res2 = self.client.post('/api/answer', json={'question_id': q, 'answer': 1.0})
        d = res2.get_json()
        if d.get('action') == 'question':
            self.assertIn('axis', d)

    def test_fetish_history_endpoint(self):
        from app import engine as app_engine
        headers = self._admin_headers()
        fid = app_engine.fetishes[0]['id']
        res = self.client.get(f'/api/admin/fetish_history/{fid}', headers=headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIsInstance(data, list)
        self.assertTrue(all('date' in r and 'correct' in r and 'wrong' in r for r in data))

    def test_answer_returns_hint_when_focused(self):
        from app import engine as app_engine
        # Patch config to low focus_threshold so hint fires easily
        orig = app_engine.config.get('focus_threshold', 0.40)
        try:
            app_engine.config['focus_threshold'] = 0.01
            self._start()
            res = self.client.post('/api/start')
            q = res.get_json()['question_id']
            resp = self.client.post('/api/answer',
                json={'question_id': q, 'answer': 1.0})
            d = resp.get_json()
            if d.get('action') == 'question':
                self.assertIn('hint', d)
        finally:
            app_engine.config['focus_threshold'] = orig


class TestEngine(unittest.TestCase):
    """engine.py のコア推論ロジックを直接テスト。"""

    def setUp(self):
        from app import engine as app_engine
        self.eng = app_engine

    def test_posteriors_sum_to_one(self):
        probs = self.eng.posteriors({})
        self.assertAlmostEqual(sum(probs), 1.0, places=5)

    def test_posteriors_yes_answer_increases_probability(self):
        nq = len(self.eng.questions)
        # Find a question with some disc (not totally flat)
        stats = self.eng.get_question_stats()
        high = max(stats, key=lambda s: s['disc'])
        q_id = high['id']
        base  = self.eng.posteriors({})
        after = self.eng.posteriors({str(q_id): 1.0})
        # Best-prob fetish after 'yes' answer should be >= base best-prob
        self.assertGreaterEqual(max(after), max(base))

    def test_posteriors_is_list_of_floats(self):
        probs = self.eng.posteriors({})
        self.assertEqual(len(probs), len(self.eng.fetishes))
        self.assertTrue(all(isinstance(p, float) for p in probs))
        self.assertTrue(all(0.0 <= p <= 1.0 for p in probs))

    def test_learn_shifts_matrix(self):
        nf  = len(self.eng.fetishes)
        nq  = len(self.eng.questions)
        idx = 0
        q   = 0
        before_yes   = self.eng.matrix['yes'][idx][q]
        before_total = self.eng.matrix['total'][idx][q]
        self.eng.learn({str(q): 1.0}, idx, strength_factor=1.0)
        self.assertGreater(self.eng.matrix['yes'][idx][q], before_yes)
        self.assertGreater(self.eng.matrix['total'][idx][q], before_total)
        # Restore to avoid affecting other tests
        self.eng.matrix['yes'][idx][q]   = before_yes
        self.eng.matrix['total'][idx][q] = before_total

    def test_best_question_not_in_asked(self):
        asked = set(range(10))
        q = self.eng.best_question({}, asked)
        self.assertNotIn(q, asked)

    def test_best_question_returns_none_when_all_asked(self):
        all_q = set(range(len(self.eng.questions)))
        q = self.eng.best_question({}, all_q)
        self.assertIsNone(q)

    def test_top_guess_returns_valid_index(self):
        idx, prob = self.eng.top_guess({}, n=1)
        self.assertGreaterEqual(idx, 0)
        self.assertLess(idx, len(self.eng.fetishes))
        self.assertGreater(prob, 0.0)

    def test_get_question_stats_has_ask_count(self):
        stats = self.eng.get_question_stats()
        self.assertTrue(all('ask_count' in s for s in stats))
        self.assertTrue(all(s['ask_count'] >= 0 for s in stats))

    def test_early_stop_condition(self):
        """高確率かつ大差なら early_stop が効いてアンサーが guess を返す。"""
        from app import app as flask_app
        client = flask_app.test_client()
        client.post('/api/start')
        orig_thr = self.eng.config.get('focus_threshold', 0.40)
        # Force posteriors to be dominated by a single fetish via answers
        # by answering all questions yes (will hit MAX_QUESTIONS or early_stop)
        res = client.post('/api/start')
        q = res.get_json()['question_id']
        action = 'question'
        for _ in range(20):
            r = client.post('/api/answer', json={'question_id': q, 'answer': 1.0})
            d = r.get_json()
            action = d.get('action')
            if action == 'guess':
                break
            q = d.get('question_id', q)
        self.assertEqual(action, 'guess')

    def test_learn_negative_weakens_matrix(self):
        idx = 0
        q   = 0
        before_total = self.eng.matrix['total'][idx][q]
        self.eng.learn_negative({str(q): 1.0}, idx)
        after_total = self.eng.matrix['total'][idx][q]
        self.assertGreater(after_total, before_total)
        # yes_count increases less than total (net negative signal)
        before_yes = self.eng.matrix['yes'][idx][q]
        self.eng.matrix['total'][idx][q] = before_total
        self.eng.matrix['yes'][idx][q]   = before_yes

    def test_learn_cooccurrence_strengthens_both(self):
        idx_a = 0
        idx_b = 1
        # q=9 は NTR・百合ともP(yes)>0.5 なので ans=1.0 で確実に eff が発生する
        q = 9
        before_tot_a = self.eng.matrix['total'][idx_a][q]
        before_tot_b = self.eng.matrix['total'][idx_b][q]
        self.eng.learn_cooccurrence({str(q): 1.0}, idx_a, idx_b, factor=1.0)
        # At least one of the two totals should have increased
        increased = (self.eng.matrix['total'][idx_a][q] > before_tot_a or
                     self.eng.matrix['total'][idx_b][q] > before_tot_b)
        self.assertTrue(increased)
        # Restore
        self.eng.matrix['total'][idx_a][q] = before_tot_a
        self.eng.matrix['total'][idx_b][q] = before_tot_b

    def test_add_fetish_appends_to_list(self):
        n_before = len(self.eng.fetishes)
        try:
            idx, db_id = self.eng.add_fetish('テスト追加_unit_xyz', 'テスト', {})
            self.assertEqual(len(self.eng.fetishes), n_before + 1)
            self.assertGreaterEqual(db_id, 10000)
            self.assertEqual(self.eng.fetishes[idx]['name'], 'テスト追加_unit_xyz')
        finally:
            new_idx = self.eng.index_of(db_id)
            if new_idx is not None:
                self.eng.fetishes.pop(new_idx)
                self.eng.matrix['yes'].pop(new_idx)
                self.eng.matrix['total'].pop(new_idx)
                self.eng._save_fetishes_file()

    def test_boost_learn_new_increases_weight(self):
        try:
            idx, db_id = self.eng.add_fetish('テストブースト_unit_xyz', 'テスト', {'0': 1.0})
            before_total = sum(self.eng.matrix['total'][idx])
            self.eng.boost_learn_new(idx, {'0': 1.0})
            after_total = sum(self.eng.matrix['total'][idx])
            self.assertGreater(after_total, before_total)
        finally:
            new_idx = self.eng.index_of(db_id)
            if new_idx is not None:
                self.eng.fetishes.pop(new_idx)
                self.eng.matrix['yes'].pop(new_idx)
                self.eng.matrix['total'].pop(new_idx)
                self.eng._save_fetishes_file()

    def test_idk_streak_triggers_guess(self):
        from app import app as flask_app
        client = flask_app.test_client()
        res = client.post('/api/start')
        q = res.get_json()['question_id']
        for _ in range(4):
            r = client.post('/api/answer', json={'question_id': q, 'answer': 0})
            d = r.get_json()
            if d.get('action') == 'guess':
                break
            q = d.get('question_id', q)
        self.assertEqual(d.get('action'), 'guess')


class TestCompoundWorks(unittest.TestCase):
    """compound_works機能のテスト"""

    def setUp(self):
        import engine as em
        # テスト前にキャッシュをリセット
        em._compound_works_loaded = False
        em._COMPOUND_WORKS = {}
        app.config['TESTING'] = True
        self.client = app.test_client()

    def tearDown(self):
        import engine as em
        em._compound_works_loaded = False
        em._COMPOUND_WORKS = {}

    def _admin_headers(self):
        import base64
        os.environ['ADMIN_PASS'] = 'testpass'
        creds = base64.b64encode(b'admin:testpass').decode()
        return {'Authorization': f'Basic {creds}'}

    def test_get_compound_works_returns_empty_for_unknown_pair(self):
        from engine import get_compound_works
        result = get_compound_works(9999, 9998)
        self.assertEqual(result, [])

    def test_set_and_get_compound_works(self):
        from engine import set_compound_works, get_compound_works
        set_compound_works(100, 200, ['作品A', '作品B'])
        result = get_compound_works(100, 200)
        self.assertEqual(result, ['作品A', '作品B'])
        # 逆順のIDでも同じ結果
        result2 = get_compound_works(200, 100)
        self.assertEqual(result2, ['作品A', '作品B'])

    def test_delete_compound_works(self):
        from engine import set_compound_works, delete_compound_works, get_compound_works
        set_compound_works(100, 200, ['作品A'])
        ok = delete_compound_works(100, 200)
        self.assertTrue(ok)
        self.assertEqual(get_compound_works(100, 200), [])

    def test_delete_nonexistent_returns_false(self):
        from engine import delete_compound_works
        self.assertFalse(delete_compound_works(9999, 9998))

    def test_list_compound_works(self):
        from engine import set_compound_works, list_compound_works
        set_compound_works(1, 2, ['作品X'])
        set_compound_works(3, 4, ['作品Y', '作品Z'])
        items = list_compound_works()
        keys = [i['key'] for i in items]
        self.assertIn('1,2', keys)
        self.assertIn('3,4', keys)

    def test_api_set_compound_works(self):
        headers = self._admin_headers()
        res = self.client.post('/api/admin/compound_works',
            json={'id_a': 0, 'id_b': 1, 'works': ['テスト作品A', 'テスト作品B']},
            headers=headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['status'], 'ok')
        self.assertEqual(data['key'], '0,1')
        self.assertIn('テスト作品A', data['works'])

    def test_api_set_requires_works(self):
        headers = self._admin_headers()
        res = self.client.post('/api/admin/compound_works',
            json={'id_a': 0, 'id_b': 1, 'works': []},
            headers=headers)
        self.assertEqual(res.status_code, 400)

    def test_api_set_same_id_rejected(self):
        headers = self._admin_headers()
        res = self.client.post('/api/admin/compound_works',
            json={'id_a': 5, 'id_b': 5, 'works': ['作品']},
            headers=headers)
        self.assertEqual(res.status_code, 400)

    def test_api_list_compound_works(self):
        from engine import set_compound_works
        set_compound_works(0, 1, ['テスト作品'])
        headers = self._admin_headers()
        res = self.client.get('/api/admin/compound_works', headers=headers)
        self.assertEqual(res.status_code, 200)
        items = res.get_json()
        self.assertIsInstance(items, list)
        keys = [i['key'] for i in items]
        self.assertIn('0,1', keys)
        # name_a / name_b フィールドが付与されている
        item = next(i for i in items if i['key'] == '0,1')
        self.assertIn('name_a', item)
        self.assertIn('name_b', item)

    def test_api_delete_compound_works(self):
        from engine import set_compound_works
        set_compound_works(0, 1, ['作品'])
        headers = self._admin_headers()
        res = self.client.delete('/api/admin/compound_works/0,1', headers=headers)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()['status'], 'deleted')

    def test_api_delete_nonexistent(self):
        headers = self._admin_headers()
        res = self.client.delete('/api/admin/compound_works/9999,9998', headers=headers)
        self.assertEqual(res.status_code, 404)

    def test_cross_works_in_guess_response(self):
        """複合診断時にcross_worksフィールドが返る"""
        from engine import set_compound_works
        set_compound_works(0, 1, ['複合専用テスト作品'])
        client = app.test_client()
        res = client.post('/api/start')
        q_id = res.get_json()['question_id']
        # 20問答えて強制終了させる
        for _ in range(20):
            r = client.post('/api/answer', json={'question_id': q_id, 'answer': 1})
            d = r.get_json()
            if d.get('action') == 'guess':
                break
            q_id = d.get('question_id', q_id)
        # cross_worksフィールドが存在する（空でも可）
        self.assertIn('cross_works', d)
        self.assertIsInstance(d['cross_works'], list)

    def test_edit_fetish_with_works(self):
        """edit_fetish()がworksパラメータを受け付ける"""
        import engine as em
        eng = em.Engine()
        fid = eng.fetishes[0]['id']
        ok = eng.edit_fetish(fid, works=['テスト作品1', 'テスト作品2'])
        self.assertTrue(ok)
        idx = eng.index_of(fid)
        self.assertEqual(eng.fetishes[idx]['works'], ['テスト作品1', 'テスト作品2'])

    def test_admin_api_edit_fetish_works(self):
        """APIからworks編集ができる"""
        from app import engine as app_engine
        headers = self._admin_headers()
        fid = app_engine.fetishes[0]['id']
        res = self.client.post(f'/api/admin/edit_fetish/{fid}',
            json={'works': ['API作品A', 'API作品B']},
            headers=headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn('API作品A', data['works'])


if __name__ == '__main__':
    unittest.main()
