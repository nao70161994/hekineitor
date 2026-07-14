import copy
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from engine import facade as engine_facade
from engine import persistence as engine_persistence
from scripts.validate_matrix_backup import validate
from services import rate_limit, server_session
from storage import atomic_write_json


class FinalReviewRegressionTests(unittest.TestCase):
    def test_file_engine_rejects_a_second_process(self):
        engine_facade.Engine()
        result = subprocess.run(
            [sys.executable, '-c', 'from engine.facade import Engine; Engine()'],
            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('supports one process only', result.stderr)

    def test_rejected_bucket_does_not_pin_capacity(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'rate.sqlite3')
            self.assertFalse(rate_limit._sqlite_shared_bucket(path, 'scope', 'A', 0, 60, 1, 1)[0])
            self.assertTrue(rate_limit._sqlite_shared_bucket(path, 'scope', 'A', 59, 60, 1, 1)[0])
            self.assertFalse(rate_limit._sqlite_shared_bucket(path, 'scope', 'B', 60, 60, 1, 1)[0])

    def test_sqlite_admission_locks_are_per_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'rate.sqlite3')
            acquired = threading.Event()

            def acquire_other_scope():
                with rate_limit._sqlite_admission_lock(path, 'admin'):
                    acquired.set()

            with rate_limit._sqlite_admission_lock(path, 'public'):
                thread = threading.Thread(target=acquire_other_scope)
                thread.start()
                self.assertTrue(acquired.wait(1))
            thread.join(1)
            self.assertFalse(thread.is_alive())

    def test_backup_validator_rejects_fractional_ids(self):
        payload = {
            'metadata': {'backup_format_version': 2},
            'fetishes': [{'id': 1.5, 'name': 'bad'}],
            'questions': [{'id': 0, 'matrix_index': 0}],
            'matrix_rows': [{'fetish_id': 1.5, 'question_id': 0, 'yes': 1, 'total': 2}],
        }
        with self.assertRaises(ValueError):
            validate(payload)

    def test_restore_journal_rejects_invalid_fetishes(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal = os.path.join(tmp, 'journal.json')
            snapshot = {'fetishes': [{}], 'matrix': {'yes': [[1]], 'total': [[2]]}}
            atomic_write_json(journal, {'format_version': 1, 'before': snapshot, 'after': snapshot})
            with self.assertRaises(RuntimeError):
                engine_persistence.recover_matrix_restore(
                    journal, os.path.join(tmp, 'fetishes.json'), os.path.join(tmp, 'matrix.json'),
                    1, atomic_write=atomic_write_json,
                )

    def test_atomic_write_propagates_directory_fsync_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch('storage.os.fsync', side_effect=[None, OSError('directory fsync failed')]):
                with self.assertRaises(OSError):
                    atomic_write_json(os.path.join(tmp, 'value.json'), {'ok': True})

    def test_db_edit_failure_does_not_mutate_memory(self):
        engine = engine_facade.Engine()
        before = copy.deepcopy(engine.fetishes[0])
        with patch.object(engine_facade, '_use_db', return_value=True), \
                patch.object(engine_facade.engine_db, 'update_fetish_fields', side_effect=RuntimeError('db')):
            with self.assertRaises(RuntimeError):
                engine.edit_fetish(before['id'], name='ghost')
        self.assertEqual(engine.fetishes[0], before)

    def test_testing_lock_reuse_is_a_single_release_alias(self):
        sid = 'reuse-depth'
        outer = server_session._acquire_request_lock(sid)
        inner = server_session._acquire_request_lock(sid, reuse_existing=True)
        self.assertIs(inner, outer)
        server_session._release_request_lock(inner)
        self.assertTrue(outer['released'])
        server_session._release_request_lock(outer)

    def test_db_learning_failure_rolls_back_its_memory_deltas(self):
        engine = engine_facade.Engine()
        before_yes = engine.matrix['yes'][0][0]
        before_total = engine.matrix['total'][0][0]
        engine.matrix['yes'][0][0] += 1.0
        engine.matrix['total'][0][0] += 2.0
        with patch.object(engine_facade, '_use_db', return_value=True), \
                patch.object(engine, '_save_to_db', side_effect=RuntimeError('db')):
            with self.assertRaises(RuntimeError):
                engine._save_async({0: [(0, 1.0, 2.0)]}, {0: engine.fetishes[0]['id']})
        self.assertEqual(engine.matrix['yes'][0][0], before_yes)
        self.assertEqual(engine.matrix['total'][0][0], before_total)

    def test_db_reload_refreshes_metadata_when_ids_are_unchanged(self):
        engine = engine_facade.Engine()
        fresh = copy.deepcopy(engine.fetishes)
        fresh[0]['name'] = 'updated by another worker'
        engine._matrix_last_loaded = 0
        with patch.object(engine_facade, '_use_db', return_value=True), \
                patch.object(engine, '_load_fetishes_from_db', return_value=fresh), \
                patch.object(engine, '_load_from_db', return_value=copy.deepcopy(engine.matrix)):
            engine._reload_matrix_if_stale()
        self.assertEqual(engine.fetishes[0]['name'], 'updated by another worker')


    def test_restore_workflow_exposes_explicit_ignore_input(self):
        workflow = Path('.github/workflows/restore_matrix.yml').read_text(encoding='utf-8')
        self.assertIn('allow_ignored_source_rows:', workflow)
        self.assertIn("payload['allow_ignored_source_rows'] = True", workflow)


if __name__ == '__main__':
    unittest.main()
