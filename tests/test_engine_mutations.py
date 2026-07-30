import copy
import json
import os
import sys
import unittest
from pathlib import Path
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
            {
                key: keep_log.get(key, 0) + remove_log.get(key, 0)
                for key in ('guessed', 'correct', 'wrong', 'correction_selected')
            },
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

    def test_review_manifest_local_mutation_commits_complete_resolved_catalog(self):
        fetish_id = self.engine.fetishes[0]['id']
        fetishes = [
            {
                'id': fetish_id,
                'name': 'Review target',
                'desc': '',
                'works': ['Same（A）', 'Same（B）'],
            }
        ]
        catalog = engine_module.work_catalog.build_catalog_from_inline(fetishes)
        review = catalog['review_queue'][0]
        manifest = {
            'schema_version': 1,
            'reviewed_at': '2026-07-28',
            'decisions': [
                {
                    'review_id': review['review_id'],
                    'candidate_key': review['candidate_key'],
                    'work_ids': review['work_ids'],
                    'decision': 'merge',
                    'target_work_id': review['work_ids'][0],
                }
            ],
        }
        before = {'fetishes': fetishes, 'compound_works': {}, 'work_catalog': catalog}

        def local_state(**values):
            if not values:
                return before
            return {
                'fetishes': values['fetishes'],
                'compound_works': values['compound_works'],
                'work_catalog': values['work_catalog'],
            }

        with (
            patch.object(engine_module, '_use_db', return_value=False),
            patch.object(self.engine, '_local_work_catalog_state', side_effect=local_state),
            patch.object(self.engine, '_commit_local_work_catalog_state', return_value=None) as commit_catalog,
        ):
            result = self.engine.mutate_work_catalog(
                'review_apply_manifest',
                {'decision_manifest': manifest},
                expected_digest=engine_module.work_catalog.catalog_digest(catalog),
            )

        self.assertEqual(result['result'], {'resolved_count': 1, 'pending_count': 0})
        commit_catalog.assert_called_once()
        committed = commit_catalog.call_args.args[1]['work_catalog']
        self.assertEqual(len(committed['works_master']), 1)
        self.assertEqual(committed['review_queue'][0]['status'], 'resolved')

    def test_seed_override_manifest_commits_catalog_atomically(self):
        fetishes = [{'id': 1, 'name': 'Target', 'desc': '', 'works': ['作品名（人物）']}]
        catalog = engine_module.work_catalog.build_catalog_from_inline(fetishes)
        before = {'fetishes': fetishes, 'compound_works': {}, 'work_catalog': catalog}
        manifest = {
            'schema_version': 1,
            'remove_display_titles': [],
            'title_normalizations': [
                {
                    'display_title': '作品名（人物）',
                    'canonical_title': '作品名',
                    'context_label': '人物',
                }
            ],
        }

        def local_state(**values):
            if not values:
                return before
            return {
                'fetishes': values['fetishes'],
                'compound_works': values['compound_works'],
                'work_catalog': values['work_catalog'],
            }

        with (
            patch.object(engine_module, '_use_db', return_value=False),
            patch.object(self.engine, '_local_work_catalog_state', side_effect=local_state),
            patch.object(self.engine, '_commit_local_work_catalog_state', return_value=None) as commit_catalog,
        ):
            result = self.engine.mutate_work_catalog(
                'seed_overrides_apply_manifest',
                {'seed_overrides': manifest},
                expected_digest=engine_module.work_catalog.catalog_digest(catalog),
            )

        self.assertEqual(result['result'], {'normalized_title_count': 1, 'removed_work_count': 0})
        commit_catalog.assert_called_once()
        committed = commit_catalog.call_args.args[1]['work_catalog']
        self.assertEqual(committed['works_master'][0]['canonical_title'], '作品名')
        self.assertEqual(committed['fetish_work_links'][0]['context_label'], '人物')

    def test_identifier_admin_operations_commit_catalog_atomically(self):
        fetishes = [
            {
                'id': 1,
                'name': 'Target',
                'desc': '',
                'works': [
                    {
                        'title': 'Managed edition',
                        'url': 'https://www.amazon.co.jp/dp/B012345678',
                    }
                ],
            }
        ]
        catalog = engine_module.work_catalog.build_catalog_from_inline(fetishes)
        edition_id = catalog['work_editions'][0]['edition_id']
        state = {'fetishes': fetishes, 'compound_works': {}, 'work_catalog': catalog}

        def local_state(**values):
            if not values:
                return copy.deepcopy(state)
            return {
                'fetishes': values['fetishes'],
                'compound_works': values['compound_works'],
                'work_catalog': values['work_catalog'],
            }

        def commit_state(_before, after):
            state.update(copy.deepcopy(after))

        with (
            patch.object(engine_module, '_use_db', return_value=False),
            patch.object(self.engine, '_local_work_catalog_state', side_effect=local_state),
            patch.object(self.engine, '_commit_local_work_catalog_state', side_effect=commit_state) as commit_catalog,
        ):
            created = self.engine.mutate_work_catalog(
                'identifier_create',
                {'edition_id': edition_id, 'scheme': 'isbn', 'authority': 'isbn', 'value': '9784199007804'},
                expected_digest=engine_module.work_catalog.catalog_digest(catalog),
            )
            identifier_id = created['result']
            updated = self.engine.mutate_work_catalog(
                'identifier_update',
                {
                    'identifier_id': identifier_id,
                    'edition_id': edition_id,
                    'scheme': 'isbn',
                    'authority': 'isbn',
                    'value': '9784101010014',
                },
                expected_digest=created['digest'],
            )
            next_identifier_id = updated['result']
            deleted = self.engine.mutate_work_catalog(
                'identifier_delete',
                {'identifier_id': next_identifier_id},
                expected_digest=updated['digest'],
            )

        self.assertNotEqual(identifier_id, next_identifier_id)
        self.assertIsNone(deleted['result'])
        self.assertEqual(state['work_catalog']['work_edition_identifiers'], [])
        self.assertEqual(commit_catalog.call_count, 3)

    def _production_correction_state(self):
        data = Path(__file__).resolve().parents[1] / 'data'
        fetishes = json.loads((data / 'fetishes.json').read_text(encoding='utf-8'))
        compounds = json.loads((data / 'compound_works.json').read_text(encoding='utf-8'))
        catalog = json.loads((data / 'work_catalog.json').read_text(encoding='utf-8'))
        corrections = json.loads((data / 'work_catalog_corrections.json').read_text(encoding='utf-8'))
        source = engine_module.work_catalog.project_approved_inline_corrections(
            fetishes,
            compound_rows=compounds,
            corrections=corrections,
            direction='reverse',
        )
        fetishes, compounds = source['fetishes'], source['compound_rows']
        player_works = [
            {
                'title': '誰かこの状況を説明してください！',
                'url': 'https://www.amazon.co.jp/dp/B07DL6G318?tag=hekinator-22',
            },
            {
                'title': 'わたしの幸せな結婚',
                'url': 'https://www.amazon.co.jp/dp/B07X25T546?tag=hekinator-22',
            },
        ]
        next(row for row in fetishes if row['id'] == 104)['works'] = player_works
        catalog = engine_module.work_catalog.replace_fetish_works(catalog, 104, player_works)
        return {'fetishes': fetishes, 'compound_works': compounds, 'work_catalog': catalog}, corrections, player_works

    def _restore_catalog_fixture(self, *, corrected, inline_target, player_replacement=False):
        data = Path(__file__).resolve().parents[1] / 'data'
        fetishes = json.loads((data / 'fetishes.json').read_text(encoding='utf-8'))
        compounds = json.loads((data / 'compound_works.json').read_text(encoding='utf-8'))
        corrections = json.loads((data / 'work_catalog_corrections.json').read_text(encoding='utf-8'))
        seed = json.loads((data / 'work_catalog_seed_overrides.json').read_text(encoding='utf-8'))
        review = json.loads((data / 'work_catalog_review_decisions.json').read_text(encoding='utf-8'))
        source = engine_module.work_catalog.project_approved_inline_corrections(
            fetishes,
            compound_rows=compounds,
            corrections=corrections,
            direction='reverse',
        )
        fetishes, compounds = source['fetishes'], source['compound_rows']
        source_catalog = engine_module.work_catalog.build_catalog_from_inline(
            fetishes,
            compound_rows=[
                {
                    'key': key,
                    'id_a': int(key.split(',')[0]),
                    'id_b': int(key.split(',')[1]),
                    'works': works,
                }
                for key, works in compounds.items()
            ],
            seed_overrides=seed,
        )
        source_catalog = engine_module.work_catalog.apply_review_decisions(source_catalog, review)
        catalog = (
            engine_module.work_catalog.apply_catalog_corrections(source_catalog, corrections)
            if corrected
            else source_catalog
        )
        projection = engine_module.work_catalog.project_approved_inline_corrections(
            fetishes,
            compound_rows=compounds,
            corrections=corrections,
        )
        if inline_target:
            fetishes, compounds = projection['fetishes'], projection['compound_rows']
        if player_replacement:
            player_works = [
                {
                    'title': '誰かこの状況を説明してください！',
                    'url': 'https://www.amazon.co.jp/dp/B07DL6G318?tag=hekinator-22',
                },
                {
                    'title': 'わたしの幸せな結婚',
                    'url': 'https://www.amazon.co.jp/dp/B07X25T546?tag=hekinator-22',
                },
            ]
            next(row for row in fetishes if row['id'] == 104)['works'] = player_works
            catalog = engine_module.work_catalog.replace_fetish_works(catalog, 104, player_works)
        return catalog, fetishes, compounds, corrections

    def _run_local_v3_restore(self, catalog, exported_fetishes, compounds, corrections):
        self.engine.fetishes = copy.deepcopy(exported_fetishes)
        before = {
            'fetishes': copy.deepcopy(exported_fetishes),
            'compound_works': copy.deepcopy(compounds),
            'work_catalog': copy.deepcopy(catalog),
            'matrix': copy.deepcopy(self.engine.matrix),
            'fetish_log': {},
        }

        def local_state(**values):
            if not values or set(values) == {'include_lifecycle'}:
                return copy.deepcopy(before)
            return {
                'fetishes': copy.deepcopy(values['fetishes']),
                'compound_works': copy.deepcopy(values['compound_works']),
                'work_catalog': copy.deepcopy(values['work_catalog']),
                'matrix': copy.deepcopy(values['matrix']),
                'fetish_log': copy.deepcopy(values['fetish_log']),
            }

        def load_json(name):
            if name == 'work_catalog_corrections.json':
                return copy.deepcopy(corrections)
            if name == 'compound_works.json':
                return copy.deepcopy(compounds)
            raise AssertionError(name)

        with (
            patch.object(engine_module, '_use_db', return_value=False),
            patch.object(self.engine, '_local_work_catalog_state', side_effect=local_state),
            patch.object(self.engine, '_load_json', side_effect=load_json),
            patch.object(self.engine, '_commit_local_work_catalog_state') as commit_catalog,
        ):
            self.engine.restore_matrix_snapshot(exported_fetishes, [], work_catalog=catalog)
        return commit_catalog.call_args.args[1]

    def test_v3_restore_forwards_old_inline_for_a_corrected_catalog_and_preserves_player_owner(self):
        catalog, old_inline, compounds, corrections = self._restore_catalog_fixture(
            corrected=True,
            inline_target=False,
            player_replacement=True,
        )

        restored = self._run_local_v3_restore(catalog, old_inline, compounds, corrections)

        parity = engine_module.work_catalog.catalog_parity_report(
            catalog, restored['fetishes'], compound_rows=restored['compound_works']
        )
        self.assertTrue(parity['automated_parity_ok'])
        expected_player = next(row for row in old_inline if row['id'] == 104)['works']
        self.assertEqual(next(row for row in restored['fetishes'] if row['id'] == 104)['works'], expected_player)

    def test_v3_restore_keeps_source_inline_for_a_pre_correction_catalog(self):
        catalog, old_inline, compounds, corrections = self._restore_catalog_fixture(
            corrected=False,
            inline_target=False,
        )
        digest = engine_module.work_catalog.catalog_digest(catalog)

        restored = self._run_local_v3_restore(catalog, old_inline, compounds, corrections)

        self.assertEqual(engine_module.work_catalog.catalog_digest(restored['work_catalog']), digest)
        parity = engine_module.work_catalog.catalog_parity_report(
            catalog, restored['fetishes'], compound_rows=restored['compound_works']
        )
        self.assertTrue(parity['automated_parity_ok'])

    def test_db_v3_restore_rejects_source_catalog_without_matching_compound_deploy(self):
        catalog, old_inline, compounds, corrections = self._restore_catalog_fixture(
            corrected=False,
            inline_target=False,
        )
        target_compounds = engine_module.work_catalog.project_approved_inline_corrections(
            old_inline,
            compound_rows=compounds,
            corrections=corrections,
        )['compound_rows']
        self.engine.fetishes = copy.deepcopy(old_inline)

        def load_json(name):
            return copy.deepcopy(corrections if name == 'work_catalog_corrections.json' else target_compounds)

        with (
            patch.object(engine_module, '_use_db', return_value=True),
            patch.object(self.engine, '_load_json', side_effect=load_json),
            patch.object(
                engine_module.facade,
                'psycopg2',
                type('Psycopg2', (), {'extras': type('Extras', (), {'execute_values': None})}),
            ),
            patch.object(engine_module.engine_db, 'restore_matrix_snapshot') as restore_db,
            self.assertRaisesRegex(ValueError, 'matching source compound deploy'),
        ):
            self.engine.restore_matrix_snapshot(old_inline, [], work_catalog=catalog)

        restore_db.assert_not_called()

    def test_db_v3_restore_rejects_corrected_catalog_without_matching_compound_deploy(self):
        catalog, old_inline, source_compounds, corrections = self._restore_catalog_fixture(
            corrected=True,
            inline_target=False,
        )
        self.engine.fetishes = copy.deepcopy(old_inline)

        def load_json(name):
            return copy.deepcopy(corrections if name == 'work_catalog_corrections.json' else source_compounds)

        with (
            patch.object(engine_module, '_use_db', return_value=True),
            patch.object(self.engine, '_load_json', side_effect=load_json),
            patch.object(
                engine_module.facade,
                'psycopg2',
                type('Psycopg2', (), {'extras': type('Extras', (), {'execute_values': None})}),
            ),
            patch.object(engine_module.engine_db, 'restore_matrix_snapshot') as restore_db,
            self.assertRaisesRegex(ValueError, 'matching target compound deploy'),
        ):
            self.engine.restore_matrix_snapshot(old_inline, [], work_catalog=catalog)

        restore_db.assert_not_called()

    def test_db_v3_restore_accepts_corrected_catalog_with_corrected_compound_deploy(self):
        catalog, old_inline, compounds, corrections = self._restore_catalog_fixture(
            corrected=True,
            inline_target=False,
        )
        projection = engine_module.work_catalog.project_approved_inline_corrections(
            old_inline,
            compound_rows=compounds,
            corrections=corrections,
        )
        self.engine.fetishes = copy.deepcopy(old_inline)

        def load_json(name):
            return copy.deepcopy(
                corrections if name == 'work_catalog_corrections.json' else projection['compound_rows']
            )

        with (
            patch.object(engine_module, '_use_db', return_value=True),
            patch.object(self.engine, '_load_json', side_effect=load_json),
            patch.object(
                engine_module.facade,
                'psycopg2',
                type('Psycopg2', (), {'extras': type('Extras', (), {'execute_values': None})}),
            ),
            patch.object(
                engine_module.engine_db,
                'restore_matrix_snapshot',
                return_value=projection['fetishes'],
            ) as restore_db,
        ):
            self.engine.restore_matrix_snapshot(old_inline, [], work_catalog=catalog)

        restore_db.assert_called_once()
        parity = engine_module.work_catalog.catalog_parity_report(
            catalog,
            self.engine.fetishes,
            compound_rows=projection['compound_rows'],
        )
        self.assertTrue(parity['automated_parity_ok'])

    def test_v3_restore_is_idempotent_for_corrected_inline(self):
        catalog, corrected_inline, compounds, corrections = self._restore_catalog_fixture(
            corrected=True,
            inline_target=True,
        )

        restored = self._run_local_v3_restore(catalog, corrected_inline, compounds, corrections)

        self.assertEqual(restored['fetishes'], corrected_inline)
        self.assertEqual(restored['compound_works'], compounds)

    def test_correction_manifest_syncs_local_inline_fallback_in_the_same_commit(self):
        before, corrections, player_works = self._production_correction_state()
        self.engine.fetishes = copy.deepcopy(before['fetishes'])

        def local_state(**values):
            if not values:
                return before
            return {
                'fetishes': values['fetishes'],
                'compound_works': values['compound_works'],
                'work_catalog': values['work_catalog'],
            }

        with (
            patch.object(engine_module, '_use_db', return_value=False),
            patch.object(self.engine, '_local_work_catalog_state', side_effect=local_state),
            patch.object(self.engine, '_commit_local_work_catalog_state') as commit_catalog,
        ):
            result = self.engine.mutate_work_catalog(
                'corrections_apply_manifest',
                {'corrections_manifest': corrections},
                expected_digest=engine_module.work_catalog.catalog_digest(before['work_catalog']),
            )

        after = commit_catalog.call_args.args[1]
        parity = engine_module.work_catalog.catalog_parity_report(
            after['work_catalog'],
            after['fetishes'],
            compound_rows=after['compound_works'],
        )
        self.assertTrue(parity['automated_parity_ok'])
        self.assertEqual(result['result']['inline_applied_link_count'], 56)
        self.assertEqual(result['result']['inline_fetish_owner_count'], 9)
        self.assertEqual(result['result']['inline_compound_owner_count'], 27)
        self.assertEqual(result['result']['inline_missing_count'], 2)
        self.assertEqual(next(row for row in after['fetishes'] if row['id'] == 104)['works'], player_works)
        self.assertEqual(next(row for row in self.engine.fetishes if row['id'] == 104)['works'], player_works)

    def test_correction_manifest_does_not_publish_db_inline_before_transaction_commit(self):
        before, corrections, _player_works = self._production_correction_state()
        original = copy.deepcopy(before['fetishes'])
        self.engine.fetishes = copy.deepcopy(original)

        with (
            patch.object(engine_module, '_use_db', return_value=True),
            patch.object(
                engine_module.facade,
                'psycopg2',
                type('Psycopg2', (), {'extras': type('Extras', (), {'execute_values': None})}),
            ),
            patch.object(engine_module.engine_db, 'mutate_work_catalog', side_effect=OSError('db rollback')),
            self.assertRaisesRegex(OSError, 'db rollback'),
        ):
            self.engine.mutate_work_catalog(
                'corrections_apply_manifest',
                {'corrections_manifest': corrections},
                expected_digest=engine_module.work_catalog.catalog_digest(before['work_catalog']),
            )

        self.assertEqual(self.engine.fetishes, original)

    def test_correction_manifest_does_not_publish_local_inline_before_commit(self):
        before, corrections, _player_works = self._production_correction_state()
        original = copy.deepcopy(before['fetishes'])
        self.engine.fetishes = copy.deepcopy(original)

        with (
            patch.object(engine_module, '_use_db', return_value=False),
            patch.object(self.engine, '_local_work_catalog_state', return_value=before),
            patch.object(self.engine, '_commit_local_work_catalog_state', side_effect=OSError('disk full')),
            self.assertRaisesRegex(OSError, 'disk full'),
        ):
            self.engine.mutate_work_catalog(
                'corrections_apply_manifest',
                {'corrections_manifest': corrections},
                expected_digest=engine_module.work_catalog.catalog_digest(before['work_catalog']),
            )

        self.assertEqual(self.engine.fetishes, original)

    def test_correction_manifest_commits_catalog_atomically(self):
        catalog = engine_module.work_catalog.build_catalog_from_inline([{'id': 1, 'works': ['Before']}])
        corrected = copy.deepcopy(catalog)
        corrected['works_master'][0]['canonical_title'] = 'After'
        corrected['works_master'][0]['normalized_title'] = 'after'
        manifest = {
            'schema_version': 1,
            'catalog_schema_version': 1,
            'corrections': [
                {'correction_id': 'fix-1', 'type': 'retitle_identity'},
                {'correction_id': 'fix-2', 'type': 'split_misassigned_edition'},
            ],
        }
        before = {'fetishes': [], 'compound_works': {}, 'work_catalog': catalog}

        def local_state(**values):
            if not values:
                return before
            return {
                'fetishes': values['fetishes'],
                'compound_works': values['compound_works'],
                'work_catalog': values['work_catalog'],
            }

        with (
            patch.object(engine_module, '_use_db', return_value=False),
            patch.object(self.engine, '_local_work_catalog_state', side_effect=local_state),
            patch.object(self.engine, '_commit_local_work_catalog_state', return_value=None) as commit_catalog,
            patch.object(engine_module.work_catalog, 'apply_catalog_corrections', return_value=corrected) as apply,
        ):
            result = self.engine.mutate_work_catalog(
                'corrections_apply_manifest',
                {'corrections_manifest': manifest},
                expected_digest=engine_module.work_catalog.catalog_digest(catalog),
            )

        self.assertEqual(
            result['result'],
            {
                'correction_count': 2,
                'split_count': 1,
                'retitle_count': 1,
                'quarantine_count': 0,
                'link_rebind_count': 0,
                'inline_applied_link_count': 0,
                'inline_fetish_owner_count': 0,
                'inline_compound_owner_count': 0,
                'inline_missing_count': 0,
            },
        )
        apply.assert_called_once_with(catalog, manifest)
        commit_catalog.assert_called_once()
        self.assertEqual(commit_catalog.call_args.args[1]['work_catalog'], corrected)
