import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
DOCS = os.path.join(ROOT, 'docs')


class TestEnginePackageDocs(unittest.TestCase):
    def read_doc(self, name):
        with open(os.path.join(DOCS, name), encoding='utf-8') as file_obj:
            return file_obj.read()

    def test_package_prep_docs_exist(self):
        expected = [
            'ENGINE_FACADE_CONTRACT.md',
            'ENGINE_PACKAGE_PLAN.md',
            'ENGINE_PACKAGE_REHEARSAL_CHECKLIST.md',
            'ENGINE_PACKAGE_PR_REVIEW.md',
            'ENGINE_PACKAGE_PR_TEMPLATE.md',
            'ENGINE_PACKAGE_SWITCH_PLAN.md',
            'ENGINE_PRIVATE_HELPER_MAP.md',
        ]
        missing = [name for name in expected if not os.path.exists(os.path.join(DOCS, name))]
        self.assertEqual(missing, [])

    def test_switch_docs_keep_atomic_and_no_prep_package_warnings(self):
        switch_plan = self.read_doc('ENGINE_PACKAGE_SWITCH_PLAN.md')
        rehearsal = self.read_doc('ENGINE_PACKAGE_REHEARSAL_CHECKLIST.md')
        review = self.read_doc('ENGINE_PACKAGE_PR_REVIEW.md')

        for body in (switch_plan, rehearsal, review):
            self.assertIn('engine.py', body)
            self.assertIn('engine/', body)
        self.assertIn('Do not execute this plan in preparatory refactor PRs', switch_plan)
        self.assertIn('prep PRs must not create `engine/`', rehearsal)
        self.assertIn('one import-target switch commit', review)

    def test_facade_contract_docs_keep_behavior_guardrails(self):
        contract = self.read_doc('ENGINE_FACADE_CONTRACT.md')
        self.assertIn('posteriors', contract)
        self.assertIn('best_question', contract)
        self.assertIn('learning deltas', contract)
        self.assertIn('DB schema', contract)
        self.assertIn('session keys', contract)

    def test_package_pr_template_locks_switch_evidence(self):
        template = self.read_doc('ENGINE_PACKAGE_PR_TEMPLATE.md')
        self.assertIn('atomic `engine.py` to `engine/` package switch PR', template)
        self.assertIn('No inference probability', template)
        self.assertIn('No learning delta', template)
        self.assertIn('No DB schema', template)
        self.assertIn('tests/test_engine_public_api_contract.py', template)
        self.assertIn('tests/test_engine_inference_regression.py', template)
        self.assertIn('git diff --check', template)
        self.assertIn('pytest', template)
        self.assertIn('Rollback Plan', template)
