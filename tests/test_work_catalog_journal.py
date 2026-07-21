import json
import tempfile
import unittest
from pathlib import Path

from engine import persistence, work_catalog
from storage import atomic_write_json


class WorkCatalogMutationJournalTests(unittest.TestCase):
    def _state(self, title):
        fetishes = [
            {'id': 1, 'name': 'A', 'desc': '', 'works': [title]},
            {'id': 2, 'name': 'B', 'desc': '', 'works': []},
        ]
        compounds = {'1,2': [title]}
        catalog = work_catalog.build_catalog_from_inline(
            fetishes,
            compound_rows=[{'id_a': 1, 'id_b': 2, 'works': [title]}],
        )
        return {'fetishes': fetishes, 'compound_works': compounds, 'work_catalog': catalog}

    def _paths(self, root):
        return (
            root / 'journal.json',
            root / 'fetishes.json',
            root / 'compound.json',
            root / 'catalog.json',
        )

    def test_commit_updates_all_files_and_removes_journal(self):
        before = self._state('Before')
        after = self._state('After')
        with tempfile.TemporaryDirectory() as temp:
            paths = self._paths(Path(temp))
            for path, value in zip(paths[1:], before.values()):
                atomic_write_json(path, value)
            persistence.commit_work_catalog_mutation(
                *paths,
                before=before,
                after=after,
                atomic_write=atomic_write_json,
            )
            self.assertFalse(paths[0].exists())
            self.assertEqual(json.loads(paths[1].read_text()), after['fetishes'])
            self.assertEqual(json.loads(paths[2].read_text()), after['compound_works'])
            self.assertEqual(json.loads(paths[3].read_text()), after['work_catalog'])

    def test_failed_commit_rolls_back_all_files(self):
        before = self._state('Before')
        after = self._state('After')
        with tempfile.TemporaryDirectory() as temp:
            paths = self._paths(Path(temp))
            for path, value in zip(paths[1:], before.values()):
                atomic_write_json(path, value)
            failed_once = False

            def fail_catalog_once(path, value, **kwargs):
                nonlocal failed_once
                if Path(path) == paths[3] and not failed_once:
                    failed_once = True
                    raise OSError('catalog write failed')
                atomic_write_json(path, value, **kwargs)

            with self.assertRaisesRegex(OSError, 'catalog write failed'):
                persistence.commit_work_catalog_mutation(
                    *paths,
                    before=before,
                    after=after,
                    atomic_write=fail_catalog_once,
                )
            self.assertFalse(paths[0].exists())
            self.assertEqual(json.loads(paths[1].read_text()), before['fetishes'])
            self.assertEqual(json.loads(paths[2].read_text()), before['compound_works'])
            self.assertEqual(json.loads(paths[3].read_text()), before['work_catalog'])

    def test_recovery_rolls_forward_valid_after_snapshot(self):
        before = self._state('Before')
        after = self._state('After')
        with tempfile.TemporaryDirectory() as temp:
            paths = self._paths(Path(temp))
            for path, value in zip(paths[1:], before.values()):
                atomic_write_json(path, value)
            atomic_write_json(paths[0], {'format_version': 1, 'before': before, 'after': after})

            recovered = persistence.recover_work_catalog_mutation(
                *paths,
                atomic_write=atomic_write_json,
            )

            self.assertTrue(recovered)
            self.assertFalse(paths[0].exists())
            self.assertEqual(json.loads(paths[1].read_text()), after['fetishes'])
            self.assertEqual(json.loads(paths[2].read_text()), after['compound_works'])
            self.assertEqual(json.loads(paths[3].read_text()), after['work_catalog'])

    def test_lifecycle_recovery_rolls_matrix_and_log_forward_with_catalog(self):
        before = self._state('Before')
        after = self._state('After')
        before.update(
            {
                'matrix': {'yes': [[2.0], [2.0]], 'total': [[4.0], [4.0]]},
                'fetish_log': {'1': {'guessed': 1, 'correct': 1, 'wrong': 0}},
            }
        )
        after['fetishes'] = after['fetishes'][:1]
        after['compound_works'] = {}
        after['work_catalog'] = work_catalog.delete_fetish_references(after['work_catalog'], 2)
        after.update(
            {
                'matrix': {'yes': [[3.0]], 'total': [[5.0]]},
                'fetish_log': {'1': {'guessed': 2, 'correct': 1, 'wrong': 1}},
            }
        )
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            paths = self._paths(root)
            matrix_path = root / 'matrix.json'
            log_path = root / 'fetish_log.json'
            atomic_write_json(paths[0], {'format_version': 2, 'before': before, 'after': after})

            recovered = persistence.recover_work_catalog_mutation(
                *paths,
                atomic_write=atomic_write_json,
                matrix_path=matrix_path,
                fetish_log_path=log_path,
                question_count=1,
            )

            self.assertTrue(recovered)
            self.assertEqual(json.loads(matrix_path.read_text()), after['matrix'])
            self.assertEqual(json.loads(log_path.read_text()), after['fetish_log'])
            self.assertEqual(json.loads(paths[3].read_text()), after['work_catalog'])

    def test_recovery_rejects_catalog_with_unknown_fetish(self):
        before = self._state('Before')
        after = self._state('After')
        after['fetishes'] = after['fetishes'][:1]
        with tempfile.TemporaryDirectory() as temp:
            paths = self._paths(Path(temp))
            atomic_write_json(paths[0], {'format_version': 1, 'before': before, 'after': after})
            with self.assertRaisesRegex(RuntimeError, 'journal is invalid'):
                persistence.recover_work_catalog_mutation(
                    *paths,
                    atomic_write=atomic_write_json,
                )
            self.assertTrue(paths[0].exists())


if __name__ == '__main__':
    unittest.main()
