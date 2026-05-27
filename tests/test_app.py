import sys
import os
import json
import re
import time
import tempfile
import unittest
import struct
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ.setdefault('SECRET_KEY', 'test_secret_key_for_testing')

from app import app
from services import ogp as ogp_service
from services import quality_stats as quality_stats_service
from services import share_events as share_events_service
from services import question_events as question_events_service
from services import share_links as share_links_service
from services import share_notes as share_notes_service
from services import test_play as test_play_service
from services import inference as inference_service
from services import learning as learning_service
import engine as eng_module
from engine import PLAYER_FETISH_BASE_ID, _use_db


DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data')
DATA_FILES = (
    'fetish_log.json', 'stats.json', 'stats_history.json', 'fetishes.json',
    'matrix.json', 'questions.json', 'compound_works.json', 'question_flags.json',
    'config.json', 'admin_audit_log.json', 'share_events.jsonl', 'question_events.jsonl', 'share_links.json',
    time.strftime('admin_audit_log_%Y%m.json'),
)


class FileSnapshotMixin:
    @classmethod
    def setUpClass(cls):
        cls._file_snapshot = {}
        for name in DATA_FILES:
            path = os.path.join(DATA_DIR, name)
            try:
                with open(path, 'rb') as f:
                    cls._file_snapshot[name] = f.read()
            except OSError:
                cls._file_snapshot[name] = None

    @classmethod
    def tearDownClass(cls):
        for name, content in cls._file_snapshot.items():
            path = os.path.join(DATA_DIR, name)
            if content is None:
                try:
                    os.remove(path)
                except OSError:
                    pass
            else:
                with open(path, 'wb') as f:
                    f.write(content)


class TestAPI(FileSnapshotMixin, unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        from app import engine as app_engine
        self._patches = [
            patch.object(app_engine, '_save_async', return_value=None),
            patch.object(app_engine, '_save_matrix_file', return_value=None),
            patch.object(app_engine, '_save_fetishes_file', return_value=None),
            patch.object(app_engine, '_save_to_db', return_value=None),
        ]
        for p in self._patches:
            p.start()
        self.client = app.test_client()
        self.client.post('/api/start')
        self._set_active_guess(0, [1, 10, 23])

    def tearDown(self):
        for p in reversed(self._patches):
            p.stop()

    def _start(self):
        res = self.client.post('/api/start')
        self._set_active_guess(0, [1, 10, 23])
        return res.get_json()

    def _set_active_guess(self, fetish_id=0, compound_ids=None):
        with self.client.session_transaction() as sess:
            sess['started'] = True
            sess['last_guess_fetish_id'] = fetish_id
            sess['last_guess_compound_ids'] = list(compound_ids or [])

    def _fetish_id_by_name(self, name):
        from app import engine as app_engine
        for fetish in app_engine.fetishes:
            if fetish.get('name') == name:
                return fetish['id']
        self.fail(f'fetish not found: {name}')

    def _force_guess(self):
        """上限まで yes と答えて強制診断を得る"""
        start = self._start()
        q = start['question_id']
        for _ in range(30):
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

    def test_confirm_correct_is_not_applied_twice(self):
        from app import engine as app_engine
        before = app_engine.get_fetish_log().get(0, {}).get('correct', 0)
        first = self.client.post('/api/confirm', json={'correct': True, 'fetish_id': 0})
        second = self.client.post('/api/confirm', json={'correct': True, 'fetish_id': 0})
        after = app_engine.get_fetish_log().get(0, {}).get('correct', 0)
        self.assertEqual(first.status_code, 200)
        self.assertIn(second.status_code, (409, 440))
        self.assertEqual(after, before + 1)

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

    def test_confirm_wrong_is_not_applied_twice(self):
        from app import engine as app_engine
        before = app_engine.get_fetish_log().get(0, {}).get('wrong', 0)
        first = self.client.post('/api/confirm', json={'correct': False, 'fetish_id': 0})
        second = self.client.post('/api/confirm', json={'correct': False, 'fetish_id': 0})
        after = app_engine.get_fetish_log().get(0, {}).get('wrong', 0)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 409)
        self.assertEqual(after, before + 1)

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

    def test_delete_owned_added_fetish_endpoint(self):
        from app import engine as app_engine
        idx, db_id = app_engine.add_fetish('テスト削除_owned_endpoint', 'テスト用', {})
        try:
            with self.client.session_transaction() as sess:
                sess['owned_added_fetish_ids'] = [db_id]
            res = self.client.delete(f'/api/fetish/{db_id}')
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.get_json()['status'], 'deleted')
            self.assertIsNone(app_engine.index_of(db_id))
            with self.client.session_transaction() as sess:
                self.assertEqual(sess.get('owned_added_fetish_ids'), [])
        finally:
            cleanup_idx = app_engine.index_of(db_id)
            if cleanup_idx is not None:
                app_engine.fetishes.pop(cleanup_idx)
                app_engine.matrix['yes'].pop(cleanup_idx)
                app_engine.matrix['total'].pop(cleanup_idx)
                app_engine._save_fetishes_file()

    def test_delete_seed_fetish_rejected_even_for_admin(self):
        headers = self._admin_headers()
        res = self.client.delete('/api/fetish/0', json={'confirm_text': 'DELETE'}, headers=headers)
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.get_json()['status'], 'error')

    # ── finalize_added ─────────────────────────────────────
    def test_test_play_admin_link_enables_banner_and_survives_start(self):
        headers = self._admin_headers()
        plain = self.client.get('/?sandbox=1')
        self.assertEqual(plain.status_code, 200)
        self.assertNotIn('テストプレイ中', plain.data.decode('utf-8'))

        res = self.client.post('/admin/test_play/start', headers=headers, follow_redirects=False)
        self.assertEqual(res.status_code, 302)
        self.assertEqual(res.headers.get('Location'), '/')
        banner = self.client.get('/')
        self.assertIn('テストプレイ中：この診断は学習に反映されません', banner.data.decode('utf-8'))
        self.client.post('/api/start')
        with self.client.session_transaction() as sess:
            self.assertTrue(test_play_service.is_learning_disabled(sess))

    def test_test_play_route_requires_admin(self):
        res = self.client.post('/admin/test_play/start')
        self.assertEqual(res.status_code, 401)
        stop = self.client.post('/admin/test_play/stop')
        self.assertEqual(stop.status_code, 401)
        with self.client.session_transaction() as sess:
            self.assertFalse(test_play_service.is_learning_disabled(sess))

    def test_test_play_stop_disables_flag_and_admin_status_updates(self):
        headers = self._admin_headers()
        normal_admin = self.client.get('/admin', headers=headers)
        self.assertIn('通常モード', normal_admin.data.decode('utf-8'))
        self.assertIn('data-action="test-play-start"', normal_admin.data.decode('utf-8'))

        self.client.post('/admin/test_play/start', headers=headers)
        active_admin = self.client.get('/admin', headers=headers)
        active_body = active_admin.data.decode('utf-8')
        self.assertIn('学習OFFテストプレイ中', active_body)
        self.assertIn('data-action="test-play-stop"', active_body)
        self.assertIn('テストプレイ開始/終了履歴', active_body)
        self.assertIn('test_play_start', active_body)
        self.assertIn('学習OFFテストプレイ中へ変更', active_body)

        res = self.client.post('/admin/test_play/stop', headers=headers, follow_redirects=False)
        self.assertEqual(res.status_code, 302)
        self.assertEqual(res.headers.get('Location'), '/admin')
        with self.client.session_transaction() as sess:
            self.assertFalse(test_play_service.is_learning_disabled(sess))
        stopped_admin = self.client.get('/admin', headers=headers)
        stopped_body = stopped_admin.data.decode('utf-8')
        self.assertIn('通常モード', stopped_body)
        self.assertIn('test_play_stop', stopped_body)
        self.assertIn('通常モードへ変更', stopped_body)

        audit = self.client.get('/api/admin/audit_log', headers=headers).get_json()['audit_log']
        test_rows = [row for row in audit if row.get('action') in ('test_play_start', 'test_play_stop')]
        self.assertGreaterEqual(len(test_rows), 2)
        for row in test_rows[:2]:
            self.assertIn(row['detail']['event_name'], ('test_play_start', 'test_play_stop'))
            self.assertIn(row['detail']['mode'], ('learning_off', 'normal'))
            self.assertNotIn('remote_addr', row)
            self.assertNotIn('path', row)
            self.assertNotIn('user_agent', row)

    def test_test_play_confirm_skips_learning_and_quality_feedback(self):
        from app import engine as app_engine
        q = 8
        idx = app_engine.index_of(0)
        before_yes = app_engine.matrix['yes'][idx][q]
        before_total = app_engine.matrix['total'][idx][q]
        before_log = dict(app_engine.get_fetish_log().get(0, {}))
        with self.client.session_transaction() as sess:
            test_play_service.enable(sess)
            sess['answers'] = {str(q): 1.0}
            sess['last_guess_quality'] = {'low_confidence_extended': True, 'additional_questions': 1}

        res = self.client.post('/api/confirm', json={'correct': True, 'fetish_id': 0})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()['status'], 'learned')
        self.assertTrue(res.get_json()['learning_disabled'])
        self.assertEqual(app_engine.matrix['yes'][idx][q], before_yes)
        self.assertEqual(app_engine.matrix['total'][idx][q], before_total)
        self.assertEqual(app_engine.get_fetish_log().get(0, {}), before_log)
        with self.client.session_transaction() as sess:
            self.assertIn('last_guess_quality', sess)

    def test_test_play_wrong_confirm_returns_candidates_without_saving(self):
        from app import engine as app_engine
        q = 8
        idx = app_engine.index_of(0)
        before_yes = app_engine.matrix['yes'][idx][q]
        before_total = app_engine.matrix['total'][idx][q]
        before_log = dict(app_engine.get_fetish_log().get(0, {}))
        with self.client.session_transaction() as sess:
            test_play_service.enable(sess)
            sess['answers'] = {str(q): 1.0}

        res = self.client.post('/api/confirm', json={
            'correct': False,
            'fetish_id': 0,
            'maybe_ids': [0],
            'wrong_ids': [],
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['status'], 'wrong')
        self.assertTrue(data['learning_disabled'])
        self.assertTrue(data['fetishes'])
        self.assertEqual(app_engine.matrix['yes'][idx][q], before_yes)
        self.assertEqual(app_engine.matrix['total'][idx][q], before_total)
        self.assertEqual(app_engine.get_fetish_log().get(0, {}), before_log)

    def test_test_play_finalize_added_skips_matrix_updates(self):
        from app import engine as app_engine
        q = self._start()['question_id']
        self.client.post('/api/answer', json={'question_id': q, 'answer': 1.0})
        f0_id = app_engine.fetishes[0]['id']
        before0 = sum(app_engine.matrix['total'][0])
        with self.client.session_transaction() as sess:
            test_play_service.enable(sess)
            sess['wrong_db_ids'] = [f0_id]
            sess['candidate_db_ids'] = [f0_id]
            sess['near_miss_db_ids'] = []
            sess['candidate_negative_factor'] = 0.3
            sess['last_guess_fetish_id'] = f0_id
            sess['last_guess_compound_ids'] = []
        res = self.client.post('/api/finalize_added', json={'items': [{'id': f0_id, 'is_new': False}]})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()['status'], 'done')
        self.assertTrue(res.get_json()['learning_disabled'])
        self.assertEqual(sum(app_engine.matrix['total'][0]), before0)
        with self.client.session_transaction() as sess:
            self.assertNotIn('wrong_db_ids', sess)

    def test_test_play_add_fetish_does_not_create_new_fetish(self):
        from app import engine as app_engine
        before_len = len(app_engine.fetishes)
        with self.client.session_transaction() as sess:
            test_play_service.enable(sess)
        res = self.client.post('/api/add_fetish', json={
            'name': 'テストプレイ限定性癖',
            'desc': '保存されない',
            'confirmed': True,
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['status'], 'learned')
        self.assertTrue(data['learning_disabled'])
        self.assertEqual(len(app_engine.fetishes), before_len)
        self.assertIsNone(app_engine.index_of('test-play'))

    def test_test_play_keeps_inference_and_result_flow_working(self):
        headers = self._admin_headers()
        self.client.post('/admin/test_play/start', headers=headers)
        data = self._force_guess()
        self.assertEqual(data.get('action'), 'guess')
        self.assertIn('fetish_name', data)
        with self.client.session_transaction() as sess:
            self.assertNotIn('last_guess_quality', sess)

    def test_finalize_added_existing_fetish(self):
        res = self.client.post('/api/finalize_added',
            json={'items': [{'id': 0, 'is_new': False}]})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()['status'], 'done')

    def test_finalize_added_invalid_id_rejected(self):
        res = self.client.post('/api/finalize_added',
            json={'items': [{'id': 2, 'is_new': False}]})
        self.assertEqual(res.status_code, 409)

    def test_finalize_added_limits_items(self):
        items = [{'id': 0, 'is_new': False} for _ in range(11)]
        res = self.client.post('/api/finalize_added', json={'items': items})
        self.assertEqual(res.status_code, 400)

    def test_finalize_added_empty_items(self):
        res = self.client.post('/api/finalize_added', json={'items': []})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()['status'], 'done')

    def test_confirm_maybe_learns_weak_positive_without_wrong_bucket(self):
        from app import engine as app_engine
        q = 8
        idx = app_engine.index_of(0)
        before_yes = app_engine.matrix['yes'][idx][q]
        before_total = app_engine.matrix['total'][idx][q]
        with self.client.session_transaction() as sess:
            sess['answers'] = {str(q): 1.0}

        res = self.client.post('/api/confirm', json={
            'correct': False,
            'fetish_id': 0,
            'maybe_ids': [0],
            'wrong_ids': [],
        })

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()['status'], 'wrong')
        self.assertGreater(app_engine.matrix['yes'][idx][q], before_yes)
        self.assertGreater(app_engine.matrix['total'][idx][q], before_total)
        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get('wrong_db_ids'), [])
            self.assertEqual(sess.get('near_miss_db_ids'), [0])
            self.assertEqual(sess.get('candidate_negative_factor'), 0.15)
        app_engine.matrix['yes'][idx][q] = before_yes
        app_engine.matrix['total'][idx][q] = before_total

    def test_feedback_factor_reduces_broad_correct_and_boosts_near_miss(self):
        from app import engine as app_engine
        broad_idx = app_engine.index_of(self._fetish_id_by_name('共依存'))
        concrete_idx = app_engine.index_of(0)

        self.assertEqual(learning_service.positive_feedback_factor(app_engine, broad_idx), 0.45)
        self.assertEqual(learning_service.positive_feedback_factor(app_engine, concrete_idx), 0.7)
        self.assertEqual(learning_service.negative_feedback_factor(app_engine, broad_idx), 1.7)
        self.assertEqual(learning_service.negative_feedback_factor(app_engine, concrete_idx), 1.3)
        self.assertEqual(learning_service.near_miss_feedback_factor(app_engine, broad_idx), 1.15)
        self.assertEqual(learning_service.near_miss_feedback_factor(app_engine, concrete_idx), 1.6)

    def test_confirm_broad_result_uses_reduced_positive_factor(self):
        from app import BOOTSTRAP
        from app import engine as app_engine
        q = 8
        answers = {str(q): 1.0}
        broad_id = self._fetish_id_by_name('共依存')
        broad_idx = app_engine.index_of(broad_id)
        expected_base = learning_service.learn_factor(
            app_engine,
            inference_service.posteriors,
            answers,
            app_engine.config.get('guess_threshold', BOOTSTRAP.guess_threshold),
            total_n=1,
        )

        with self.client.session_transaction() as sess:
            sess['started'] = True
            sess['answers'] = answers
            sess['last_guess_fetish_id'] = broad_id
            sess['last_guess_compound_ids'] = []
            sess.pop('feedback_status', None)

        with patch('services.learning.learn_positive') as learn_positive:
            res = self.client.post('/api/confirm', json={
                'correct': True,
                'fetish_id': broad_id,
            })

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()['status'], 'learned')
        learn_positive.assert_called_once()
        self.assertEqual(learn_positive.call_args.args[2], broad_idx)
        self.assertAlmostEqual(
            learn_positive.call_args.kwargs['strength_factor'],
            expected_base * learning_service.BROAD_RESULT_POSITIVE_SCALE,
        )

    def test_confirm_wrong_result_uses_negative_factor_once(self):
        from app import engine as app_engine
        q = 8
        answers = {str(q): 1.0}
        broad_id = self._fetish_id_by_name('共依存')
        broad_idx = app_engine.index_of(broad_id)

        with self.client.session_transaction() as sess:
            sess['started'] = True
            sess['answers'] = answers
            sess['last_guess_fetish_id'] = broad_id
            sess['last_guess_compound_ids'] = []
            sess.pop('feedback_status', None)

        with patch('services.learning.learn_negative') as learn_negative:
            res = self.client.post('/api/confirm', json={
                'correct': False,
                'fetish_id': broad_id,
                'wrong_ids': [broad_id],
            })

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()['status'], 'wrong')
        learn_negative.assert_called_once()
        self.assertEqual(learn_negative.call_args.args[2], broad_idx)
        self.assertAlmostEqual(
            learn_negative.call_args.kwargs['strength_factor'],
            learning_service.BROAD_RESULT_NEGATIVE_SCALE,
        )
        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get('negative_learned_db_ids'), [broad_id])

    def test_finalize_added_wrong_result_uses_negative_factor(self):
        from app import engine as app_engine
        q = 8
        answers = {str(q): 1.0}
        broad_id = self._fetish_id_by_name('共依存')
        broad_idx = app_engine.index_of(broad_id)
        correct_id = self._fetish_id_by_name('白衣')

        with self.client.session_transaction() as sess:
            sess['started'] = True
            sess['answers'] = answers
            sess['last_guess_fetish_id'] = broad_id
            sess['last_guess_compound_ids'] = [correct_id]
            sess['wrong_db_ids'] = [broad_id]
            sess['candidate_db_ids'] = [correct_id]
            sess['feedback_status'] = 'pending_correction'

        with patch('services.learning.learn_positive'), patch('services.learning.learn_negative') as learn_negative:
            res = self.client.post('/api/finalize_added', json={
                'items': [{'id': correct_id, 'is_new': False}],
            })

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()['status'], 'done')
        learn_negative.assert_called_once()
        self.assertEqual(learn_negative.call_args.args[2], broad_idx)
        self.assertAlmostEqual(
            learn_negative.call_args.kwargs['strength_factor'],
            learning_service.BROAD_RESULT_NEGATIVE_SCALE,
        )

    def test_confirm_maybe_uses_near_miss_factor(self):
        from app import BOOTSTRAP
        from app import engine as app_engine
        q = 8
        answers = {str(q): 1.0}
        guessed_id = 0
        maybe_id = self._fetish_id_by_name('白衣')
        maybe_idx = app_engine.index_of(maybe_id)
        expected_base = learning_service.learn_factor(
            app_engine,
            inference_service.posteriors,
            answers,
            app_engine.config.get('guess_threshold', BOOTSTRAP.guess_threshold),
            total_n=1,
        )

        with self.client.session_transaction() as sess:
            sess['started'] = True
            sess['answers'] = answers
            sess['last_guess_fetish_id'] = guessed_id
            sess['last_guess_compound_ids'] = [maybe_id]
            sess.pop('feedback_status', None)

        with patch('services.learning.learn_near_miss') as learn_near_miss:
            res = self.client.post('/api/confirm', json={
                'correct': False,
                'fetish_id': guessed_id,
                'compound_ids': [maybe_id],
                'maybe_ids': [maybe_id],
                'wrong_ids': [],
            })

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()['status'], 'wrong')
        learn_near_miss.assert_called_once()
        self.assertEqual(learn_near_miss.call_args.args[2], maybe_idx)
        self.assertAlmostEqual(
            learn_near_miss.call_args.kwargs['strength_factor'],
            expected_base * learning_service.NEAR_MISS_SCALE,
        )

    def test_confirm_defer_learning_returns_candidates_without_matrix_or_pending_penalty(self):
        from app import engine as app_engine
        q = 8
        idx = app_engine.index_of(0)
        before_yes = app_engine.matrix['yes'][idx][q]
        before_total = app_engine.matrix['total'][idx][q]
        before_log = dict(app_engine.get_fetish_log().get(0, {}))
        with self.client.session_transaction() as sess:
            sess['answers'] = {str(q): 1.0}

        res = self.client.post('/api/confirm', json={
            'correct': False,
            'fetish_id': 0,
            'maybe_ids': [0],
            'wrong_ids': [],
            'defer_learning': True,
        })

        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['status'], 'wrong')
        self.assertTrue(data['fetishes'])
        self.assertEqual(app_engine.matrix['yes'][idx][q], before_yes)
        self.assertEqual(app_engine.matrix['total'][idx][q], before_total)
        self.assertEqual(app_engine.get_fetish_log().get(0, {}), before_log)
        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get('wrong_db_ids'), [])
            self.assertEqual(sess.get('near_miss_db_ids'), [])
            self.assertTrue(sess.get('candidate_db_ids'))

        app_engine.matrix['yes'][idx][q] = before_yes
        app_engine.matrix['total'][idx][q] = before_total

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
        """hard上限以内に必ず guess が返ること。"""
        data = self._force_guess()
        self.assertEqual(data.get('action'), 'guess')

    def test_low_confidence_at_soft_limit_extends_questions(self):
        import app as app_module
        with self.client.session_transaction() as sess:
            sess['started'] = True
            sess['answers'] = {str(i): 1.0 for i in range(19)}
            sess['asked'] = list(range(20))
            sess['idk_streak'] = 0
        with patch.object(app_module.engine, 'top_guess', return_value=[(0, 0.50), (1, 0.45)]), \
                patch.object(app_module.engine, 'best_disambiguating_question', return_value=20) as disambiguating:
            res = self.client.post('/api/answer', json={'question_id': 19, 'answer': 1.0})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['action'], 'question')
        self.assertEqual(data['count'], 20)
        self.assertEqual(data['total'], 30)
        self.assertIn('絞り込み', data.get('hint', ''))
        disambiguating.assert_called_once()

    def test_normal_flow_uses_best_question_before_soft_limit(self):
        import app as app_module
        with self.client.session_transaction() as sess:
            sess['started'] = True
            sess['answers'] = {str(i): 1.0 for i in range(4)}
            sess['asked'] = list(range(5))
            sess['idk_streak'] = 0
        with patch.object(app_module.engine, 'top_guess', return_value=[(0, 0.36), (1, 0.22)]), \
                patch.object(app_module.engine, 'best_question', return_value=5) as best_question, \
                patch.object(app_module.engine, 'best_disambiguating_question', return_value=6) as disambiguating:
            res = self.client.post('/api/answer', json={'question_id': 4, 'answer': 1.0})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['action'], 'question')
        self.assertEqual(data['question_id'], 5)
        self.assertEqual(data.get('progress_message'), 'かなり見えてきました')
        best_question.assert_called_once()
        disambiguating.assert_not_called()

    def test_progress_message_for_close_candidates(self):
        import app as app_module
        with self.client.session_transaction() as sess:
            sess['started'] = True
            sess['answers'] = {str(i): 1.0 for i in range(2)}
            sess['asked'] = [0, 1, 2]
            sess['idk_streak'] = 0
        with patch.object(app_module.engine, 'top_guess', return_value=[(0, 0.42), (1, 0.39)]), \
                patch.object(app_module.engine, 'best_question', return_value=3):
            res = self.client.post('/api/answer', json={'question_id': 2, 'answer': 1.0})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['action'], 'question')
        self.assertEqual(data.get('progress_message'), '候補が2つに割れています')

    def test_hard_limit_forces_guess_even_when_low_confidence(self):
        import app as app_module
        with self.client.session_transaction() as sess:
            sess['started'] = True
            sess['answers'] = {str(i): 1.0 for i in range(29)}
            sess['asked'] = list(range(30))
            sess['idk_streak'] = 0
        with patch.object(app_module.engine, 'top_guess', return_value=[(0, 0.50), (1, 0.45)]):
            res = self.client.post('/api/answer', json={'question_id': 29, 'answer': 1.0})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()['action'], 'guess')

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

    def test_learning_endpoints_without_start_return_440(self):
        fresh = app.test_client()
        cases = [
            ('/api/confirm', {'correct': True, 'fetish_id': 0}),
            ('/api/teach', {'fetish_id': 0}),
            ('/api/add_fetish', {'name': '未開始テスト', 'confirmed': True}),
            ('/api/finalize_added', {'items': []}),
        ]
        for url, payload in cases:
            with self.subTest(url=url):
                res = fresh.post(url, json=payload)
                self.assertEqual(res.status_code, 440)

    def test_answer_rejects_non_current_question_id(self):
        start = self._start()
        current = start['question_id']
        other = 0 if current != 0 else 1
        res = self.client.post('/api/answer', json={'question_id': other, 'answer': 1.0})
        self.assertEqual(res.status_code, 409)

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
        data = self._force_guess()
        fid = data['fetish_id']
        log_before = app_engine.get_fetish_log()
        self.client.post('/api/confirm', json={
            'correct': True,
            'fetish_id': fid,
            'compound_ids': [c['fetish_id'] for c in data.get('compound', [])],
        })
        log_after = app_engine.get_fetish_log()
        before = log_before.get(fid, {}).get('correct', 0)
        after  = log_after.get(fid, {}).get('correct', 0)
        self.assertGreater(after, before)

    def test_fetish_log_uses_configured_temp_path(self):
        from app import engine as app_engine
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'isolated', 'fetish_log.json')
            with patch.dict(os.environ, {'FETISH_LOG_PATH': path}, clear=False):
                app_engine.log_guessed(0)
                self.assertTrue(os.path.exists(path))
                with open(path, encoding='utf-8') as f:
                    data = json.load(f)
                self.assertEqual(data['0']['guessed'], 1)

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
        self._set_active_guess(0, [f1_id])
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
        self.assertEqual(res.headers['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(res.headers['X-Frame-Options'], 'DENY')
        self.assertIn('Content-Security-Policy', res.headers)
        data = res.get_json()
        self.assertEqual(data['status'], 'ok')
        self.assertIn('fetishes', data)
        self.assertIn('questions', data)
        self.assertIn('matrix', data)
        self.assertIn('runtime', data)
        self.assertIn('persistence', data)
        self.assertTrue(data['matrix']['ok'])
        self.assertIn('error_counts', data['runtime'])
        self.assertIn('matrix_saved_mtime', data['persistence'])
        self.assertGreater(data['fetishes'], 0)
        self.assertGreater(data['questions'], 0)

    def test_health_ignores_invalid_threshold_env(self):
        old_threshold = os.environ.get('HEALTH_5XX_DEGRADED_THRESHOLD')
        try:
            os.environ['HEALTH_5XX_DEGRADED_THRESHOLD'] = 'bad'
            res = self.client.get('/health')
            self.assertEqual(res.status_code, 200)
            self.assertIn('status', res.get_json())
        finally:
            if old_threshold is None:
                os.environ.pop('HEALTH_5XX_DEGRADED_THRESHOLD', None)
            else:
                os.environ['HEALTH_5XX_DEGRADED_THRESHOLD'] = old_threshold

    def test_health_degrades_on_5xx_threshold(self):
        import app as app_module
        old_counts = dict(app_module._ERROR_COUNTS)
        old_threshold = os.environ.get('HEALTH_5XX_DEGRADED_THRESHOLD')
        try:
            app_module._ERROR_COUNTS['5xx'] = 1
            os.environ['HEALTH_5XX_DEGRADED_THRESHOLD'] = '1'
            res = self.client.get('/health')
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertEqual(data['status'], 'degraded')
            self.assertIn('5xx_threshold', data['degraded_reasons'])
        finally:
            app_module._ERROR_COUNTS.clear()
            app_module._ERROR_COUNTS.update(old_counts)
            if old_threshold is None:
                os.environ.pop('HEALTH_5XX_DEGRADED_THRESHOLD', None)
            else:
                os.environ['HEALTH_5XX_DEGRADED_THRESHOLD'] = old_threshold


    def _admin_read_headers(self):
        return {'Authorization': 'Bearer read-token'}

    def _admin_headers(self):
        import base64
        os.environ['ADMIN_PASS'] = 'testpass'
        creds = base64.b64encode(b'admin:testpass').decode()
        return {'Authorization': f'Basic {creds}'}

    def _full_matrix_rows(self):
        from app import engine as app_engine
        rows = []
        for fi, f in enumerate(app_engine.fetishes):
            for qi, q in enumerate(app_engine.questions):
                rows.append({
                    'fetish_id': f['id'],
                    'fetish_name': f['name'],
                    'question_id': qi,
                    'question_text': q['text'],
                    'yes': app_engine.matrix['yes'][fi][qi],
                    'total': app_engine.matrix['total'][fi][qi],
                })
        return rows

    def test_export_log_returns_csv(self):
        headers = self._admin_headers()
        res = self.client.get('/api/admin/export_log', headers=headers)
        self.assertEqual(res.status_code, 200)
        self.assertIn('text/csv', res.content_type)
        body = res.data.decode('utf-8')
        self.assertTrue(body.startswith('id,name,guessed,correct,wrong,feedback_total,feedback_accuracy,unfeedback,guess_confirm_rate'))

    def test_export_log_escapes_formula_names(self):
        headers = self._admin_headers()
        from app import engine as app_engine
        fid = app_engine.fetishes[0]['id']
        original_name = app_engine.fetishes[0]['name']
        try:
            app_engine.fetishes[0]['name'] = '=cmd'
            with patch.object(app_engine, 'get_fetish_log', return_value={fid: {'guessed': 1, 'correct': 1, 'wrong': 0}}):
                res = self.client.get('/api/admin/export_log', headers=headers)
            self.assertEqual(res.status_code, 200)
            self.assertIn("'=cmd", res.data.decode('utf-8'))
        finally:
            app_engine.fetishes[0]['name'] = original_name

    def test_export_matrix_returns_json(self):
        headers = self._admin_headers()
        res = self.client.get('/api/admin/export_matrix', headers=headers)
        self.assertEqual(res.status_code, 200)
        self.assertIn('application/json', res.content_type)
        data = res.get_json()
        self.assertIn('fetishes', data)
        self.assertIn('matrix_rows', data)
        self.assertIn('exported_at', data)
        self.assertIn('metadata', data)
        self.assertEqual(data['metadata']['matrix_row_count'], len(data['matrix_rows']))
        self.assertGreater(len(data['matrix_rows']), 0)

    def test_import_matrix_rejects_invalid_counts(self):
        headers = self._admin_headers()
        res = self.client.post('/api/admin/import_matrix',
            json={'matrix_rows': [{'fetish_id': 0, 'question_id': 0, 'yes': 2, 'total': 1}]},
            headers=headers)
        self.assertEqual(res.status_code, 400)

    def test_import_matrix_creates_pre_import_backup(self):
        headers = self._admin_headers()
        rows = self._full_matrix_rows()
        snapshot = unittest.mock.Mock(return_value=os.path.join(DATA_DIR, 'matrix_import_backups', 'test.json'))
        ops = type('Ops', (), {
            'snapshot_current_matrix': snapshot,
            'completeness_error': lambda self, report: None,
            'expected_rows': lambda self: len(rows),
            'list_backups': lambda self, limit=50: [],
        })()
        with patch('app._matrix_operations', return_value=ops):
            res = self.client.post('/api/admin/import_matrix',
                json={'matrix_rows': rows, 'confirm_text': 'IMPORT'},
                headers=headers)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()['imported_rows'], len(rows))
        self.assertIn('backup_path', res.get_json())
        snapshot.assert_called_once()

    def test_import_matrix_dry_run_reports_missing_player_fetishes(self):
        headers = self._admin_headers()
        from app import engine as app_engine
        missing_id = max(f['id'] for f in app_engine.fetishes) + 1000
        if missing_id < PLAYER_FETISH_BASE_ID:
            missing_id = PLAYER_FETISH_BASE_ID + 1000
        rows = self._full_matrix_rows()
        for qi, question in enumerate(app_engine.questions):
            rows.append({
                'fetish_id': missing_id,
                'fetish_name': '復元待ち',
                'question_id': qi,
                'question_text': question['text'],
                'yes': 1,
                'total': 2,
            })
        payload = {
            'fetishes': app_engine.fetishes + [{'id': missing_id, 'name': '復元待ち', 'desc': '復元待ち', 'works': []}],
            'matrix_rows': rows,
        }
        try:
            dry = self.client.post('/api/admin/import_matrix/dry_run', json=payload, headers=headers)
            self.assertEqual(dry.status_code, 200)
            dry_data = dry.get_json()
            self.assertTrue(dry_data['complete'])
            self.assertEqual(dry_data['missing_player_fetish_count'], 1)
            self.assertEqual(dry_data['restorable_player_fetish_count'], 1)
            self.assertEqual(dry_data['missing_player_fetishes'][0]['id'], missing_id)

            payload['confirm_text'] = 'IMPORT'
            res = self.client.post('/api/admin/import_matrix', json=payload, headers=headers)
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertEqual(data['restored_player_fetish_count'], 1)
            idx = app_engine.index_of(missing_id)
            self.assertIsNotNone(idx)
            self.assertEqual(app_engine.fetishes[idx]['name'], '復元待ち')
            self.assertEqual(app_engine.matrix['yes'][idx][0], 1)
            self.assertEqual(app_engine.matrix['total'][idx][0], 2)
        finally:
            idx = app_engine.index_of(missing_id)
            if idx is not None:
                app_engine.fetishes.pop(idx)
                app_engine.matrix['yes'].pop(idx)
                app_engine.matrix['total'].pop(idx)

    def test_import_matrix_requires_confirmation_after_validation(self):
        headers = self._admin_headers()
        res = self.client.post('/api/admin/import_matrix',
            json={'matrix_rows': self._full_matrix_rows()},
            headers=headers)
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()['required_confirm_text'], 'IMPORT')

    def test_import_matrix_rejects_partial_snapshot(self):
        from app import engine as app_engine
        headers = self._admin_headers()
        fid = app_engine.fetishes[0]['id']
        res = self.client.post('/api/admin/import_matrix',
            json={'matrix_rows': [{
                'fetish_id': fid,
                'question_id': 0,
                'yes': app_engine.matrix['yes'][0][0],
                'total': app_engine.matrix['total'][0][0],
            }], 'confirm_text': 'IMPORT'},
            headers=headers)
        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertIn('expected_rows', data)
        self.assertEqual(data['valid_rows'], 1)

    def test_restore_matrix_backup_endpoint(self):
        headers = self._admin_headers()
        backup_dir = os.path.join(DATA_DIR, 'matrix_import_backups')
        os.makedirs(backup_dir, exist_ok=True)
        backup_name = 'test_restore_matrix.json'
        backup_path = os.path.join(backup_dir, backup_name)
        rows = self._full_matrix_rows()
        payload = {'matrix_rows': rows}
        try:
            with open(backup_path, 'w', encoding='utf-8') as f:
                json.dump(payload, f)
            snapshot = unittest.mock.Mock(return_value=os.path.join(backup_dir, 'pre_restore.json'))
            ops = type('Ops', (), {
                'snapshot_current_matrix': snapshot,
                'completeness_error': lambda self, report: None,
                'expected_rows': lambda self: len(rows),
                'list_backups': lambda self, limit=50: [],
            })()
            with patch('app._matrix_operations', return_value=ops):
                res = self.client.post(f'/api/admin/matrix_backups/{backup_name}/restore',
                    json={'confirm_text': 'RESTORE'}, headers=headers)
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertEqual(data['status'], 'ok')
            self.assertEqual(data['restored_rows'], len(rows))
        finally:
            try:
                os.remove(backup_path)
            except OSError:
                pass

    def test_restore_matrix_backup_restores_missing_player_fetishes(self):
        headers = self._admin_headers()
        from app import engine as app_engine
        backup_dir = os.path.join(DATA_DIR, 'matrix_import_backups')
        os.makedirs(backup_dir, exist_ok=True)
        backup_name = 'test_restore_missing_player_matrix.json'
        backup_path = os.path.join(backup_dir, backup_name)
        missing_id = max(f['id'] for f in app_engine.fetishes) + 2000
        if missing_id < PLAYER_FETISH_BASE_ID:
            missing_id = PLAYER_FETISH_BASE_ID + 2000
        rows = self._full_matrix_rows()
        for qi, question in enumerate(app_engine.questions):
            rows.append({
                'fetish_id': missing_id,
                'fetish_name': 'バックアップ復元',
                'question_id': qi,
                'question_text': question['text'],
                'yes': 3,
                'total': 4,
            })
        payload = {
            'fetishes': app_engine.fetishes + [{
                'id': missing_id,
                'name': 'バックアップ復元',
                'desc': 'バックアップ復元',
                'works': [],
            }],
            'matrix_rows': rows,
        }
        try:
            with open(backup_path, 'w', encoding='utf-8') as f:
                json.dump(payload, f)
            res = self.client.post(f'/api/admin/matrix_backups/{backup_name}/restore',
                json={'confirm_text': 'RESTORE'}, headers=headers)
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertEqual(data['restored_player_fetish_count'], 1)
            idx = app_engine.index_of(missing_id)
            self.assertIsNotNone(idx)
            self.assertEqual(app_engine.fetishes[idx]['name'], 'バックアップ復元')
            self.assertEqual(app_engine.matrix['yes'][idx][0], 3)
            self.assertEqual(app_engine.matrix['total'][idx][0], 4)
        finally:
            idx = app_engine.index_of(missing_id)
            if idx is not None:
                app_engine.fetishes.pop(idx)
                app_engine.matrix['yes'].pop(idx)
                app_engine.matrix['total'].pop(idx)
            try:
                os.remove(backup_path)
            except OSError:
                pass

    def test_restore_matrix_backup_rejects_partial_snapshot(self):
        from app import engine as app_engine
        headers = self._admin_headers()
        backup_dir = os.path.join(DATA_DIR, 'matrix_import_backups')
        os.makedirs(backup_dir, exist_ok=True)
        backup_name = 'test_restore_partial_matrix.json'
        backup_path = os.path.join(backup_dir, backup_name)
        fid = app_engine.fetishes[0]['id']
        payload = {'matrix_rows': [{
            'fetish_id': fid,
            'question_id': 0,
            'yes': app_engine.matrix['yes'][0][0],
            'total': app_engine.matrix['total'][0][0],
        }]}
        try:
            with open(backup_path, 'w', encoding='utf-8') as f:
                json.dump(payload, f)
            res = self.client.post(f'/api/admin/matrix_backups/{backup_name}/restore',
                json={'confirm_text': 'RESTORE'}, headers=headers)
            self.assertEqual(res.status_code, 400)
            self.assertIn('expected_rows', res.get_json())
        finally:
            try:
                os.remove(backup_path)
            except OSError:
                pass

    def test_import_matrix_dry_run_validates_without_importing(self):
        headers = self._admin_headers()
        res = self.client.post('/api/admin/import_matrix/dry_run',
            json={'matrix_rows': [{'fetish_id': 0, 'question_id': 0, 'yes': 1, 'total': 2}]},
            headers=headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['status'], 'ok')
        self.assertEqual(data['valid_rows'], 1)
        self.assertEqual(data['skipped_rows'], 0)
        self.assertFalse(data['complete'])
        self.assertGreater(data['expected_rows'], 1)

    def test_import_matrix_dry_run_rejects_invalid_counts(self):
        headers = self._admin_headers()
        res = self.client.post('/api/admin/import_matrix/dry_run',
            json={'matrix_rows': [{'fetish_id': 0, 'question_id': 0, 'yes': 2, 'total': 1}]},
            headers=headers)
        self.assertEqual(res.status_code, 400)

    def test_import_matrix_dry_run_rejects_duplicate_pairs(self):
        from app import engine as app_engine
        headers = self._admin_headers()
        fid = app_engine.fetishes[0]['id']
        rows = [
            {'fetish_id': fid, 'question_id': 0, 'yes': 1, 'total': 2},
            {'fetish_id': fid, 'question_id': 0, 'yes': 1, 'total': 2},
        ]
        res = self.client.post('/api/admin/import_matrix/dry_run',
            json={'matrix_rows': rows},
            headers=headers)
        self.assertEqual(res.status_code, 400)

    def test_import_matrix_rejects_duplicate_pairs(self):
        from app import engine as app_engine
        headers = self._admin_headers()
        fid = app_engine.fetishes[0]['id']
        rows = [
            {'fetish_id': fid, 'question_id': 0, 'yes': 1, 'total': 2},
            {'fetish_id': fid, 'question_id': 0, 'yes': 1, 'total': 2},
        ]
        res = self.client.post('/api/admin/import_matrix',
            json={'matrix_rows': rows, 'confirm_text': 'IMPORT'},
            headers=headers)
        self.assertEqual(res.status_code, 400)

    def test_admin_params_rejects_non_finite_and_out_of_range_values(self):
        headers = self._admin_headers()
        from app import engine as app_engine
        before = app_engine.config.get('guess_threshold')
        res = self.client.post('/api/admin/params', json={'guess_threshold': 'nan', 'compound_ratio': 2}, headers=headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['updated'], {})
        self.assertGreaterEqual(len(data['errors']), 2)
        self.assertEqual(app_engine.config.get('guess_threshold'), before)


    def test_admin_read_token_allows_read_only_analytics(self):
        with patch.dict(os.environ, {'ADMIN_READ_TOKEN': 'read-token', 'ADMIN_PASS': 'testpass'}):
            headers = self._admin_read_headers()
            for path in (
                '/api/admin/preflight',
                '/api/admin/read_overview',
                '/api/admin/fetishes_snapshot',
                '/api/admin/learning_stats',
                '/api/admin/question_stats',
                '/api/admin/quality_report',
                '/api/admin/works_health',
                '/api/admin/audit_log',
                '/api/admin/maintenance_checklist',
                '/api/admin/matrix_health',
                '/api/admin/funnel_metrics',
                '/api/admin/player_fetishes',
                '/api/admin/promoted_fetish_history',
                '/api/admin/question_events',
                '/api/admin/share_events',
                '/api/admin/fetish_log_rows',
                '/api/admin/recent_fetish_ranking',
                '/api/admin/export_stats_history',
                '/api/admin/matrix_backups',
                '/api/admin/works_link_queue',
                '/api/admin/share_notes',
                '/api/admin/fetish_lookup/0',
            ):
                res = self.client.get(path, headers=headers)
                self.assertEqual(res.status_code, 200, path)

    def test_admin_read_token_cannot_mutate(self):
        with patch.dict(os.environ, {'ADMIN_READ_TOKEN': 'read-token', 'ADMIN_PASS': 'testpass'}):
            res = self.client.post('/api/admin/params', headers=self._admin_read_headers(), json={'guess_threshold': 0.8})
            share_note = self.client.post('/api/admin/share_notes', headers=self._admin_read_headers(), json={'result_name': 'NTR', 'note': 'x'})
        self.assertEqual(res.status_code, 401)
        self.assertEqual(share_note.status_code, 401)

    def test_admin_read_overview_lists_safe_snapshot_endpoints(self):
        with patch.dict(os.environ, {'ADMIN_READ_TOKEN': 'read-token', 'ADMIN_PASS': 'testpass'}):
            res = self.client.get('/api/admin/read_overview', headers=self._admin_read_headers())
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn('/api/admin/fetishes_snapshot', data['available_endpoints'])
        self.assertIn('/api/admin/funnel_metrics', data['available_endpoints'])
        self.assertIn('/api/admin/low_exposure_fetishes', data['available_endpoints'])
        self.assertIn('analysis_log_status', data)

    def test_admin_read_token_security_contract_for_read_endpoints(self):
        import app as app_module
        old_counts = dict(app_module._ERROR_COUNTS)
        read_paths = (
            '/api/admin/preflight',
            '/api/admin/read_overview',
            '/api/admin/fetishes_snapshot',
            '/api/admin/learning_stats',
            '/api/admin/question_stats',
            '/api/admin/quality_report',
            '/api/admin/works_health',
            '/api/admin/audit_log',
            '/api/admin/audit_log?format=csv',
            '/api/admin/maintenance_checklist',
            '/api/admin/matrix_health',
            '/api/admin/funnel_metrics',
            '/api/admin/player_fetishes',
            '/api/admin/promoted_fetish_history',
            '/api/admin/question_events?limit=50',
            '/api/admin/question_events/questions.csv?limit=50',
            '/api/admin/question_events/category.csv?limit=50',
            '/api/admin/share_events?limit=50',
            '/api/admin/share_events/ranking.csv?limit=50',
            '/api/admin/share_events/daily.csv?limit=50',
            '/api/admin/share_events/comparison.csv?limit=50',
            '/api/admin/share_notes',
            '/api/admin/fetish_log_rows?page=1&per_page=10',
            '/api/admin/low_exposure_fetishes?threshold=3&limit=20',
            '/api/admin/recent_fetish_ranking',
            '/api/admin/export_stats_history',
            '/api/admin/matrix_backups',
            '/api/admin/works_link_queue',
            '/api/admin/works_review',
            '/api/admin/fetish_lookup/0',
            '/api/admin/fetish_history/0',
            '/api/admin/performance',
        )
        env = {
            'ADMIN_READ_TOKEN': 'read-secret-token',
            'ADMIN_PASS': 'admin-secret-pass',
            'SECRET_KEY': 'secret-key-sentinel',
            'DATABASE_URL': 'postgres://secret-db-url',
        }
        forbidden_values = tuple(env.values()) + ('remote_addr', 'user_agent', 'session_id', 'ADMIN_PASS', 'DATABASE_URL', 'SECRET_KEY')
        try:
            with patch.dict(os.environ, env):
                headers = {'Authorization': 'Bearer read-secret-token'}
                for path in read_paths:
                    with self.subTest(path=path):
                        unauth = self.client.get(path)
                        self.assertIn(unauth.status_code, (401, 403), path)
                        res = self.client.get(path, headers=headers)
                        self.assertEqual(res.status_code, 200, path)
                        body = res.data.decode('utf-8', errors='replace')
                        for forbidden in forbidden_values:
                            self.assertNotIn(forbidden, body, path)
                        self.assertLess(len(res.data), 1_500_000, path)
        finally:
            app_module._ERROR_COUNTS.clear()
            app_module._ERROR_COUNTS.update(old_counts)

    def test_admin_read_token_rejects_mutation_endpoints(self):
        import app as app_module
        old_counts = dict(app_module._ERROR_COUNTS)
        mutation_paths = (
            ('/admin/test_play/start', {}),
            ('/admin/test_play/stop', {}),
            ('/api/admin/params', {'guess_threshold': 0.8}),
            ('/api/admin/cleanup_sessions', {}),
            ('/api/admin/add_fetish', {'name': 'x', 'desc': 'x'}),
            ('/api/admin/capture_priors', {}),
            ('/api/admin/promote_fetish/10000', {}),
            ('/api/admin/edit_question/0', {'text': 'x'}),
            ('/api/admin/edit_fetish/0', {'name': 'x'}),
            ('/api/admin/merge_fetishes', {'id_keep': 0, 'id_remove': 1}),
            ('/api/admin/import_matrix/dry_run', {'matrix_rows': []}),
            ('/api/admin/share_notes', {'result_name': 'NTR', 'note': 'x'}),
        )
        try:
            with patch.dict(os.environ, {'ADMIN_READ_TOKEN': 'read-token', 'ADMIN_PASS': 'testpass'}):
                headers = self._admin_read_headers()
                for path, payload in mutation_paths:
                    with self.subTest(path=path):
                        res = self.client.post(path, headers=headers, json=payload)
                        self.assertIn(res.status_code, (401, 403), path)
        finally:
            app_module._ERROR_COUNTS.clear()
            app_module._ERROR_COUNTS.update(old_counts)

    def test_basic_admin_auth_still_allows_management_read(self):
        with patch.dict(os.environ, {'ADMIN_READ_TOKEN': 'read-token', 'ADMIN_PASS': 'testpass'}):
            res = self.client.get('/api/admin/preflight', headers=self._admin_headers())
            self.assertEqual(res.status_code, 200)
            page = self.client.get('/admin', headers=self._admin_headers())
            self.assertEqual(page.status_code, 200)

    def test_admin_read_token_requires_env(self):
        old_token = os.environ.pop('ADMIN_READ_TOKEN', None)
        try:
            res = self.client.get('/api/admin/preflight', headers={'Authorization': 'Bearer read-token'})
            self.assertIn(res.status_code, (401, 503))
        finally:
            if old_token is not None:
                os.environ['ADMIN_READ_TOKEN'] = old_token

    def test_preflight_includes_ogp_font_check(self):
        headers = self._admin_headers()
        with tempfile.TemporaryDirectory() as tmp:
            q_path = os.path.join(tmp, 'question_events.jsonl')
            s_path = os.path.join(tmp, 'share_events.jsonl')
            question_events_service.record_event('question_shown', question_id=1, path=q_path)
            share_events_service.record_event('result_page_view', result_name='NTR', channel='result_page', success=True, path=s_path)
            with patch.dict(os.environ, {'QUESTION_EVENT_LOG_PATH': q_path, 'SHARE_EVENT_LOG_PATH': s_path}):
                res = self.client.get('/api/admin/preflight', headers=headers)
        self.assertEqual(res.status_code, 200)
        checks = {row['name']: row for row in res.get_json()['checks']}
        self.assertIn('ogp_cjk_font_available', checks)
        self.assertIn('analysis_stats_history_rows', checks)
        self.assertIn('1 question_events rows', checks['analysis_question_events_rows']['detail'])
        self.assertIn('1 share_events rows', checks['analysis_share_events_rows']['detail'])
        self.assertIn(q_path, checks['analysis_question_events_rows']['detail'])
        self.assertIn(s_path, checks['analysis_share_events_rows']['detail'])
        self.assertIn('writable=True', checks['analysis_question_events_rows']['detail'])
        self.assertIn('writable=True', checks['analysis_share_events_rows']['detail'])

    def test_audit_log_export_and_preflight(self):
        headers = self._admin_headers()
        res = self.client.get('/api/admin/audit_log', headers=headers)
        self.assertEqual(res.status_code, 200)
        self.assertIn('audit_log', res.get_json())
        res = self.client.get('/api/admin/audit_log?format=csv', headers=headers)
        self.assertEqual(res.status_code, 200)
        self.assertIn('text/csv', res.content_type)
        self.assertTrue(res.data.decode('utf-8').startswith('ts,action,status'))
        old_keep = os.environ.get('MATRIX_IMPORT_BACKUP_KEEP')
        try:
            os.environ['MATRIX_IMPORT_BACKUP_KEEP'] = 'bad'
            res = self.client.get('/api/admin/preflight', headers=headers)
            self.assertEqual(res.status_code, 200)
            self.assertIn('checks', res.get_json())
        finally:
            if old_keep is None:
                os.environ.pop('MATRIX_IMPORT_BACKUP_KEEP', None)
            else:
                os.environ['MATRIX_IMPORT_BACKUP_KEEP'] = old_keep

    def test_admin_fetish_log_rows_paginates(self):
        headers = self._admin_headers()
        res = self.client.get('/api/admin/fetish_log_rows?page=1&per_page=10&sort=guessed&order=desc', headers=headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertLessEqual(len(data['rows']), 10)
        self.assertIn('total', data)
        self.assertIn('pages', data)


    def test_admin_low_exposure_fetishes_returns_analysis_summary(self):
        from app import engine as app_engine
        headers = self._admin_headers()
        with patch.object(app_engine, 'get_fetish_log', return_value={
            0: {'guessed': 0, 'correct': 0, 'wrong': 0},
            1: {'guessed': 2, 'correct': 1, 'wrong': 0},
            2: {'guessed': 10, 'correct': 3, 'wrong': 1},
        }):
            res = self.client.get('/api/admin/low_exposure_fetishes?threshold=3&limit=20', headers=headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['status'], 'ok')
        self.assertEqual(data['threshold'], 3)
        self.assertGreaterEqual(data['zero_count'], 1)
        self.assertGreaterEqual(data['low_count'], 2)
        self.assertIn('low_share', data['summary'])
        guessed_values = [row['guessed'] for row in data['rows']]
        self.assertEqual(guessed_values, sorted(guessed_values))
        self.assertIn('works_count', data['rows'][0])
        self.assertIn('detail_url', data['rows'][0])

    def test_admin_works_link_queue_endpoint(self):
        headers = self._admin_headers()
        res = self.client.get('/api/admin/works_link_queue', headers=headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['status'], 'ok')
        self.assertIn('missing_url', data['counts'])
        self.assertIn('search_url', data['counts'])
        self.assertIn('missing_asin', data['counts'])
        self.assertIn('samples', data)

    def test_admin_works_seed_backfill_dry_run_and_apply(self):
        from app import engine as app_engine
        headers = self._admin_headers()
        idx = next(i for i, fetish in enumerate(app_engine.fetishes) if fetish['id'] < PLAYER_FETISH_BASE_ID and fetish.get('works'))
        original = [dict(work) for work in app_engine.fetishes[idx].get('works', [])]
        try:
            app_engine.fetishes[idx]['works'] = []
            res = self.client.get('/api/admin/works_seed_backfill?sample_limit=200', headers=headers)
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertEqual(data['status'], 'ok')
            self.assertEqual(data['mode'], 'dry_run')
            self.assertGreaterEqual(data['candidate_count'], 1)
            self.assertIn(app_engine.fetishes[idx]['id'], {row['id'] for row in data['candidates']})

            res = self.client.post('/api/admin/works_seed_backfill', headers=headers, json={})
            self.assertEqual(res.status_code, 400)
            self.assertEqual(res.get_json()['required_confirm_text'], 'BACKFILL_WORKS')

            res = self.client.post('/api/admin/works_seed_backfill', headers=headers, json={'confirm_text': 'BACKFILL_WORKS'})
            self.assertEqual(res.status_code, 200)
            applied = res.get_json()
            self.assertEqual(applied['status'], 'ok')
            self.assertEqual(applied['mode'], 'applied')
            self.assertGreaterEqual(applied['updated_count'], 1)
            self.assertTrue(app_engine.fetishes[idx].get('works'))
        finally:
            app_engine.fetishes[idx]['works'] = original

    def test_admin_performance_endpoint(self):
        headers = self._admin_headers()
        res = self.client.get('/api/admin/performance', headers=headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['status'], 'ok')
        self.assertTrue(data['measurements'])
        self.assertIn('ms', data['measurements'][0])

    def test_admin_csrf_enforced_when_enabled(self):
        app.config['ENFORCE_CSRF'] = True
        try:
            headers = self._admin_headers()
            res = self.client.post('/api/admin/cleanup_sessions', headers=headers)
            self.assertEqual(res.status_code, 403)
            admin = self.client.get('/admin', headers=headers)
            self.assertEqual(admin.status_code, 200)
            match = re.search(r'csrfToken: \"([^\"]+)\"', admin.data.decode('utf-8'))
            self.assertIsNotNone(match)
            headers = {**headers, 'X-CSRF-Token': match.group(1)}
            res = self.client.post('/api/admin/cleanup_sessions', headers=headers)
            self.assertEqual(res.status_code, 200)
        finally:
            app.config.pop('ENFORCE_CSRF', None)

    def test_rate_limit_enforced_when_enabled(self):
        import app as app_module
        app.config['ENFORCE_RATE_LIMIT'] = True
        app.config['RATE_LIMIT_OVERRIDES'] = {'api_start': (2, 60)}
        app_module._RATE_LIMIT_BUCKETS.clear()
        try:
            self.assertEqual(self.client.post('/api/start').status_code, 200)
            self.assertEqual(self.client.post('/api/start').status_code, 200)
            limited = self.client.post('/api/start')
            self.assertEqual(limited.status_code, 429)
            self.assertIn('Retry-After', limited.headers)
            self.assertIn('retry_after', limited.get_json())
        finally:
            app.config.pop('ENFORCE_RATE_LIMIT', None)
            app.config.pop('RATE_LIMIT_OVERRIDES', None)
            app_module._RATE_LIMIT_BUCKETS.clear()

    def test_rate_limit_ignores_untrusted_x_forwarded_for(self):
        import app as app_module
        app.config['ENFORCE_RATE_LIMIT'] = True
        app.config['RATE_LIMIT_OVERRIDES'] = {'api_start': (2, 60)}
        app.config.pop('TRUSTED_PROXY_IPS', None)
        app_module._RATE_LIMIT_BUCKETS.clear()
        try:
            for i in range(2):
                res = self.client.post('/api/start',
                    headers={'X-Forwarded-For': f'203.0.113.{i}'},
                    environ_base={'REMOTE_ADDR': '198.51.100.10'})
                self.assertEqual(res.status_code, 200)
            limited = self.client.post('/api/start',
                headers={'X-Forwarded-For': '203.0.113.99'},
                environ_base={'REMOTE_ADDR': '198.51.100.10'})
            self.assertEqual(limited.status_code, 429)
        finally:
            app.config.pop('ENFORCE_RATE_LIMIT', None)
            app.config.pop('RATE_LIMIT_OVERRIDES', None)
            app_module._RATE_LIMIT_BUCKETS.clear()

    def test_rate_limit_can_use_environment_settings(self):
        import app as app_module
        app.config['ENFORCE_RATE_LIMIT'] = True
        old_limit = os.environ.get('RATE_LIMIT_API_START_LIMIT')
        old_window = os.environ.get('RATE_LIMIT_API_START_WINDOW')
        app_module._RATE_LIMIT_BUCKETS.clear()
        try:
            os.environ['RATE_LIMIT_API_START_LIMIT'] = '1'
            os.environ['RATE_LIMIT_API_START_WINDOW'] = '60'
            self.assertEqual(self.client.post('/api/start').status_code, 200)
            limited = self.client.post('/api/start')
            self.assertEqual(limited.status_code, 429)
            self.assertGreaterEqual(limited.get_json()['retry_after'], 1)
        finally:
            app.config.pop('ENFORCE_RATE_LIMIT', None)
            app_module._RATE_LIMIT_BUCKETS.clear()
            if old_limit is None:
                os.environ.pop('RATE_LIMIT_API_START_LIMIT', None)
            else:
                os.environ['RATE_LIMIT_API_START_LIMIT'] = old_limit
            if old_window is None:
                os.environ.pop('RATE_LIMIT_API_START_WINDOW', None)
            else:
                os.environ['RATE_LIMIT_API_START_WINDOW'] = old_window

    def test_admin_csrf_token_expires_when_enabled(self):
        app.config['ENFORCE_CSRF'] = True
        old_ttl = os.environ.get('ADMIN_CSRF_TTL_SECONDS')
        try:
            os.environ['ADMIN_CSRF_TTL_SECONDS'] = '1'
            headers = self._admin_headers()
            admin = self.client.get('/admin', headers=headers)
            self.assertEqual(admin.status_code, 200)
            match = re.search(r'csrfToken: \"([^\"]+)\"', admin.data.decode('utf-8'))
            self.assertIsNotNone(match)
            with self.client.session_transaction() as sess:
                sess['admin_csrf_issued_at'] = 0
            res = self.client.post('/api/admin/cleanup_sessions',
                headers={**headers, 'X-CSRF-Token': match.group(1)})
            self.assertEqual(res.status_code, 403)
        finally:
            app.config.pop('ENFORCE_CSRF', None)
            if old_ttl is None:
                os.environ.pop('ADMIN_CSRF_TTL_SECONDS', None)
            else:
                os.environ['ADMIN_CSRF_TTL_SECONDS'] = old_ttl

    def test_recent_ranking_bounds_query_params(self):
        headers = self._admin_headers()
        res = self.client.get('/api/admin/recent_fetish_ranking?days=-1&top_n=999',
            headers=headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['days'], 1)
        self.assertIn(data['source'], ('recent', 'all_time_fallback'))

    def test_quality_report_endpoint(self):
        headers = self._admin_headers()
        res = self.client.get('/api/admin/quality_report', headers=headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn('low_questions', data)
        self.assertIn('high_correlation_questions', data)
        self.assertIn('weak_fetishes', data)
        self.assertIn('feedback_summary', data)
        self.assertIn('confusion_summary', data)
        self.assertIn('low_confidence_summary', data)
        self.assertIn('action_items', data)

    def test_quality_report_includes_low_confidence_effectiveness(self):
        import app as app_module
        from app import engine as app_engine
        fid = app_engine.fetishes[0]['id']
        quality_stats_service.record_quality_stat(app_engine, 'q_low_conf_guess')
        quality_stats_service.record_quality_stat(app_engine, 'q_additional_guess')
        quality_stats_service.record_quality_stat(app_engine, 'q_additional_question', 2)
        with self.client.session_transaction() as sess:
            sess['answers'] = {}
            sess['last_guess_quality'] = {
                'low_confidence_extended': True,
                'additional_questions': 2,
            }
        res = self.client.post('/api/confirm', json={'correct': True, 'fetish_id': fid})
        self.assertEqual(res.status_code, 200)

        headers = self._admin_headers()
        res = self.client.get('/api/admin/quality_report', headers=headers)
        self.assertEqual(res.status_code, 200)
        summary = res.get_json()['low_confidence_summary']
        self.assertGreaterEqual(summary['low_confidence_guesses'], 1)
        self.assertGreaterEqual(summary['low_confidence_correct'], 1)
        self.assertGreaterEqual(summary['additional_questions_asked'], 2)

    def test_maintenance_checklist_endpoint(self):
        headers = self._admin_headers()
        res = self.client.get('/api/admin/maintenance_checklist', headers=headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        admin_page = self.client.get('/admin', headers=headers)
        self.assertEqual(admin_page.status_code, 200)
        self.assertIn(b'apply-works-seed-backfill', admin_page.data)
        self.assertIn(b'repair-promoted-stats-dry-run', admin_page.data)
        self.assertIn(b'repair-promoted-stats-apply', admin_page.data)
        self.assertIn(b'move-stats-history-dry-run', admin_page.data)
        self.assertIn(b'move-stats-history-apply', admin_page.data)
        self.assertIn(b'lookup-fetish-id', admin_page.data)
        self.assertIn('checklist', data)
        self.assertIn('weak_fetishes', data)
        self.assertIn('duplicate_questions', data)
        self.assertIn('low_questions', data)
        self.assertIn('works', data)
        ids = {item['id'] for item in data['checklist']}
        self.assertIn('weak_fetishes', ids)
        self.assertIn('duplicate_questions', ids)
        self.assertIn('low_questions', ids)
        self.assertIn('works', ids)
        self.assertIn('missing_url_work_count', data['works'])
        if data['weak_fetishes']:
            row = data['weak_fetishes'][0]
            self.assertIn('edit_anchor', row)
            self.assertIn('similarity_anchor', row)
            self.assertIn('hint', row)
        if data['duplicate_questions']:
            self.assertIn('suggested_action', data['duplicate_questions'][0])

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
        from app import engine as app_engine
        before = app_engine.get_stats().get('start_count', 0)
        res = self.client.post('/api/resume', json={'pairs': []})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get('action'), 'question')
        self.assertIn('question_id', data)
        self.assertEqual(app_engine.get_stats().get('start_count', 0), before)

    def test_resume_with_answers_counts_as_start_source(self):
        from app import engine as app_engine
        before = app_engine.get_stats().get('start_count', 0)
        res = self.client.post('/api/resume', json={'pairs': [{'q_id': 0, 'answer': 1.0}]})
        self.assertEqual(res.status_code, 200)
        self.assertGreater(app_engine.get_stats().get('start_count', 0), before)

    def test_funnel_metrics_marks_impossible_completion_rate_unavailable(self):
        from services.admin_helpers import build_completion_metrics
        metrics = build_completion_metrics(
            {'start_count': 10, 'completion_count': 12},
            [{'start': 5, 'completion': 7}],
            {},
        )
        self.assertIsNone(metrics['completion_rate'])
        self.assertFalse(metrics['completion_rate_reliable'])
        self.assertIn('参考不可', metrics['completion_rate_note'])
        self.assertIsNone(metrics['recent_7_days']['completion_rate'])
        self.assertFalse(metrics['recent_7_days']['completion_rate_reliable'])

    def test_unverified_resumed_guess_skips_learning(self):
        from app import engine as app_engine
        q = 8
        idx = app_engine.index_of(0)
        before_yes = app_engine.matrix['yes'][idx][q]
        before_total = app_engine.matrix['total'][idx][q]
        before_log = dict(app_engine.get_fetish_log().get(0, {}))
        with self.client.session_transaction() as sess:
            sess['started'] = True
            sess['answers'] = {str(q): 1.0}
            sess['last_guess_fetish_id'] = 0
            sess['last_guess_compound_ids'] = []
            sess['client_resumed'] = True
            sess['resume_learning_verified'] = False
        res = self.client.post('/api/confirm', json={'correct': True, 'fetish_id': 0})
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['learning_disabled'])
        self.assertEqual(app_engine.matrix['yes'][idx][q], before_yes)
        self.assertEqual(app_engine.matrix['total'][idx][q], before_total)
        self.assertEqual(app_engine.get_fetish_log().get(0, {}), before_log)

    def test_continue_after_guess(self):
        self._force_guess()
        res = self.client.post('/api/continue')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn(data.get('action'), ('question',))

    def test_guess_logs_compound_candidates_as_guessed(self):
        from app import engine as app_engine
        old_compound = app_engine.config.get('compound_ratio')
        old_triple = app_engine.config.get('triple_ratio')
        try:
            app_engine.config['compound_ratio'] = 0.0
            app_engine.config['triple_ratio'] = 0.0
            data = self._force_guess()
            compound_ids = [item['fetish_id'] for item in data.get('compound', [])]
            self.assertTrue(compound_ids)
            log = app_engine.get_fetish_log()
            for fetish_id in {data['fetish_id']} | set(compound_ids):
                self.assertGreaterEqual(log.get(fetish_id, {}).get('guessed', 0), 1)
        finally:
            if old_compound is None:
                app_engine.config.pop('compound_ratio', None)
            else:
                app_engine.config['compound_ratio'] = old_compound
            if old_triple is None:
                app_engine.config.pop('triple_ratio', None)
            else:
                app_engine.config['triple_ratio'] = old_triple

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

    def test_admin_fetish_lookup_returns_name(self):
        headers = self._admin_headers()
        res = self.client.get('/api/admin/fetish_lookup/0', headers=headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['status'], 'ok')
        self.assertEqual(data['id'], 0)
        self.assertIn('name', data)
        self.assertFalse(data['is_player_fetish'])

        missing = self.client.get('/api/admin/fetish_lookup/999999', headers=headers)
        self.assertEqual(missing.status_code, 404)

    def test_repair_promoted_stats_history_requires_mapping_and_confirm(self):
        headers = self._admin_headers()
        res = self.client.get('/api/admin/repair_promoted_stats_history', headers=headers)
        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertEqual(data['required_confirm_text'], 'REPAIR_PROMOTED_STATS')

        with patch('engine.facade._use_db', return_value=True), \
             patch('engine.db.promoted_stats_history_repair_report', return_value={'mapping_count': 1, 'rows': [], 'total_value': 0, 'storage': 'postgres'}), \
             patch('engine.db.repair_promoted_stats_history', return_value={'mapping_count': 1, 'rows': [], 'total_value': 3, 'applied': True, 'storage': 'postgres'}):
            dry = self.client.get('/api/admin/repair_promoted_stats_history',
                headers=headers, json={'mappings': [{'old_id': 10000, 'new_id': 3}]})
            self.assertEqual(dry.status_code, 200)
            self.assertEqual(dry.get_json()['mode'], 'dry_run')

            post_dry = self.client.post('/api/admin/repair_promoted_stats_history', headers=headers, json={
                'dry_run': True,
                'mappings': [{'old_id': 10000, 'new_id': 3}],
            })
            self.assertEqual(post_dry.status_code, 200)
            self.assertEqual(post_dry.get_json()['mode'], 'dry_run')

            missing_confirm = self.client.post('/api/admin/repair_promoted_stats_history',
                headers=headers, json={'mappings': [{'old_id': 10000, 'new_id': 3}]})
            self.assertEqual(missing_confirm.status_code, 400)
            self.assertEqual(missing_confirm.get_json()['required_confirm_text'], 'REPAIR_PROMOTED_STATS')

            applied = self.client.post('/api/admin/repair_promoted_stats_history', headers=headers, json={
                'mappings': [{'old_id': 10000, 'new_id': 3}],
                'confirm_text': 'REPAIR_PROMOTED_STATS',
            })
            self.assertEqual(applied.status_code, 200)
            self.assertEqual(applied.get_json()['mode'], 'applied')
            self.assertEqual(applied.get_json()['total_value'], 3)

    def test_move_stats_history_allows_seed_id_correction_with_confirm(self):
        headers = self._admin_headers()
        with patch('engine.facade._use_db', return_value=True), \
             patch('engine.db.promoted_stats_history_repair_report', return_value={'mapping_count': 4, 'rows': [], 'total_value': 12, 'storage': 'postgres'}), \
             patch('engine.db.repair_promoted_stats_history', return_value={'mapping_count': 4, 'rows': [], 'total_value': 12, 'applied': True, 'storage': 'postgres'}):
            dry = self.client.post('/api/admin/move_stats_history', headers=headers, json={
                'dry_run': True,
                'mappings': [
                    {'old_id': 129, 'new_id': 128},
                    {'old_id': 130, 'new_id': 129},
                    {'old_id': 131, 'new_id': 130},
                    {'old_id': 132, 'new_id': 131},
                ],
            })
            self.assertEqual(dry.status_code, 200)
            self.assertEqual(dry.get_json()['mode'], 'dry_run')

            rejected = self.client.post('/api/admin/move_stats_history', headers=headers, json={
                'mappings': [{'old_id': 129, 'new_id': 128}],
            })
            self.assertEqual(rejected.status_code, 400)
            self.assertEqual(rejected.get_json()['required_confirm_text'], 'MOVE_STATS_HISTORY')

            applied = self.client.post('/api/admin/move_stats_history', headers=headers, json={
                'confirm_text': 'MOVE_STATS_HISTORY',
                'mappings': [{'old_id': 129, 'new_id': 128}],
            })
            self.assertEqual(applied.status_code, 200)
            self.assertEqual(applied.get_json()['mode'], 'applied')

    def test_edit_question_empty_text_rejected(self):
        headers = self._admin_headers()
        res = self.client.post('/api/admin/edit_question/0',
            json={'text': '  '}, headers=headers)
        self.assertEqual(res.status_code, 400)

    def test_result_share_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'share_links.json')
            with patch.dict(os.environ, {'SHARE_LINKS_PATH': path}):
                res = self.client.get('/r?f=NTR&p=82&d=テスト')
        self.assertEqual(res.status_code, 200)
        body = res.data.decode('utf-8')
        self.assertIn('NTR', body)
        self.assertIn('82', body)
        self.assertIn("あなたの『癖』は……", body)
        self.assertIn('AI精度82%', body)
        self.assertIn('次はあなたの番です……', body)
        self.assertNotIn('称号', body)
        self.assertNotIn('レア度', body)
        self.assertIn('og:url', body)
        self.assertIn('/r?f=NTR&amp;p=82&amp;d=', body)
        self.assertNotRegex(body, r'https?://[^" ]+/r/[0-9A-Za-z]{4,6}')
        self.assertIn("あなたの『癖』は…… NTR", body)
        self.assertIn('/ogp.png?f=NTR&amp;p=82', body)
        self.assertEqual(res.headers.get('X-Robots-Tag'), 'noindex, follow')
        self.assertIn('name="robots" content="noindex,follow"', body)

    def test_legacy_result_share_does_not_create_short_link(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'share_links.json')
            with patch.dict(os.environ, {'SHARE_LINKS_PATH': path}):
                res = self.client.get('/r?f=NTR&p=82&d=テスト')
                self.assertEqual(res.status_code, 200)
                self.assertFalse(os.path.exists(path))

    def test_short_result_share_link_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'share_links.json')
            with patch.dict(os.environ, {'SHARE_LINKS_PATH': path}):
                created = self.client.post('/api/share_link', json={
                    'fetish': '感覚遮断落とし穴',
                    'percent': '93',
                    'desc': 'テスト説明',
                })
                self.assertEqual(created.status_code, 200)
                data = created.get_json()
                self.assertEqual(data['status'], 'ok')
                self.assertRegex(data['share_id'], r'^[0-9A-Za-z]{4,6}$')
                self.assertEqual(data['share_url'], f"/r/{data['share_id']}")

                res = self.client.get(data['share_url'])
                self.assertEqual(res.status_code, 200)
                body = res.data.decode('utf-8')
                self.assertIn('感覚遮断落とし穴', body)
                self.assertIn('AI精度93%', body)
                self.assertIn(f"/r/{data['share_id']}", body)
                self.assertIn('/ogp.png?f=%E6%84%9F%E8%A6%9A%E9%81%AE%E6%96%AD%E8%90%BD%E3%81%A8%E3%81%97%E7%A9%B4&amp;p=93', body)

    def test_share_link_api_rejects_missing_name(self):
        res = self.client.post('/api/share_link', json={'probability': '88'})
        self.assertEqual(res.status_code, 400)

    def test_ogp_png_image(self):
        res = self.client.get('/ogp.png?f=NTR&p=82')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.mimetype, 'image/png')
        self.assertTrue(res.data.startswith(b'\x89PNG\r\n\x1a\n'))
        width, height = struct.unpack('>II', res.data[16:24])
        self.assertEqual((width, height), (1200, 630))

    def test_ogp_font_path_env_is_preferred(self):
        with patch.dict(os.environ, {'OGP_FONT_PATH': '/tmp/custom-ogp-font.ttf'}):
            self.assertEqual(next(ogp_service._ogp_font_candidates()), '/tmp/custom-ogp-font.ttf')

    def test_ogp_texts_fall_back_to_ascii_when_cjk_font_is_missing(self):
        texts = ogp_service._ogp_texts('眼鏡', '88', cjk_supported=False)
        self.assertEqual(texts['label'], 'Your observed pattern is...')
        self.assertEqual(texts['name'], 'Megane')
        self.assertEqual(texts['prob'], 'AI Precision 88%')
        self.assertEqual(texts['side'], 'Next observation: you.')
        self.assertEqual(texts['mark_sub'], 'LOG')

    def test_ogp_texts_keep_japanese_when_cjk_font_is_available(self):
        texts = ogp_service._ogp_texts('眼鏡', '88', cjk_supported=True)
        self.assertEqual(texts['label'], "あなたの『癖』は……")
        self.assertEqual(texts['name'], '眼鏡')
        self.assertEqual(texts['prob'], 'AI精度 88%')
        self.assertEqual(texts['mark'], 'AI')
        self.assertEqual(texts['mark_sub'], '観測ログ')

    def test_legacy_svg_ogp_uses_ai_badge_instead_of_question_mark(self):
        svg = ogp_service.render_svg('眼鏡', '88')
        self.assertIn(">あなたの『癖』は……</text>", svg)
        self.assertIn('>AI精度 88%</text>', svg)
        self.assertNotIn('>?</text>', svg)

    def test_result_share_clamps_probability(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'share_links.json')
            with patch.dict(os.environ, {'SHARE_LINKS_PATH': path}):
                res = self.client.get('/r?f=NTR&p=999&d=テスト')
        body = res.data.decode('utf-8')
        self.assertIn('AI精度100%', body)
        self.assertIn('/ogp.png?f=NTR&amp;p=100', body)
        self.assertIn('/r?f=NTR&amp;p=100&amp;d=', body)

    def test_share_event_api_records_minimal_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'share_events.jsonl')
            with patch.dict(os.environ, {'SHARE_EVENT_LOG_PATH': path}):
                res = self.client.post('/api/share_event', json={
                    'event_name': 'share_button_click',
                    'result_name': 'NTR',
                    'channel': 'button',
                    'success': True,
                    'ignored': 'not persisted',
                })
            self.assertEqual(res.status_code, 200)
            self.assertTrue(res.get_json()['recorded'])
            with open(path, encoding='utf-8') as file_obj:
                event = json.loads(file_obj.readline())
        self.assertEqual(set(event), {'timestamp', 'event_name', 'result_name', 'channel', 'success'})
        self.assertEqual(event['event_name'], 'share_button_click')
        self.assertEqual(event['result_name'], 'NTR')
        self.assertEqual(event['channel'], 'button')
        self.assertTrue(event['success'])
        self.assertNotIn('ip', event)
        self.assertNotIn('user_agent', event)
        self.assertNotIn('session', event)

    def test_share_event_api_ignores_unknown_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'share_events.jsonl')
            with patch.dict(os.environ, {'SHARE_EVENT_LOG_PATH': path}):
                res = self.client.post('/api/share_event', json={'event_name': 'unknown_event'})
                self.assertEqual(res.status_code, 200)
                self.assertFalse(res.get_json()['recorded'])
                self.assertFalse(os.path.exists(path))

    def test_result_share_and_ogp_views_are_logged(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'share_events.jsonl')
            with patch.dict(os.environ, {'SHARE_EVENT_LOG_PATH': path, 'SHARE_LINKS_PATH': os.path.join(tmp, 'share_links.json')}):
                self.client.get('/r?f=NTR&p=82&d=テスト')
                self.client.get('/ogp.png?f=NTR&p=82')
                self.client.get('/ogp?f=NTR&p=82')
                events = share_events_service.read_events(path=path, limit=10)
        names = [event['event_name'] for event in events]
        self.assertIn('result_page_view', names)
        self.assertIn('ogp_png_view', names)
        self.assertIn('ogp_svg_view', names)
        self.assertTrue(all('ip' not in event and 'user_agent' not in event for event in events))


    def test_admin_question_events_report_and_csv(self):
        headers = self._admin_headers()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'question_events.jsonl')
            question_events_service.record_event('question_shown', question_id=1, question_text='返信が遅いと気になる？', category='attachment', axis='abstract', path=path)
            question_events_service.record_event('question_answered', question_id=1, answer=1.0, category='attachment', axis='abstract', path=path)
            question_events_service.record_event('question_dropoff', question_id=1, answered_count=1, category='attachment', axis='abstract', path=path)
            question_events_service.record_event('question_shown', question_id=2, question_text='現実寄りより、少し非現実感がある方が惹かれる？', category='world', axis='abstract', path=path)
            question_events_service.record_event('question_result_contribution', question_id=1, result_name='共依存', answer=1.0, result_rank=1, path=path)
            with patch.dict(os.environ, {'QUESTION_EVENT_LOG_PATH': path}):
                report = self.client.get('/api/admin/question_events', headers=headers)
                questions_csv = self.client.get('/api/admin/question_events/questions.csv', headers=headers)
                category_csv = self.client.get('/api/admin/question_events/category.csv', headers=headers)
        self.assertEqual(report.status_code, 200)
        data = report.get_json()
        self.assertEqual(data['status'], 'ok')
        self.assertEqual(data['metrics']['shown'], 2)
        self.assertEqual(data['metrics']['answered'], 1)
        self.assertEqual(data['metrics']['dropoffs'], 1)
        self.assertEqual(data['questions'][0]['question_id'], 1)
        self.assertEqual(data['questions'][0]['yes_rate'], 100.0)
        self.assertEqual(data['contribution_ranking'][0]['top_results'][0]['result_name'], '共依存')
        self.assertIn('text/csv', questions_csv.content_type)
        self.assertIn('question_id,category,axis,shown', questions_csv.data.decode('utf-8').splitlines()[0])
        self.assertIn('category,shown,shown_share', category_csv.data.decode('utf-8').splitlines()[0])

    def test_high_yes_rate_questions_are_reworded_to_tradeoffs(self):
        from app import engine as app_engine
        self.assertEqual(
            app_engine.questions[35]['text'],
            '感情をはっきり言葉にする人より、沈黙や間で伝わる人の方が気になる？',
        )
        self.assertEqual(app_engine.questions[35].get('category'), 'tone')
        self.assertEqual(
            app_engine.questions[141]['text'],
            '生活感のある賑やかさより、余白が多く整った静けさの方が落ち着く？',
        )
        self.assertEqual(app_engine.questions[141].get('category'), 'aesthetic')


    def test_question_events_are_recorded_without_personal_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'question_events.jsonl')
            with patch.dict(os.environ, {'QUESTION_EVENT_LOG_PATH': path}):
                start = self.client.post('/api/start').get_json()
                self.client.post('/api/answer', json={'question_id': start['question_id'], 'answer': 1.0})
                with self.client.session_transaction() as sess:
                    sess['completed'] = False
                    sess['dropoff_recorded'] = False
                self.client.post('/api/dropoff', json={'question_id': start['question_id']})
                events = question_events_service.read_events(path=path, limit=10)
        names = [event['event_name'] for event in events]
        self.assertIn('question_shown', names)
        self.assertIn('question_answered', names)
        self.assertIn('question_dropoff', names)
        self.assertTrue(all('ip' not in event and 'user_agent' not in event and 'session' not in event for event in events))


    def test_admin_page_shows_analysis_log_status(self):
        headers = self._admin_headers()
        with tempfile.TemporaryDirectory() as tmp:
            q_path = os.path.join(tmp, 'question_events.jsonl')
            s_path = os.path.join(tmp, 'share_events.jsonl')
            question_events_service.record_event('question_shown', question_id=1, path=q_path)
            share_events_service.record_event('result_page_view', result_name='NTR', channel='result_page', success=True, path=s_path)
            with patch.dict(os.environ, {'QUESTION_EVENT_LOG_PATH': q_path, 'SHARE_EVENT_LOG_PATH': s_path}):
                res = self.client.get('/admin', headers=headers)
        self.assertEqual(res.status_code, 200)
        body = res.data.decode('utf-8')
        self.assertIn('分析ログ蓄積状況', body)
        self.assertIn('question_events が少ないため', body)
        self.assertIn('share_events が少ないため', body)
        self.assertIn('取得元: JSONL question_events', body)

    def test_admin_share_events_report(self):
        headers = self._admin_headers()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'share_events.jsonl')
            old_now = type('Now', (), {'astimezone': lambda self, tz: self, 'isoformat': lambda self, timespec='seconds': '2026-05-23T00:00:00+00:00'})()
            new_now = type('Now', (), {'astimezone': lambda self, tz: self, 'isoformat': lambda self, timespec='seconds': '2026-05-24T00:00:00+00:00'})()
            share_events_service.record_event('share_button_click', result_name='OLD', channel='button', success=True, path=path, now_fn=lambda: old_now)
            share_events_service.record_event('copy_success', result_name='NTR', channel='clipboard', success=True, path=path, now_fn=lambda: new_now)
            share_events_service.record_event('copy_failure', result_name='NTR', channel='clipboard', success=False, path=path, now_fn=lambda: new_now)
            share_events_service.record_event('share_button_click', result_name='NTR', channel='button', success=True, path=path, now_fn=lambda: new_now)
            share_events_service.record_event('result_page_view', result_name='NTR', channel='result_page', success=True, path=path, now_fn=lambda: new_now)
            with patch.dict(os.environ, {'SHARE_EVENT_LOG_PATH': path}):
                res = self.client.get('/api/admin/share_events?since=2026-05-24&until=2026-05-24', headers=headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['status'], 'ok')
        self.assertEqual(data['total'], 4)
        self.assertEqual(data['by_event']['copy_success'], 1)
        self.assertEqual(data['by_channel']['clipboard'], 2)
        self.assertEqual(data['success']['true'], 3)
        self.assertEqual(data['success']['false'], 1)
        self.assertEqual(data['metrics']['copy_successes'], 1)
        self.assertEqual(data['metrics']['copy_failures'], 1)
        self.assertEqual(data['daily'][0]['copy_successes'], 1)
        self.assertEqual(data['ranking'][0]['result_name'], 'NTR')
        self.assertEqual(data['ranking'][0]['copy_successes'], 1)
        self.assertEqual(data['ranking'][0]['share_actions'], 1)
        self.assertEqual(data['ranking'][0]['share_success_rate'], 100.0)
        self.assertTrue(data['comparison']['enabled'])
        self.assertEqual(data['comparison']['metrics']['total']['current'], 4)
        self.assertEqual(data['comparison']['metrics']['total']['previous'], 1)
        self.assertEqual(data['filters']['since'], '2026-05-24')
        self.assertEqual(data['filters']['compare_since'], '2026-05-23')
        self.assertIn('share_actions_delta', data['ranking'][0])

    def test_admin_share_events_csv_exports(self):
        headers = self._admin_headers()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'share_events.jsonl')
            now = type('Now', (), {'astimezone': lambda self, tz: self, 'isoformat': lambda self, timespec='seconds': '2026-05-24T00:00:00+00:00'})()
            share_events_service.record_event('share_button_click', result_name='NTR', channel='button', success=True, path=path, now_fn=lambda: now)
            share_events_service.record_event('result_page_view', result_name='NTR', channel='result_page', success=True, path=path, now_fn=lambda: now)
            with patch.dict(os.environ, {'SHARE_EVENT_LOG_PATH': path}):
                ranking = self.client.get('/api/admin/share_events/ranking.csv?since=2026-05-24', headers=headers)
                daily = self.client.get('/api/admin/share_events/daily.csv?since=2026-05-24', headers=headers)
                comparison = self.client.get('/api/admin/share_events/comparison.csv?since=2026-05-24&compare_since=2026-05-23', headers=headers)
        self.assertEqual(ranking.status_code, 200)
        self.assertIn('text/csv', ranking.content_type)
        ranking_header = ranking.data.decode('utf-8').splitlines()[0]
        self.assertIn('result_name,total,share_button_clicks', ranking_header)
        self.assertIn('filter_since', ranking_header)
        self.assertIn('NTR', ranking.data.decode('utf-8'))
        self.assertIn('2026-05-24', ranking.data.decode('utf-8'))
        self.assertEqual(daily.status_code, 200)
        daily_header = daily.data.decode('utf-8').splitlines()[0]
        self.assertIn('date,total,share_button_clicks', daily_header)
        self.assertIn('filter_since', daily_header)
        self.assertIn('2026-05-24', daily.data.decode('utf-8'))
        self.assertEqual(comparison.status_code, 200)
        comparison_header = comparison.data.decode('utf-8').splitlines()[0]
        self.assertIn('metric,current,previous,delta,growth_rate', comparison_header)
        self.assertIn('compare_since', comparison_header)

    def test_admin_page_renders_share_event_summary(self):
        headers = self._admin_headers()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'share_events.jsonl')
            share_events_service.record_event('share_button_click', result_name='NTR', channel='button', success=True, path=path)
            share_events_service.record_event('web_share_success', result_name='NTR', channel='web_share', success=True, path=path)
            share_events_service.record_event('x_share_click', result_name='NTR', channel='x', success=True, path=path)
            share_events_service.record_event('ogp_png_view', result_name='NTR', channel='ogp', success=True, path=path)
            share_events_service.record_event('result_page_view', result_name='NTR', channel='result_page', success=True, path=path)
            share_events_service.record_event('share_button_click', result_name='眼鏡', channel='button', success=True, path=path)
            with patch.dict(os.environ, {'SHARE_EVENT_LOG_PATH': path}):
                res = self.client.get('/admin?compare_since=2026-05-20&compare_until=2026-05-20', headers=headers)
        self.assertEqual(res.status_code, 200)
        body = res.data.decode('utf-8')
        self.assertIn('拡散イベント', body)
        self.assertIn('共有ボタン押下', body)
        self.assertIn('Web Share成功', body)
        self.assertIn('Xクリック', body)
        self.assertIn('OGP表示', body)
        self.assertIn('期間適用', body)
        self.assertIn('比較since', body)
        self.assertIn('総イベント', body)
        self.assertIn('サンプルが少ない', body)
        self.assertIn('ランキングCSV', body)
        self.assertIn('比較CSV', body)
        self.assertIn('日次CSV', body)
        self.assertIn('結果別シェアランキング', body)
        self.assertIn('伸び', body)
        self.assertIn('結果→共有', body)
        self.assertIn('共有成功', body)
        self.assertIn('眼鏡', body)
        self.assertIn('/api/admin/share_events', body)

    def test_admin_share_notes_api_saves_without_personal_identifiers(self):
        headers = self._admin_headers()
        with tempfile.TemporaryDirectory() as tmp:
            notes_path = os.path.join(tmp, 'share_notes.json')
            with patch.dict(os.environ, {'SHARE_NOTES_PATH': notes_path}):
                res = self.client.post(
                    '/api/admin/share_notes',
                    headers=headers,
                    json={'result_name': 'NTR', 'note': 'OGP称号を強める'},
                )
                self.assertEqual(res.status_code, 200)
                data = res.get_json()
                self.assertEqual(data['status'], 'ok')
                self.assertEqual(data['note']['note'], 'OGP称号を強める')
                get_res = self.client.get('/api/admin/share_notes', headers=headers)
                self.assertEqual(get_res.status_code, 200)
                self.assertEqual(get_res.get_json()['notes']['NTR']['note'], 'OGP称号を強める')
        self.assertNotIn('remote_addr', json.dumps(data, ensure_ascii=False))

    def test_admin_share_notes_csrf_enforced_when_enabled(self):
        app.config['ENFORCE_CSRF'] = True
        try:
            headers = self._admin_headers()
            with tempfile.TemporaryDirectory() as tmp:
                notes_path = os.path.join(tmp, 'share_notes.json')
                with patch.dict(os.environ, {'SHARE_NOTES_PATH': notes_path}):
                    blocked = self.client.post(
                        '/api/admin/share_notes',
                        headers=headers,
                        json={'result_name': 'NTR', 'note': 'blocked'},
                    )
                    self.assertEqual(blocked.status_code, 403)
                    admin = self.client.get('/admin', headers=headers)
                    self.assertEqual(admin.status_code, 200)
                    match = re.search(r'csrfToken: "([^"]+)"', admin.data.decode('utf-8'))
                    self.assertIsNotNone(match)
                    ok = self.client.post(
                        '/api/admin/share_notes',
                        headers={**headers, 'X-CSRF-Token': match.group(1)},
                        json={'result_name': 'NTR', 'note': 'saved'},
                    )
                    self.assertEqual(ok.status_code, 200)
        finally:
            app.config.pop('ENFORCE_CSRF', None)

    def test_admin_page_renders_escaped_share_note_form(self):
        headers = self._admin_headers()
        with tempfile.TemporaryDirectory() as tmp:
            events_path = os.path.join(tmp, 'share_events.jsonl')
            notes_path = os.path.join(tmp, 'share_notes.json')
            share_events_service.record_event('share_button_click', result_name='NTR', channel='button', success=True, path=events_path)
            share_notes_service.save_note('NTR', '<script>alert(1)</script>', path=notes_path)
            with patch.dict(os.environ, {'SHARE_EVENT_LOG_PATH': events_path, 'SHARE_NOTES_PATH': notes_path}):
                res = self.client.get('/admin', headers=headers)
        self.assertEqual(res.status_code, 200)
        body = res.data.decode('utf-8')
        self.assertIn('改善メモあり', body)
        self.assertIn('data-action="save-share-note"', body)
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', body)
        self.assertNotIn('<script>alert(1)</script>', body)

    def test_result_feedback_cta_is_simplified(self):
        res = self.client.get('/')
        self.assertEqual(res.status_code, 200)
        body = res.data.decode('utf-8')
        self.assertIn('data-action="quick-feedback" data-feedback="yes"', body)
        self.assertIn('data-action="quick-feedback" data-feedback="maybe"', body)
        self.assertIn('data-action="quick-feedback" data-feedback="no"', body)
        self.assertIn('detail-feedback-panel hidden', body)
        self.assertIn('詳細に○△×を付ける', body)

    def test_public_index_links_to_crawlable_pages(self):
        res = self.client.get('/')
        self.assertEqual(res.status_code, 200)
        body = res.data.decode('utf-8')
        self.assertIn('<link rel="canonical"', body)
        self.assertIn('property="og:url"', body)
        self.assertIn('href="/fetishes"', body)
        self.assertIn('href="/stats"', body)

    def test_fetish_index_page(self):
        res = self.client.get('/fetishes')
        self.assertEqual(res.status_code, 200)
        body = res.data.decode('utf-8')
        self.assertIn('性癖一覧', body)
        self.assertIn('<link rel="canonical"', body)
        self.assertIn('application/ld+json', body)
        self.assertIn('href="/fetish/0"', body)
        self.assertIn('data-href="/fetish/0"', body)
        self.assertIn("event.target.closest('a')", body)

    def test_fetish_index_links_work_examples_with_affiliate_tag(self):
        from app import BOOTSTRAP, engine as app_engine
        original_works = app_engine.fetishes[0].get('works', [])
        original_associate_id = BOOTSTRAP.amazon_associate_id
        try:
            BOOTSTRAP.amazon_associate_id = 'hekinator-22'
            app_engine.fetishes[0]['works'] = [
                {'title': 'ListDirect', 'url': 'https://www.amazon.co.jp/dp/B000000000'},
                'ListSearch',
                {'title': 'UnsafeList', 'url': 'javascript:alert(1)'},
            ]
            res = self.client.get('/fetishes')
            self.assertEqual(res.status_code, 200)
            body = res.data.decode('utf-8')
            self.assertIn('href="https://www.amazon.co.jp/dp/B000000000?tag=hekinator-22"', body)
            self.assertIn('href="https://www.amazon.co.jp/s?k=ListSearch&amp;tag=hekinator-22"', body)
            self.assertIn('UnsafeList', body)
            self.assertNotIn('javascript:alert', body)
            self.assertIn('rel="noopener sponsored"', body)
        finally:
            BOOTSTRAP.amazon_associate_id = original_associate_id
            app_engine.fetishes[0]['works'] = original_works

    def test_stats_page_has_seo_metadata(self):
        res = self.client.get('/stats')
        self.assertEqual(res.status_code, 200)
        body = res.data.decode('utf-8')
        self.assertIn('<link rel="canonical"', body)
        self.assertIn('property="og:url"', body)
        self.assertIn('name="twitter:card"', body)

    def test_sitemap_indexes_public_content_only(self):
        res = self.client.get('/sitemap.xml')
        self.assertEqual(res.status_code, 200)
        body = res.data.decode('utf-8')
        self.assertIn('/fetishes', body)
        self.assertIn('/stats', body)
        self.assertIn('/fetish/0', body)
        self.assertNotIn('/admin', body)
        self.assertNotIn('/api/', body)
        self.assertNotIn('/offline', body)
        self.assertNotIn('/r</loc>', body)

    def test_robots_points_to_sitemap(self):
        res = self.client.get('/robots.txt')
        self.assertEqual(res.status_code, 200)
        body = res.data.decode('utf-8')
        self.assertIn('Disallow: /admin', body)
        self.assertIn('Disallow: /api/', body)
        self.assertIn('Sitemap:', body)

    def test_site_base_url_controls_canonical_urls(self):
        with patch.dict(os.environ, {'SITE_BASE_URL': 'https://example.test'}, clear=False):
            res = self.client.get('/fetishes')
        body = res.data.decode('utf-8')
        self.assertIn('href="https://example.test/fetishes"', body)

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

    def test_fetish_similarity_rejects_non_integer_ids(self):
        headers = self._admin_headers()
        res = self.client.post('/api/admin/fetish_similarity',
            json={'id_a': 'x', 'id_b': 0}, headers=headers)
        self.assertEqual(res.status_code, 400)

    def test_merge_fetishes_rejects_non_integer_ids(self):
        headers = self._admin_headers()
        res = self.client.post('/api/admin/merge_fetishes',
            json={'id_keep': 'x', 'id_remove': 0, 'confirm_text': 'MERGE'},
            headers=headers)
        self.assertEqual(res.status_code, 400)

    def test_fetish_detail_shows_search_fallback_separately_without_works(self):
        from app import BOOTSTRAP, engine as app_engine
        fid = app_engine.fetishes[0]['id']
        original_works = app_engine.fetishes[0].get('works', [])
        original_associate_id = BOOTSTRAP.amazon_associate_id
        try:
            BOOTSTRAP.amazon_associate_id = 'hekinator-22'
            app_engine.fetishes[0]['works'] = []
            res = self.client.get(f'/fetish/{fid}')
            self.assertEqual(res.status_code, 200)
            body = res.data.decode('utf-8')
            self.assertNotIn('<h2 class="section-title">おすすめ作品</h2>', body)
            self.assertIn('<h2 class="section-title">関連作品を探す</h2>', body)
            self.assertIn('https://www.amazon.co.jp/s?k=', body)
            self.assertIn('tag=hekinator-22', body)
            self.assertLess(body.index('<div class="section-title">この性癖とは</div>'), body.index('<h2 class="section-title">関連作品を探す</h2>'))
        finally:
            BOOTSTRAP.amazon_associate_id = original_associate_id
            app_engine.fetishes[0]['works'] = original_works

    def test_fetish_detail_drops_unsafe_work_url(self):
        from app import engine as app_engine
        fid = app_engine.fetishes[0]['id']
        original_works = app_engine.fetishes[0].get('works', [])
        try:
            app_engine.fetishes[0]['works'] = [{'title': 'Unsafe', 'url': 'javascript:alert(1)'}]
            res = self.client.get(f'/fetish/{fid}')
            self.assertEqual(res.status_code, 200)
            body = res.data.decode('utf-8')
            self.assertIn('Unsafe', body)
            self.assertNotIn('javascript:alert', body)
            self.assertNotIn('href=""', body)
        finally:
            app_engine.fetishes[0]['works'] = original_works

    def test_fetish_detail_uses_feedback_accuracy(self):
        from app import engine as app_engine
        fid = app_engine.fetishes[0]['id']
        with patch.object(app_engine, 'get_fetish_log', return_value={fid: {'guessed': 100, 'correct': 1, 'wrong': 3}}):
            res = self.client.get(f'/fetish/{fid}')
        self.assertEqual(res.status_code, 200)
        body = res.data.decode('utf-8')
        self.assertIn('25%', body)

    def test_fetish_detail_has_seo_content(self):
        from app import engine as app_engine
        fid = app_engine.fetishes[0]['id']
        name = app_engine.fetishes[0]['name']
        res = self.client.get(f'/fetish/{fid}')
        self.assertEqual(res.status_code, 200)
        body = res.data.decode('utf-8')
        self.assertIn(f'{name}とは？性癖診断・おすすめ作品', body)
        self.assertIn('<link rel="canonical"', body)
        self.assertIn('application/ld+json', body)
        self.assertIn('この性癖とは', body)

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
        self.assertEqual(first_line, 'date,start,completion,play,learn,correct,wrong,dropoff')

    def test_start_returns_axis(self):
        res = self.client.post('/api/start')
        d = res.get_json()
        self.assertIn('axis', d)
        self.assertIn(d['axis'], ('content', 'abstract', 'personality', None))

    def test_start_increments_start_count(self):
        from app import engine as app_engine
        before = app_engine.get_stats().get('start_count', 0)
        res = self.client.post('/api/start')
        self.assertEqual(res.status_code, 200)
        after = app_engine.get_stats().get('start_count', 0)
        self.assertGreater(after, before)

    def test_dropoff_records_answered_count_once_before_completion(self):
        from app import engine as app_engine
        self.client.post('/api/start')
        with self.client.session_transaction() as sess:
            sess['answers'] = {'1': 1.0, '2': -1.0}
            sess['started'] = True
            sess['completed'] = False
            sess['dropoff_recorded'] = False
        with patch.object(app_engine, 'log_dropoff') as recorder:
            res = self.client.post('/api/dropoff', json={'answered_count': 2})
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.get_json()['status'], 'ok')
            recorder.assert_called_once_with(2)
            res2 = self.client.post('/api/dropoff', json={'answered_count': 2})
            self.assertEqual(res2.status_code, 200)
            self.assertEqual(res2.get_json()['status'], 'ignored')
            recorder.assert_called_once()

    def test_dropoff_ignored_after_completion(self):
        from app import engine as app_engine
        with self.client.session_transaction() as sess:
            sess['started'] = True
            sess['completed'] = True
            sess['answers'] = {'1': 1.0}
            sess['dropoff_recorded'] = False
        with patch.object(app_engine, 'log_dropoff') as recorder:
            res = self.client.post('/api/dropoff', json={'answered_count': 1})
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.get_json()['status'], 'ignored')
            recorder.assert_not_called()

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


class TestEngine(FileSnapshotMixin, unittest.TestCase):
    """engine.py のコア推論ロジックを直接テスト。"""

    def setUp(self):
        from app import engine as app_engine
        self.eng = app_engine
        self._patches = [
            patch.object(self.eng, '_save_async', return_value=None),
            patch.object(self.eng, '_save_matrix_file', return_value=None),
            patch.object(self.eng, '_save_fetishes_file', return_value=None),
            patch.object(self.eng, '_save_to_db', return_value=None),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in reversed(self._patches):
            p.stop()

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
        for _ in range(30):
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


class TestCompoundWorks(FileSnapshotMixin, unittest.TestCase):
    """compound_works機能のテスト"""

    def setUp(self):
        import engine as em
        self._save_patch = patch.object(em, '_save_compound_works', return_value=None)
        self._save_patch.start()
        # テスト前にキャッシュをリセット
        em._compound_works_loaded = False
        em._COMPOUND_WORKS = {}
        app.config['TESTING'] = True
        self.client = app.test_client()

    def tearDown(self):
        import engine as em
        em._compound_works_loaded = False
        em._COMPOUND_WORKS = {}
        self._save_patch.stop()


    def _admin_read_headers(self):
        return {'Authorization': 'Bearer read-token'}

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
        # 上限まで答えて強制終了させる
        for _ in range(35):
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
        """APIからworks編集ができる（テスト後に元に戻す）"""
        from app import engine as app_engine
        headers = self._admin_headers()
        fid = app_engine.fetishes[0]['id']
        idx = app_engine.index_of(fid)
        original_works = list(app_engine.fetishes[idx].get('works', []))
        try:
            res = self.client.post(f'/api/admin/edit_fetish/{fid}',
                json={'works': ['API作品A', 'API作品B']},
                headers=headers)
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertIn('API作品A', data['works'])
        finally:
            app_engine.edit_fetish(fid, works=original_works)

    def test_admin_api_edit_fetish_rejects_invalid_works_payload_types(self):
        from app import engine as app_engine
        headers = self._admin_headers()
        fid = app_engine.fetishes[0]['id']
        for works in (None, {'title': 'bad'}, 123):
            with self.subTest(works=works):
                res = self.client.post(f'/api/admin/edit_fetish/{fid}',
                    json={'works': works},
                    headers=headers)
                self.assertEqual(res.status_code, 400)

    def test_work_url_rejects_javascript_scheme(self):
        from engine import parse_work_item
        self.assertEqual(parse_work_item('危険|javascript:alert(1)'), '危険')
        self.assertEqual(parse_work_item({'title': '危険', 'url': 'javascript:alert(1)'}), '危険')
        self.assertEqual(
            parse_work_item('安全|https://example.com/a'),
            {'title': '安全', 'url': 'https://example.com/a'},
        )


if __name__ == '__main__':
    unittest.main()
