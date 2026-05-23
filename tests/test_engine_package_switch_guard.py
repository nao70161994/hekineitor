import importlib.util
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import engine

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


class TestEnginePackageSwitchGuard(unittest.TestCase):
    def test_engine_import_still_resolves_to_module_file_before_atomic_switch(self):
        self.assertTrue(engine.__file__.endswith('engine.py'))
        self.assertEqual(os.path.abspath(engine.__file__), os.path.join(ROOT, 'engine.py'))

    def test_importlib_spec_still_points_at_engine_py_before_atomic_switch(self):
        spec = importlib.util.find_spec('engine')
        self.assertIsNotNone(spec)
        self.assertEqual(os.path.abspath(spec.origin), os.path.join(ROOT, 'engine.py'))
        self.assertIsNone(spec.submodule_search_locations)

    def test_engine_package_directory_is_not_created_during_prep_refactors(self):
        self.assertFalse(os.path.isdir(os.path.join(ROOT, 'engine')))

    def test_engine_helper_modules_remain_top_level_during_prep_refactors(self):
        helper_files = [
            'engine_admin_reports.py',
            'engine_compound_works.py',
            'engine_constants.py',
            'engine_correlation.py',
            'engine_data.py',
            'engine_db.py',
            'engine_inference.py',
            'engine_learning.py',
            'engine_mutations.py',
            'engine_persistence.py',
            'engine_question_selection.py',
            'engine_reporting.py',
            'engine_runtime.py',
            'engine_stats.py',
        ]
        missing = [name for name in helper_files if not os.path.exists(os.path.join(ROOT, name))]
        self.assertEqual(missing, [])
