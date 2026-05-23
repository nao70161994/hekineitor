import importlib.util
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import engine

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


class TestEnginePackageSwitchGuard(unittest.TestCase):
    def test_engine_import_resolves_to_package_after_atomic_switch(self):
        self.assertTrue(engine.__file__.endswith(os.path.join('engine', '__init__.py')))
        self.assertEqual(os.path.abspath(engine.__file__), os.path.join(ROOT, 'engine', '__init__.py'))

    def test_importlib_spec_points_at_engine_package_after_atomic_switch(self):
        spec = importlib.util.find_spec('engine')
        self.assertIsNotNone(spec)
        self.assertEqual(os.path.abspath(spec.origin), os.path.join(ROOT, 'engine', '__init__.py'))
        self.assertEqual([os.path.abspath(path) for path in spec.submodule_search_locations], [os.path.join(ROOT, 'engine')])

    def test_legacy_engine_py_module_is_removed_after_atomic_switch(self):
        self.assertFalse(os.path.exists(os.path.join(ROOT, 'engine.py')))
        self.assertTrue(os.path.isdir(os.path.join(ROOT, 'engine')))

    def test_legacy_engine_helper_shims_remain_for_import_compatibility(self):
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
        package_helpers = [
            'admin_reports.py',
            'compound_works.py',
            'constants.py',
            'correlation.py',
            'data.py',
            'persistence.py',
            'reporting.py',
            'runtime.py',
            'stats.py',
        ]
        missing_package = [name for name in package_helpers if not os.path.exists(os.path.join(ROOT, 'engine', name))]
        self.assertEqual(missing_package, [])
