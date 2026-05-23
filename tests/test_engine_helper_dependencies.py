import ast
import importlib
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

TOP_LEVEL_HELPER_SHIMS = [
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

PACKAGE_HELPER_MODULES = [
    'engine.admin_reports',
    'engine.compound_works',
    'engine.constants',
    'engine.correlation',
    'engine.data',
    'engine.persistence',
    'engine.reporting',
    'engine.runtime',
    'engine.stats',
]

PACKAGE_HELPER_FILES = [module.replace('.', '/') + '.py' for module in PACKAGE_HELPER_MODULES]


class TestEngineHelperDependencies(unittest.TestCase):
    def test_helpers_do_not_import_public_engine_facade(self):
        offenders = []
        for filename in PACKAGE_HELPER_FILES:
            path = os.path.join(ROOT, filename)
            with open(path, encoding='utf-8') as file_obj:
                tree = ast.parse(file_obj.read(), filename=filename)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name == 'engine':
                            offenders.append((filename, node.lineno, 'import engine'))
                elif isinstance(node, ast.ImportFrom) and node.module == 'engine':
                    offenders.append((filename, node.lineno, 'from engine import ...'))
        self.assertEqual(offenders, [])

    def test_top_level_engine_helper_shims_remain_for_import_compatibility(self):
        actual = sorted(
            name for name in os.listdir(ROOT)
            if name.startswith('engine_') and name.endswith('.py')
        )
        self.assertEqual(actual, sorted(TOP_LEVEL_HELPER_SHIMS))

    def test_package_helpers_import_without_engine_instance_setup(self):
        for module_name in PACKAGE_HELPER_MODULES:
            with self.subTest(module=module_name):
                module = importlib.import_module(module_name)
                self.assertEqual(module.__name__, module_name)

    def test_top_level_moved_shims_alias_package_modules(self):
        aliases = {
            'engine_admin_reports': 'engine.admin_reports',
            'engine_compound_works': 'engine.compound_works',
            'engine_constants': 'engine.constants',
            'engine_correlation': 'engine.correlation',
            'engine_data': 'engine.data',
            'engine_persistence': 'engine.persistence',
            'engine_reporting': 'engine.reporting',
            'engine_runtime': 'engine.runtime',
            'engine_stats': 'engine.stats',
        }
        for shim_name, package_name in aliases.items():
            with self.subTest(shim=shim_name):
                self.assertIs(importlib.import_module(shim_name), importlib.import_module(package_name))
