#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""QuizComplete 评估集与触发边界契约测试。"""

import json
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
EVALS_DIR = ROOT / 'evals'


class EvaluationContractTests(unittest.TestCase):
    def test_runtime_eval_schema_and_files(self):
        data = json.loads(
            (EVALS_DIR / 'evals.json').read_text(encoding='utf-8')
        )
        self.assertEqual(data['skill_name'], 'quiz-complete')
        self.assertGreaterEqual(len(data['evals']), 3)

        ids = set()
        names = set()
        for item in data['evals']:
            self.assertTrue(item['id'])
            self.assertNotIn(item['id'], ids)
            ids.add(item['id'])
            self.assertTrue(item['name'])
            self.assertNotIn(item['name'], names)
            names.add(item['name'])
            self.assertTrue(item['prompt'].strip())
            self.assertTrue(item['expected_output'].strip())
            self.assertIsInstance(item['files'], list)
            self.assertTrue(item['expectations'])
            self.assertTrue(all(value.strip() for value in item['expectations']))
            for relative_path in item['files']:
                self.assertTrue(
                    (EVALS_DIR / relative_path).is_file(),
                    relative_path,
                )

    def test_trigger_dataset_has_eight_positive_and_eight_negative_cases(self):
        data = json.loads(
            (EVALS_DIR / 'trigger-cases.draft.json').read_text(encoding='utf-8')
        )
        self.assertEqual(data['skill_name'], 'quiz-complete')
        cases = data['cases']
        self.assertEqual(len(cases), 16)
        self.assertEqual(sum(bool(case['should_trigger']) for case in cases), 8)
        self.assertEqual(sum(not case['should_trigger'] for case in cases), 8)
        self.assertEqual(len({case['id'] for case in cases}), 16)
        self.assertEqual(len({case['query'] for case in cases}), 16)

    def test_description_declares_trigger_boundaries(self):
        skill = (ROOT / 'SKILL.md').read_text(encoding='utf-8')
        description = next(
            line.split(':', 1)[1].strip()
            for line in skill.splitlines()
            if line.startswith('description:')
        )

        self.assertTrue(description.startswith('当用户明确要求'))
        self.assertIn('时使用', description)
        self.assertIn('不要用于', description)
        self.assertIn('单道题', description)
        self.assertIn('通用问卷', description)
        self.assertIn('教学方案', description)
        self.assertLessEqual(len(description), 1024)


if __name__ == '__main__':
    unittest.main()
