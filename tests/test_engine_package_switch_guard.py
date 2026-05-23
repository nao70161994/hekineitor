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

    def test_engine_package_directory_is_not_created_during_prep_refactors(self):
        self.assertFalse(os.path.isdir(os.path.join(ROOT, 'engine')))
