import json
import os
import re
import struct
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ.setdefault('SECRET_KEY', 'test_secret_key_for_testing')

import engine as eng_module
from app import app
from engine import PLAYER_FETISH_BASE_ID, _use_db
from services import inference as inference_service
from services import learning as learning_service
from services import ogp as ogp_service
from services import quality_stats as quality_stats_service
from services import question_events as question_events_service
from services import result_exposure as result_exposure_service
from services import share_events as share_events_service
from services import share_links as share_links_service
from services import share_notes as share_notes_service
from services import test_play as test_play_service

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data')
DATA_FILES = (
    'fetish_log.json',
    'stats.json',
    'stats_history.json',
    'fetishes.json',
    'matrix.json',
    'questions.json',
    'compound_works.json',
    'question_flags.json',
    'config.json',
    'admin_audit_log.json',
    'share_events.jsonl',
    'question_events.jsonl',
    'share_links.json',
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


class APITestCase(FileSnapshotMixin, unittest.TestCase):
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
            res = self.client.post('/api/answer', json={'question_id': q, 'answer': 1.0})
            data = res.get_json()
            if data.get('action') == 'guess':
                return data
            q = data.get('question_id', q)
        return data

    def _adjusted_scores_for(self, top, second):
        def fake_adjusted_scores(engine, probs, ranked):
            scores = {}
            for position, index in enumerate(ranked):
                raw_probability = float(probs[index])
                if position == 0:
                    adjusted_score = top
                elif position == 1:
                    adjusted_score = second
                else:
                    adjusted_score = min(raw_probability, second) * 0.1
                scores[index] = {
                    'raw_probability': raw_probability,
                    'factor': adjusted_score / raw_probability if raw_probability else 1.0,
                    'adjusted_score': adjusted_score,
                }
            return scores

        return fake_adjusted_scores

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
                rows.append(
                    {
                        'fetish_id': f['id'],
                        'fetish_name': f['name'],
                        'question_id': qi,
                        'question_text': q['text'],
                        'yes': app_engine.matrix['yes'][fi][qi],
                        'total': app_engine.matrix['total'][fi][qi],
                    }
                )
        return rows


__all__ = [
    'os',
    'json',
    're',
    'time',
    'tempfile',
    'unittest',
    'struct',
    'patch',
    'app',
    'ogp_service',
    'quality_stats_service',
    'share_events_service',
    'question_events_service',
    'share_links_service',
    'share_notes_service',
    'result_exposure_service',
    'test_play_service',
    'inference_service',
    'learning_service',
    'eng_module',
    'PLAYER_FETISH_BASE_ID',
    '_use_db',
    'DATA_DIR',
    'DATA_FILES',
    'FileSnapshotMixin',
    'APITestCase',
]
