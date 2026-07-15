import unittest

import engine_mutations


class TestEngineMutationHelpers(unittest.TestCase):
    def test_next_player_and_first_free_seed_ids(self):
        fetishes = [{'id': 0}, {'id': 2}, {'id': 10000}, {'id': 10002}]
        self.assertEqual(engine_mutations.next_player_fetish_id(fetishes, 10000), 10003)
        self.assertEqual(engine_mutations.first_free_seed_id(fetishes, 10000), 1)

    def test_append_edit_delete_helpers_mutate_expected_structures(self):
        fetishes = []
        matrix = {'yes': [], 'total': []}
        idx = engine_mutations.append_fetish(
            fetishes, matrix, db_id=10000, name='A', desc='D', yes_row=[1.0], total_row=[2.0]
        )
        self.assertEqual(idx, 0)
        self.assertEqual(fetishes, [{'id': 10000, 'name': 'A', 'desc': 'D'}])
        engine_mutations.apply_fetish_edits(fetishes[0], name='B', works=['W'])
        self.assertEqual(fetishes[0], {'id': 10000, 'name': 'B', 'desc': 'D', 'works': ['W']})
        engine_mutations.delete_fetish_at(fetishes, matrix, 0)
        self.assertEqual(fetishes, [])
        self.assertEqual(matrix, {'yes': [], 'total': []})

    def test_merge_rows_and_log_entries(self):
        fetishes = [{'id': 1, 'name': 'A', 'desc': 'a'}, {'id': 2, 'name': 'B', 'desc': 'b'}]
        matrix = {'yes': [[1.0, 2.0], [3.0, 4.0]], 'total': [[5.0, 6.0], [7.0, 8.0]]}
        keep_name, keep_desc = engine_mutations.merge_fetish_rows(fetishes, matrix, 0, 1, new_name='Merged')
        self.assertEqual((keep_name, keep_desc), ('Merged', 'a'))
        self.assertEqual(fetishes, [{'id': 1, 'name': 'Merged', 'desc': 'a'}])
        self.assertEqual(matrix, {'yes': [[4.0, 6.0]], 'total': [[12.0, 14.0]]})
        self.assertEqual(
            engine_mutations.merge_log_entries({'1': {'guessed': 1, 'correct': 2}, '2': {'wrong': 3}}, 1, 2),
            {'1': {'guessed': 1, 'correct': 2, 'wrong': 3}},
        )
