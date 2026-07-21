import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import engine as engine_module
from engine import PLAYER_FETISH_BASE_ID, Engine


class TestEngineMutations(unittest.TestCase):
    def setUp(self):
        self._patches = [
            patch.object(Engine, '_save_matrix_file', return_value=None),
            patch.object(Engine, '_save_fetishes_file', return_value=None),
            patch.object(Engine, '_save_to_db', return_value=None),
            patch.object(Engine, '_load_matrix_file', new=lambda self: self._init_matrix_file()),
        ]
        for patcher in self._patches:
            patcher.start()
        self.engine = Engine()

    def tearDown(self):
        for patcher in self._patches:
            patcher.stop()

    def test_learn_silent_cold_start_updates_only_target_without_learn_count(self):
        target_before_yes = self.engine.matrix['yes'][0][8]
        target_before_total = self.engine.matrix['total'][0][8]
        other_before_yes = self.engine.matrix['yes'][1][8]
        other_before_total = self.engine.matrix['total'][1][8]
        with (
            patch.object(self.engine, '_save_async', return_value=None) as save_async,
            patch.object(self.engine, '_increment_learn_count', return_value=None) as increment,
        ):
            self.engine._learn_silent({'8': 1.0}, 0, cold_start=True)
        self.assertEqual(self.engine.matrix['yes'][0][8], target_before_yes + 1.0)
        self.assertEqual(self.engine.matrix['total'][0][8], target_before_total + 1.0)
        self.assertEqual(self.engine.matrix['yes'][1][8], other_before_yes)
        self.assertEqual(self.engine.matrix['total'][1][8], other_before_total)
        save_async.assert_called_once()
        increment.assert_not_called()

    def test_add_fetish_local_assigns_next_player_id_and_copies_template_row(self):
        with (
            patch.object(engine_module, '_use_db', return_value=False),
            patch.object(self.engine, '_save_fetishes_file', return_value=None) as save_fetishes,
        ):
            idx, db_id = self.engine.add_fetish('追加テスト', 'desc', {'8': 1})
        self.assertEqual(idx, len(self.engine.fetishes) - 1)
        self.assertGreaterEqual(db_id, PLAYER_FETISH_BASE_ID)
        self.assertEqual(self.engine.fetishes[idx], {'id': db_id, 'name': '追加テスト', 'desc': 'desc'})
        self.assertEqual(len(self.engine.matrix['yes'][idx]), len(self.engine.questions))
        self.assertEqual(len(self.engine.matrix['total'][idx]), len(self.engine.questions))
        save_fetishes.assert_called_once_with()

    def test_edit_fetish_local_updates_only_provided_fields(self):
        original_desc = self.engine.fetishes[0]['desc']
        with (
            patch.object(engine_module, '_use_db', return_value=False),
            patch.object(self.engine, '_commit_local_work_catalog_state', return_value=None) as commit_catalog,
        ):
            ok = self.engine.edit_fetish(self.engine.fetishes[0]['id'], name='編集名', works=['W'])
        self.assertTrue(ok)
        self.assertEqual(self.engine.fetishes[0]['name'], '編集名')
        self.assertEqual(self.engine.fetishes[0]['desc'], original_desc)
        self.assertEqual(self.engine.fetishes[0]['works'], ['W'])
        commit_catalog.assert_called_once()
        before, after = commit_catalog.call_args.args
        self.assertNotEqual(before['work_catalog'], after['work_catalog'])

    def test_delete_fetish_local_rejects_seed_and_removes_player_rows(self):
        seed_id = self.engine.fetishes[0]['id']
        self.assertFalse(self.engine.delete_fetish(seed_id))
        with (
            patch.object(engine_module, '_use_db', return_value=False),
            patch.object(self.engine, '_save_fetishes_file', return_value=None) as save_fetishes,
            patch.object(self.engine, '_save_matrix_file', return_value=None) as save_matrix,
            patch.object(self.engine, '_commit_local_work_catalog_state', return_value=None) as commit_catalog,
        ):
            idx, db_id = self.engine.add_fetish('削除テスト', 'desc', {})
            ok = self.engine.delete_fetish(db_id)
        self.assertTrue(ok)
        self.assertIsNone(self.engine.index_of(db_id))
        self.assertEqual(len(self.engine.matrix['yes']), len(self.engine.fetishes))
        self.assertEqual(len(self.engine.matrix['total']), len(self.engine.fetishes))
        self.assertGreaterEqual(save_fetishes.call_count, 1)
        self.assertEqual(save_matrix.call_count, 1)
        commit_catalog.assert_called_once()
        self.assertIn('matrix', commit_catalog.call_args.args[1])

    def test_merge_fetishes_local_adds_matrix_rows_and_merges_log_entries(self):
        id_keep = self.engine.fetishes[0]['id']
        id_remove = self.engine.fetishes[1]['id']
        yes_keep = list(self.engine.matrix['yes'][0])
        yes_remove = list(self.engine.matrix['yes'][1])
        total_keep = list(self.engine.matrix['total'][0])
        total_remove = list(self.engine.matrix['total'][1])
        with (
            patch.object(engine_module, '_use_db', return_value=False),
            patch.object(self.engine, '_commit_local_work_catalog_state', return_value=None) as commit_catalog,
        ):
            ok = self.engine.merge_fetishes(id_keep, id_remove, new_name='統合名')
        self.assertTrue(ok)
        self.assertIsNone(self.engine.index_of(id_remove))
        keep_idx = self.engine.index_of(id_keep)
        self.assertEqual(self.engine.fetishes[keep_idx]['name'], '統合名')
        self.assertEqual(self.engine.matrix['yes'][keep_idx], [a + b for a, b in zip(yes_keep, yes_remove)])
        self.assertEqual(self.engine.matrix['total'][keep_idx], [a + b for a, b in zip(total_keep, total_remove)])
        before, after = commit_catalog.call_args.args
        keep_log = before['fetish_log'].get(str(id_keep), {})
        remove_log = before['fetish_log'].get(str(id_remove), {})
        self.assertEqual(
            after['fetish_log'][str(id_keep)],
            {key: keep_log.get(key, 0) + remove_log.get(key, 0) for key in ('guessed', 'correct', 'wrong')},
        )
        self.assertNotIn(str(id_remove), after['fetish_log'])

    def test_promote_fetish_local_moves_player_id_to_first_free_seed_id(self):
        with (
            patch.object(engine_module, '_use_db', return_value=False),
            patch.object(self.engine, '_save_fetishes_file', return_value=None),
            patch.object(self.engine, '_commit_local_work_catalog_state', return_value=None) as commit_catalog,
        ):
            idx, player_id = self.engine.add_fetish('昇格テスト', 'desc', {})
            old_seed_id = self.engine.fetishes[0]['id']
            self.engine.fetishes[0]['id'] = 9999
            new_id = self.engine.promote_fetish(player_id)
        self.assertEqual(new_id, old_seed_id)
        self.assertIsNotNone(self.engine.index_of(new_id))
        self.assertIsNone(self.engine.index_of(player_id))
        commit_catalog.assert_called_once()

    def test_promote_fetish_db_uses_authoritative_db_id_selection(self):
        with patch.object(engine_module, '_use_db', return_value=False):
            idx, player_id = self.engine.add_fetish('DB昇格テスト', 'desc', {})
        with (
            patch.object(engine_module, '_use_db', return_value=True),
            patch.object(
                engine_module.facade,
                'psycopg2',
                type('Psycopg2', (), {'extras': type('Extras', (), {'execute_values': None})}),
            ),
            patch.object(engine_module.engine_db, 'promote_player_fetish_to_seed', return_value=7) as helper,
        ):
            new_id = self.engine.promote_fetish(player_id)

        self.assertEqual(new_id, 7)
        self.assertIsNotNone(self.engine.index_of(7))
        self.assertIsNone(self.engine.index_of(player_id))
        helper.assert_called_once()
        self.assertEqual(helper.call_args.args[0], player_id)
        self.assertEqual(helper.call_args.kwargs['player_base_id'], PLAYER_FETISH_BASE_ID)

    def test_promote_fetish_db_keeps_memory_id_when_db_rejects(self):
        with patch.object(engine_module, '_use_db', return_value=False):
            idx, player_id = self.engine.add_fetish('DB昇格失敗テスト', 'desc', {})
        with (
            patch.object(engine_module, '_use_db', return_value=True),
            patch.object(
                engine_module.facade,
                'psycopg2',
                type('Psycopg2', (), {'extras': type('Extras', (), {'execute_values': None})}),
            ),
            patch.object(engine_module.engine_db, 'promote_player_fetish_to_seed', return_value=None),
        ):
            new_id = self.engine.promote_fetish(player_id)

        self.assertIsNone(new_id)
        self.assertIsNotNone(self.engine.index_of(player_id))
