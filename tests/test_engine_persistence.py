import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import engine_persistence


class TestEnginePersistenceHelpers(unittest.TestCase):
    def test_valid_matrix_shape_matches_engine_contract(self):
        self.assertTrue(engine_persistence.valid_matrix_shape({'yes': [[1.0]], 'total': [[2.0]]}, 1, 1))
        self.assertFalse(engine_persistence.valid_matrix_shape({'yes': [[1.0]], 'total': []}, 1, 1))
        self.assertFalse(engine_persistence.valid_matrix_shape({'yes': [[1.0, 2.0]], 'total': [[2.0]]}, 1, 1))
        self.assertFalse(engine_persistence.valid_matrix_shape([], 1, 1))

    def test_initial_matrix_applies_learned_priors_without_changing_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            learned_path = os.path.join(tmp, 'learned_priors.json')
            with open(learned_path, 'w', encoding='utf-8') as file_obj:
                json.dump({'10': {'1': 0.75}, '99': {'0': 0.9}}, file_obj)

            matrix = engine_persistence.initial_matrix(
                [{'id': 10}],
                [{'text': 'q0'}, {'text': 'q1'}],
                build_initial_matrix=lambda nf, nq: ([[2.0] * nq for _ in range(nf)], [[4.0] * nq for _ in range(nf)]),
                learned_priors_path=learned_path,
                pseudo=20,
            )

        self.assertEqual(matrix, {'yes': [[2.0, 15.0]], 'total': [[4.0, 20.0]]})

    def test_initial_matrix_ignores_invalid_learned_priors_like_engine_did(self):
        with tempfile.TemporaryDirectory() as tmp:
            learned_path = os.path.join(tmp, 'learned_priors.json')
            with open(learned_path, 'w', encoding='utf-8') as file_obj:
                file_obj.write('{bad json')

            matrix = engine_persistence.initial_matrix(
                [{'id': 10}],
                [{'text': 'q0'}],
                build_initial_matrix=lambda nf, nq: ([[2.0]], [[4.0]]),
                learned_priors_path=learned_path,
                pseudo=20,
            )

        self.assertEqual(matrix, {'yes': [[2.0]], 'total': [[4.0]]})

    def test_load_matrix_file_returns_existing_valid_matrix(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'matrix.json')
            with open(path, 'w', encoding='utf-8') as file_obj:
                json.dump({'yes': [[1.0]], 'total': [[2.0]]}, file_obj)

            matrix = engine_persistence.load_matrix_file(
                path,
                [{'id': 10}],
                [{'text': 'q0'}],
                init_matrix=lambda: self.fail('init should not run'),
            )

        self.assertEqual(matrix, {'yes': [[1.0]], 'total': [[2.0]]})

    def test_load_matrix_file_backs_up_invalid_shape_and_reinitializes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'matrix.json')
            with open(path, 'w', encoding='utf-8') as file_obj:
                json.dump({'yes': [], 'total': []}, file_obj)

            matrix = engine_persistence.load_matrix_file(
                path,
                [{'id': 10}],
                [{'text': 'q0'}],
                init_matrix=lambda: {'yes': [[2.0]], 'total': [[4.0]]},
            )

            self.assertEqual(matrix, {'yes': [[2.0]], 'total': [[4.0]]})
            self.assertFalse(os.path.exists(path))
            self.assertTrue(os.path.exists(path + '.bak'))

    def test_save_matrix_and_fetishes_file_preserve_atomic_write_arguments(self):
        writes = []
        engine_persistence.save_matrix_file('matrix.json', {'yes': [[1]], 'total': [[2]]}, atomic_write=lambda *args, **kwargs: writes.append((args, kwargs)))
        engine_persistence.save_fetishes_file('fetishes.json', [{'id': 1}], atomic_write=lambda *args, **kwargs: writes.append((args, kwargs)))

        self.assertEqual(writes[0], ((('matrix.json', {'yes': [[1]], 'total': [[2]]})), {}))
        self.assertEqual(writes[1], ((('fetishes.json', [{'id': 1}])), {'ensure_ascii': False, 'indent': 2}))

    def test_learned_priors_snapshot_uses_threshold_rounding_and_string_keys(self):
        probabilities = {
            (0, 0): 0.5,
            (0, 1): 0.551,
            (1, 0): 0.449,
            (1, 1): 0.7,
        }
        snapshot = engine_persistence.learned_priors_snapshot(
            [{'id': 10}, {'id': 20}],
            [{'text': 'q0'}, {'text': 'q1'}],
            probability=lambda f, q: probabilities[(f, q)],
        )
        self.assertEqual(snapshot, {'10': {'1': 0.551}, '20': {'0': 0.449, '1': 0.7}})

    def test_save_learned_priors_preserves_atomic_write_options(self):
        writes = []
        engine_persistence.save_learned_priors(
            'learned_priors.json',
            [{'id': 10}],
            [{'text': 'q0'}],
            probability=lambda f, q: 0.9,
            atomic_write=lambda *args, **kwargs: writes.append((args, kwargs)),
        )
        self.assertEqual(writes, [(('learned_priors.json', {'10': {'0': 0.9}}), {'ensure_ascii': False})])

    def test_save_questions_file_preserves_atomic_write_arguments(self):
        writes = []
        engine_persistence.save_questions_file('questions.json', [{'text': 'Q'}], atomic_write=lambda *args, **kwargs: writes.append((args, kwargs)))
        self.assertEqual(writes, [(('questions.json', [{'text': 'Q'}]), {})])
