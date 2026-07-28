import json
import tempfile
import unittest
from pathlib import Path

from engine import persistence
from storage import atomic_write_json


class FeedbackBatchPersistenceTests(unittest.TestCase):
    def _state(self, value):
        return {
            'matrix': {'yes': [[value]], 'total': [[value + 1]]},
            'fetish_log': {'1': {'guessed': 1, 'correct': value, 'wrong': 0}},
            'stats': {'learn_count': value},
            'stats_history': {'2026-07-28': {'learn': value}},
        }

    def _paths(self, root):
        return tuple(root / name for name in ('journal.json', 'matrix.json', 'log.json', 'stats.json', 'history.json'))

    def test_commit_updates_every_feedback_file(self):
        before, after = self._state(1), self._state(2)
        with tempfile.TemporaryDirectory() as temp:
            paths = self._paths(Path(temp))
            for path, value in zip(paths[1:], before.values()):
                atomic_write_json(path, value)
            persistence.commit_feedback_batch(*paths, before=before, after=after, atomic_write=atomic_write_json)
            self.assertFalse(paths[0].exists())
            for path, value in zip(paths[1:], after.values()):
                self.assertEqual(json.loads(path.read_text()), value)

    def test_failed_commit_rolls_every_feedback_file_back(self):
        before, after = self._state(1), self._state(2)
        with tempfile.TemporaryDirectory() as temp:
            paths = self._paths(Path(temp))
            for path, value in zip(paths[1:], before.values()):
                atomic_write_json(path, value)
            failed = False

            def fail_stats_once(path, value, **kwargs):
                nonlocal failed
                if Path(path) == paths[3] and not failed:
                    failed = True
                    raise OSError('stats write failed')
                atomic_write_json(path, value, **kwargs)

            with self.assertRaisesRegex(OSError, 'stats write failed'):
                persistence.commit_feedback_batch(*paths, before=before, after=after, atomic_write=fail_stats_once)
            self.assertFalse(paths[0].exists())
            for path, value in zip(paths[1:], before.values()):
                self.assertEqual(json.loads(path.read_text()), value)

    def test_recovery_rolls_an_interrupted_batch_forward(self):
        before, after = self._state(1), self._state(2)
        with tempfile.TemporaryDirectory() as temp:
            paths = self._paths(Path(temp))
            for path, value in zip(paths[1:], before.values()):
                atomic_write_json(path, value)
            atomic_write_json(paths[0], {'format_version': 1, 'before': before, 'after': after})
            self.assertTrue(persistence.recover_feedback_batch(*paths, atomic_write=atomic_write_json))
            self.assertFalse(paths[0].exists())
            for path, value in zip(paths[1:], after.values()):
                self.assertEqual(json.loads(path.read_text()), value)


if __name__ == '__main__':
    unittest.main()
