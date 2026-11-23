#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""QuizComplete 简繁判断题判定矩阵测试。"""

import importlib.util
import json
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
BUILD_PATH = ROOT / 'build.py'


def make_markdown(traditional):
    title = '# 判斷題測試' if traditional else '# 判断题测试'
    stem = '下列敘述是否正確（ ）' if traditional else '下列叙述是否正确（ ）'
    explanation = '依定義判斷。' if traditional else '依据定义判断。'
    tag = '測試·判斷' if traditional else '测试·判断'
    answers = ['正確', '錯誤', '正確', '錯誤'] if traditional else [
        '正确', '错误', '正确', '错误',
    ]
    blocks = [title, '']
    for idx, answer in enumerate(answers, 1):
        blocks.extend([
            '### 第 %d 题（判断题）' % idx,
            '',
            '%s%d' % (stem, idx),
            '',
            '**答案**：%s' % answer,
            '',
            '**解析**：%s' % explanation,
            '',
            '**知识回溯**：%s' % tag,
            '',
            '---',
            '',
        ])
    return '\n'.join(blocks)


def build_and_read(traditional):
    with tempfile.TemporaryDirectory(prefix='quiz-complete-judge-') as tmp:
        root = pathlib.Path(tmp)
        input_dir = root / 'input'
        output_dir = root / 'output'
        input_dir.mkdir()
        (input_dir / 'questions.md').write_text(
            make_markdown(traditional),
            encoding='utf-8',
        )

        run = subprocess.run(
            [
                sys.executable,
                str(BUILD_PATH),
                '--input', str(input_dir),
                '--title', '判断题契约',
                '--output', str(output_dir),
            ],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=60,
        )
        if run.returncode != 0:
            raise AssertionError(run.stdout + run.stderr)
        return (output_dir / 'index.html').read_text(encoding='utf-8')


def extract_questions(html):
    match = re.search(
        r'const allQuestions = (\[.*?\]);',
        html,
        re.DOTALL,
    )
    if not match:
        raise AssertionError('未找到 allQuestions')
    return json.loads(match.group(1))


def extract_label(html, name):
    match = re.search(
        r"const %s = '([^']+)';" % name,
        html,
    )
    if not match:
        raise AssertionError('未找到 %s' % name)
    return match.group(1)


class JudgmentContractTests(unittest.TestCase):
    def test_simplified_and_traditional_judgment_matrix(self):
        cases = (
            (False, '正确', '错误'),
            (True, '正確', '錯誤'),
        )
        for traditional, true_label, false_label in cases:
            with self.subTest(traditional=traditional):
                html = build_and_read(traditional)
                questions = extract_questions(html)
                self.assertEqual(len(questions), 4)
                self.assertTrue(all(q['type'] == 'judge' for q in questions))

                actual_true = extract_label(html, 'JUDGE_TRUE_LABEL')
                actual_false = extract_label(html, 'JUDGE_FALSE_LABEL')
                self.assertEqual((actual_true, actual_false), (
                    true_label,
                    false_label,
                ))

                pair_match = re.search(
                    r"\[\[JUDGE_TRUE_LABEL, '([^']+)'\], "
                    r"\[JUDGE_FALSE_LABEL, '([^']+)'\]\]",
                    html,
                )
                self.assertIsNotNone(pair_match)
                true_value, false_value = pair_match.groups()
                self.assertEqual((true_value, false_value), ('正确', '错误'))

                for question in questions:
                    expected_value = question['answer']
                    for label, selected_value in (
                        (true_label, true_value),
                        (false_label, false_value),
                    ):
                        expected_match = selected_value == expected_value
                        semantic_match = label == (
                            true_label
                            if expected_value == '正确'
                            else false_label
                        )
                        self.assertEqual(expected_match, semantic_match)

    def test_judge_answer_input_variants_are_normalized(self):
        module_path = ROOT / 'build.py'
        spec = importlib.util.spec_from_file_location(
            'quiz_complete_judge',
            module_path,
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        for raw in ('正确', '正確', '对', '對', '是', '✔', '√', '✓', 'T', 'true'):
            self.assertEqual(module.normalize_judge_answer(raw), '正确')
        for raw in ('错误', '錯誤', '错', '錯', '否', '✘', '×', 'F', 'false'):
            self.assertEqual(module.normalize_judge_answer(raw), '错误')
        for raw in ('不正确', '不對'):
            self.assertEqual(module.normalize_judge_answer(raw), '错误')
        self.assertIsNone(module.normalize_judge_answer('无法判断'))


if __name__ == '__main__':
    unittest.main()
