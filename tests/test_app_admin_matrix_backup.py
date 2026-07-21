# ruff: noqa: F403, F405

from tests._app_test_support import *


class TestAdminMatrixBackup(APITestCase):
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
        self.assertEqual(data['metadata']['backup_format_version'], 3)
        self.assertEqual(data['work_catalog']['schema_version'], 1)
        self.assertEqual(data['metadata']['matrix_row_count'], len(data['matrix_rows']))
        self.assertGreater(len(data['matrix_rows']), 0)

    def test_v3_backup_requires_a_valid_work_catalog(self):
        headers = self._admin_headers()
        exported = self.client.get('/api/admin/export_matrix', headers=headers).get_json()
        missing = json.loads(json.dumps(exported))
        missing.pop('work_catalog')
        response = self.client.post('/api/admin/import_matrix/dry_run', json=missing, headers=headers)
        self.assertEqual(response.status_code, 400)
        self.assertIn('work_catalog', response.get_json()['message'])

        broken = json.loads(json.dumps(exported))
        broken['work_catalog']['fetish_work_links'][0]['work_id'] = 'wrk_missing'
        response = self.client.post('/api/admin/import_matrix/dry_run', json=broken, headers=headers)
        self.assertEqual(response.status_code, 400)
        self.assertIn('work_catalog', response.get_json()['message'])

    def test_import_v3_passes_catalog_to_transactional_restore(self):
        headers = self._admin_headers()
        from app import engine as app_engine

        exported = self.client.get('/api/admin/export_matrix', headers=headers).get_json()
        exported['confirm_text'] = 'IMPORT'
        snapshot = unittest.mock.Mock(return_value=os.path.join(DATA_DIR, 'matrix_import_backups', 'test.json'))
        ops = type(
            'Ops',
            (),
            {
                'snapshot_current_matrix': snapshot,
                'completeness_error': lambda self, report: None,
                'expected_rows': lambda self: len(exported['matrix_rows']),
                'list_backups': lambda self, limit=50: [],
            },
        )()
        with (
            patch('app._matrix_operations', return_value=ops),
            patch.object(
                app_engine,
                'restore_matrix_snapshot',
                return_value=(len(exported['matrix_rows']), []),
            ) as restore,
        ):
            response = self.client.post('/api/admin/import_matrix', json=exported, headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(restore.call_args.kwargs['work_catalog'], exported['work_catalog'])
        snapshot.assert_called_once()

    def test_import_matrix_rejects_invalid_counts(self):
        headers = self._admin_headers()
        res = self.client.post(
            '/api/admin/import_matrix',
            json={'matrix_rows': [{'fetish_id': 0, 'question_id': 0, 'yes': 2, 'total': 1}]},
            headers=headers,
        )
        self.assertEqual(res.status_code, 400)

    def test_import_matrix_creates_pre_import_backup(self):
        headers = self._admin_headers()
        rows = self._full_matrix_rows()
        snapshot = unittest.mock.Mock(return_value=os.path.join(DATA_DIR, 'matrix_import_backups', 'test.json'))
        ops = type(
            'Ops',
            (),
            {
                'snapshot_current_matrix': snapshot,
                'completeness_error': lambda self, report: None,
                'expected_rows': lambda self: len(rows),
                'list_backups': lambda self, limit=50: [],
            },
        )()
        with patch('app._matrix_operations', return_value=ops):
            res = self.client.post(
                '/api/admin/import_matrix', json={'matrix_rows': rows, 'confirm_text': 'IMPORT'}, headers=headers
            )
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
            rows.append(
                {
                    'fetish_id': missing_id,
                    'fetish_name': '復元待ち',
                    'question_id': qi,
                    'question_text': question['text'],
                    'yes': 1,
                    'total': 2,
                }
            )
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
        res = self.client.post(
            '/api/admin/import_matrix', json={'matrix_rows': self._full_matrix_rows()}, headers=headers
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()['required_confirm_text'], 'IMPORT')

    def test_import_matrix_rejects_partial_snapshot(self):
        from app import engine as app_engine

        headers = self._admin_headers()
        fid = app_engine.fetishes[0]['id']
        res = self.client.post(
            '/api/admin/import_matrix',
            json={
                'matrix_rows': [
                    {
                        'fetish_id': fid,
                        'question_id': 0,
                        'yes': app_engine.matrix['yes'][0][0],
                        'total': app_engine.matrix['total'][0][0],
                    }
                ],
                'confirm_text': 'IMPORT',
            },
            headers=headers,
        )
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
            ops = type(
                'Ops',
                (),
                {
                    'snapshot_current_matrix': snapshot,
                    'completeness_error': lambda self, report: None,
                    'expected_rows': lambda self: len(rows),
                    'list_backups': lambda self, limit=50: [],
                },
            )()
            with patch('app._matrix_operations', return_value=ops):
                res = self.client.post(
                    f'/api/admin/matrix_backups/{backup_name}/restore',
                    json={'confirm_text': 'RESTORE'},
                    headers=headers,
                )
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
            rows.append(
                {
                    'fetish_id': missing_id,
                    'fetish_name': 'バックアップ復元',
                    'question_id': qi,
                    'question_text': question['text'],
                    'yes': 3,
                    'total': 4,
                }
            )
        payload = {
            'fetishes': app_engine.fetishes
            + [
                {
                    'id': missing_id,
                    'name': 'バックアップ復元',
                    'desc': 'バックアップ復元',
                    'works': [],
                }
            ],
            'matrix_rows': rows,
        }
        try:
            with open(backup_path, 'w', encoding='utf-8') as f:
                json.dump(payload, f)
            res = self.client.post(
                f'/api/admin/matrix_backups/{backup_name}/restore', json={'confirm_text': 'RESTORE'}, headers=headers
            )
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
        payload = {
            'matrix_rows': [
                {
                    'fetish_id': fid,
                    'question_id': 0,
                    'yes': app_engine.matrix['yes'][0][0],
                    'total': app_engine.matrix['total'][0][0],
                }
            ]
        }
        try:
            with open(backup_path, 'w', encoding='utf-8') as f:
                json.dump(payload, f)
            res = self.client.post(
                f'/api/admin/matrix_backups/{backup_name}/restore', json={'confirm_text': 'RESTORE'}, headers=headers
            )
            self.assertEqual(res.status_code, 400)
            self.assertIn('expected_rows', res.get_json())
        finally:
            try:
                os.remove(backup_path)
            except OSError:
                pass

    def test_import_matrix_dry_run_validates_without_importing(self):
        headers = self._admin_headers()
        res = self.client.post(
            '/api/admin/import_matrix/dry_run',
            json={'matrix_rows': [{'fetish_id': 0, 'question_id': 0, 'yes': 1, 'total': 2}]},
            headers=headers,
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['status'], 'ok')
        self.assertEqual(data['valid_rows'], 1)
        self.assertEqual(data['skipped_rows'], 0)
        self.assertFalse(data['complete'])
        self.assertGreater(data['expected_rows'], 1)

    def test_import_matrix_dry_run_rejects_invalid_counts(self):
        headers = self._admin_headers()
        res = self.client.post(
            '/api/admin/import_matrix/dry_run',
            json={'matrix_rows': [{'fetish_id': 0, 'question_id': 0, 'yes': 2, 'total': 1}]},
            headers=headers,
        )
        self.assertEqual(res.status_code, 400)

    def test_import_matrix_dry_run_rejects_duplicate_pairs(self):
        from app import engine as app_engine

        headers = self._admin_headers()
        fid = app_engine.fetishes[0]['id']
        rows = [
            {'fetish_id': fid, 'question_id': 0, 'yes': 1, 'total': 2},
            {'fetish_id': fid, 'question_id': 0, 'yes': 1, 'total': 2},
        ]
        res = self.client.post('/api/admin/import_matrix/dry_run', json={'matrix_rows': rows}, headers=headers)
        self.assertEqual(res.status_code, 400)

    def test_import_matrix_rejects_duplicate_pairs(self):
        from app import engine as app_engine

        headers = self._admin_headers()
        fid = app_engine.fetishes[0]['id']
        rows = [
            {'fetish_id': fid, 'question_id': 0, 'yes': 1, 'total': 2},
            {'fetish_id': fid, 'question_id': 0, 'yes': 1, 'total': 2},
        ]
        res = self.client.post(
            '/api/admin/import_matrix', json={'matrix_rows': rows, 'confirm_text': 'IMPORT'}, headers=headers
        )
        self.assertEqual(res.status_code, 400)
