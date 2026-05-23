import ast
import importlib
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

HELPER_MODULES = [
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


class TestEngineHelperDependencies(unittest.TestCase):
    def test_helpers_do_not_import_public_engine_facade(self):
        offenders = []
        for filename in HELPER_MODULES:
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

    def test_helper_list_matches_top_level_engine_helpers(self):
        actual = sorted(
            name for name in os.listdir(ROOT)
            if name.startswith('engine_') and name.endswith('.py')
        )
        self.assertEqual(actual, sorted(HELPER_MODULES))

    def test_helpers_import_without_engine_instance_setup(self):
        for filename in HELPER_MODULES:
            module_name = filename[:-3]
            with self.subTest(module=module_name):
                module = importlib.import_module(module_name)
                self.assertEqual(module.__name__, module_name)
