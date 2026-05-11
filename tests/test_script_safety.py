import importlib.util
import json
import os
import runpy
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RestoreMatrixScriptTests(unittest.TestCase):
    def test_current_backup_shape_builds_priors(self):
        restore_matrix = load_module('restore_matrix_under_test', ROOT / 'restore_matrix.py')
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / 'data'
            data_dir.mkdir()
            (data_dir / 'questions.json').write_text(
                json.dumps([{'text': 'q0'}, {'text': 'q1'}]),
                encoding='utf-8',
            )
            restore_matrix.DATA_DIR = str(data_dir)

            priors = restore_matrix.build_priors({
                'exported_at': datetime.now(timezone.utc).isoformat(),
                'fetishes': [{'id': 10}, {'id': 20}],
                'matrix_rows': [
                    {'fetish_id': 10, 'question_id': 0, 'yes': 2, 'total': 4},
                    {'fetish_id': 20, 'question_id': 1, 'yes': 3, 'total': 4},
                ],
            })

        self.assertEqual(priors, {
            '10': {'0': 0.5, '1': 0.5},
            '20': {'0': 0.5, '1': 0.75},
        })

    def test_backup_freshness_is_validated_when_export_metadata_exists(self):
        restore_matrix = load_module('restore_matrix_under_test_freshness', ROOT / 'restore_matrix.py')
        restore_matrix.MAX_BACKUP_AGE_HOURS = 1
        old_export = datetime.now(timezone.utc) - timedelta(hours=2)

        with self.assertRaisesRegex(ValueError, '古すぎます'):
            restore_matrix.validate_backup_freshness({
                'metadata': {'exported_at': old_export.isoformat()},
            })

        with self.assertRaisesRegex(ValueError, 'exported_at'):
            restore_matrix.validate_backup_freshness({'matrix_rows': []})

    def test_unsupported_backup_shape_fails_clearly(self):
        restore_matrix = load_module('restore_matrix_under_test_bad', ROOT / 'restore_matrix.py')
        with self.assertRaisesRegex(ValueError, 'unsupported backup shape'):
            restore_matrix.build_priors({
                'exported_at': datetime.now(timezone.utc).isoformat(),
                'rows': [],
            })


class FetchKindleAsinsScriptTests(unittest.TestCase):
    def test_save_progress_uses_atomic_writer(self):
        fetch_kindle = load_module('fetch_kindle_under_test', ROOT / 'fetch_kindle_asins.py')
        calls = []

        def fake_atomic_write_json(path, data, **kwargs):
            calls.append((path, data, kwargs))

        fetch_kindle.atomic_write_json = fake_atomic_write_json
        fetch_kindle.save_progress({'title': 'B000000000'})

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], fetch_kindle.PROGRESS)
        self.assertEqual(calls[0][1], {'title': 'B000000000'})
        self.assertTrue(calls[0][2]['ensure_ascii'] is False)

    def test_known_asin_lookup_handles_search_and_title_variants(self):
        fetch_kindle = load_module('fetch_kindle_lookup_under_test', ROOT / 'fetch_kindle_asins.py')

        fetishes = [{
            'works': [{
                'title': 'orange',
                'url': 'https://www.amazon.co.jp/dp/B00JD349L6?tag=hekinator-22',
            }]
        }]
        exact, canonical = fetch_kindle.known_asin_maps({}, fetishes)

        self.assertTrue(fetch_kindle.is_search_url('https://www.amazon.co.jp/s?k=orange&tag=hekinator-22'))
        self.assertEqual(
            fetch_kindle.lookup_known_asin('orange（漫画）', exact, canonical),
            'B00JD349L6',
        )

    def test_known_asin_lookup_handles_descriptive_prefix(self):
        fetch_kindle = load_module('fetch_kindle_suffix_under_test', ROOT / 'fetch_kindle_asins.py')

        exact, canonical = fetch_kindle.known_asin_maps({
            '君が望む永遠（NTR√）': 'B0FNDBR1YM',
            '君が望む永遠（遥√）': 'B0FNDBR1YM',
        }, [])

        self.assertEqual(
            fetch_kindle.lookup_known_asin('NTRエロゲの金字塔・君が望む永遠', exact, canonical),
            'B0FNDBR1YM',
        )


class WorksLinksScriptTests(unittest.TestCase):
    def test_report_escapes_data_and_uses_noopener(self):
        with tempfile.TemporaryDirectory() as tmp:
            cwd = os.getcwd()
            try:
                os.chdir(tmp)
                data_dir = Path('data')
                data_dir.mkdir()
                (data_dir / 'fetishes.json').write_text(json.dumps([{
                    'name': '<img src=x onerror=alert(1)>',
                    'works': [{
                        'title': 'A&B <script>alert(1)</script>',
                        'url': 'https://example.test/dp/B000000000?q="x"&a=<b>',
                    }],
                }]), encoding='utf-8')

                runpy.run_path(str(ROOT / 'check_works_links.py'), run_name='__main__')
                report = Path('works_review.html').read_text(encoding='utf-8')
            finally:
                os.chdir(cwd)

        self.assertIn('&lt;img src=x onerror=alert(1)&gt;', report)
        self.assertIn('A&amp;B &lt;script&gt;alert(1)&lt;/script&gt;', report)
        self.assertIn('href="https://example.test/dp/B000000000?q=&quot;x&quot;&amp;a=&lt;b&gt;"', report)
        self.assertIn('rel="noopener"', report)
        self.assertNotIn('<script>alert(1)</script>', report)


class RestoreMatrixWorkflowTests(unittest.TestCase):
    def test_workflow_validates_restore_result_counts(self):
        workflow = (ROOT / '.github' / 'workflows' / 'restore_matrix.yml').read_text(encoding='utf-8')

        self.assertIn("with open('/tmp/restore_result.json'", workflow)
        self.assertIn("expected = len(payload.get('matrix_rows', []))", workflow)
        self.assertIn('imported_rows mismatch', workflow)
        self.assertIn('Restore skipped rows', workflow)

    def test_workflow_requires_backup_freshness_metadata(self):
        workflow = (ROOT / '.github' / 'workflows' / 'restore_matrix.yml').read_text(encoding='utf-8')

        self.assertIn('exported_at', workflow)
        self.assertIn('MATRIX_BACKUP_MAX_AGE_HOURS', workflow)
        self.assertIn('must include exported_at metadata', workflow)
        self.assertIn('row count mismatch', workflow)
        self.assertIn('matrix_backup.json is stale', workflow)


if __name__ == '__main__':
    unittest.main()
