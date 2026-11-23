#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""QuizComplete 项目级审计配置测试。"""

import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
BUILD_PATH = ROOT / 'build.py'
SPEC = importlib.util.spec_from_file_location('quiz_complete_audit', BUILD_PATH)
BUILD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILD)


def write_profile(path, data):
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )


def question_markdown():
    blocks = ['# 审计测试', '']
    options = (
        ('A. 甲', 'B. 乙', 'C. 丙', 'D. 一个非常长的干扰选项内容'),
        ('A. 子项', 'B. 丑项', 'C. 寅项', 'D. 卯项'),
        ('A. 东项', 'B. 西项', 'C. 南项', 'D. 北项'),
        ('A. 春项', 'B. 夏项', 'C. 秋项', 'D. 冬项'),
    )
    for idx, (answer, opts) in enumerate(zip('ABCD', options), 1):
        blocks.extend([
            '### 第 %d 题（单选题）' % idx,
            '',
            '审计测试题干%d（ ）' % idx,
            '',
            *opts,
            '',
            '**答案**：%s' % answer,
            '',
            '**解析**：审计测试解析%d。' % idx,
            '',
            '**知识回溯**：测试·审计%d' % idx,
            '',
            '---',
            '',
        ])
    return '\n'.join(blocks)


class AuditProfileTests(unittest.TestCase):
    def test_valid_profile_merges_only_given_fields(self):
        with tempfile.TemporaryDirectory(prefix='quiz-complete-profile-') as tmp:
            path = pathlib.Path(tmp) / 'audit.json'
            write_profile(path, {
                'multi_full_max_pct': 20,
                'opt_len_gap_max': 10,
                'multi_cardinality_target_pct': {
                    '1': 25,
                    '2': 25,
                    '3': 25,
                    '4': 25,
                },
            })

            thresholds, targets = BUILD.load_audit_profile(path)

        self.assertEqual(thresholds['multi_full_max_pct'], 20)
        self.assertEqual(thresholds['opt_len_gap_max'], 10)
        self.assertEqual(
            thresholds['single_pos_max_pct'],
            BUILD.AUDIT_THRESHOLDS['single_pos_max_pct'],
        )
        self.assertEqual(targets, {1: 25, 2: 25, 3: 25, 4: 25})

    def test_invalid_profiles_are_rejected(self):
        cases = (
            {'unknown_field': 1},
            {'multi_full_max_pct': 101},
            {'multi_pattern_min_sample': 0},
            {'option_similarity_threshold': 1.1},
            {
                'multi_cardinality_target_pct': {
                    '1': 25,
                    '2': 25,
                    '3': 25,
                }
            },
            {
                'multi_cardinality_target_pct': {
                    '1': 25,
                    '2': 25,
                    '3': 25,
                    '4': 24,
                }
            },
        )
        with tempfile.TemporaryDirectory(prefix='quiz-complete-profile-') as tmp:
            path = pathlib.Path(tmp) / 'audit.json'
            for data in cases:
                with self.subTest(data=data):
                    write_profile(path, data)
                    with self.assertRaises(ValueError):
                        BUILD.load_audit_profile(path)

    def test_invalid_profile_fails_before_overwriting_output(self):
        with tempfile.TemporaryDirectory(prefix='quiz-complete-profile-') as tmp:
            root = pathlib.Path(tmp)
            input_dir = root / 'input'
            output_dir = root / 'output'
            input_dir.mkdir()
            output_dir.mkdir()
            (input_dir / 'questions.md').write_text(
                question_markdown(),
                encoding='utf-8',
            )
            index_path = output_dir / 'index.html'
            index_path.write_text('OLD INDEX', encoding='utf-8')
            profile_path = root / 'invalid.json'
            write_profile(profile_path, {'unknown_field': 1})

            run = subprocess.run(
                [
                    sys.executable,
                    str(BUILD_PATH),
                    '--input', str(input_dir),
                    '--title', '审计配置',
                    '--output', str(output_dir),
                    '--audit-profile', str(profile_path),
                ],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=60,
            )

            self.assertEqual(run.returncode, 2, run.stdout + run.stderr)
            self.assertIn('审计配置无效', run.stdout)
            self.assertEqual(index_path.read_text(encoding='utf-8'), 'OLD INDEX')

    def test_custom_profile_changes_strict_audit_outcome(self):
        with tempfile.TemporaryDirectory(prefix='quiz-complete-profile-') as tmp:
            root = pathlib.Path(tmp)
            input_dir = root / 'input'
            input_dir.mkdir()
            (input_dir / 'questions.md').write_text(
                question_markdown(),
                encoding='utf-8',
            )
            profile_path = root / 'relaxed.json'
            write_profile(profile_path, {'opt_len_gap_max': 20})
            common = [
                sys.executable,
                str(BUILD_PATH),
                '--input', str(input_dir),
                '--title', '审计配置',
                '--strict-audit',
            ]

            default_output = root / 'default-output'
            default_run = subprocess.run(
                common + ['--output', str(default_output)],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=60,
            )
            custom_output = root / 'custom-output'
            custom_run = subprocess.run(
                common + [
                    '--output', str(custom_output),
                    '--audit-profile', str(profile_path),
                ],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=60,
            )

            self.assertEqual(
                default_run.returncode,
                2,
                default_run.stdout + default_run.stderr,
            )
            self.assertIn('选项长度极差', default_run.stdout)
            self.assertFalse((default_output / 'index.html').exists())
            self.assertEqual(
                custom_run.returncode,
                0,
                custom_run.stdout + custom_run.stderr,
            )
            self.assertTrue((custom_output / 'index.html').is_file())

    def test_zero_cardinality_target_does_not_require_that_group(self):
        questions = []
        cardinalities = [1] * 7 + [2] * 7 + [3] * 6
        for idx, cardinality in enumerate(cardinalities):
            answer = ' · '.join('ABCD'[:cardinality])
            questions.append({
                'id': 'q_%02d' % idx,
                'type': 'multiple',
                'question': '目标为零测试 %d' % idx,
                'options': [
                    '%s. 选项%d%s' % (letter, idx, letter)
                    for letter in 'ABCD'
                ],
                'answer': answer,
                'explanation': '测试解析 %d' % idx,
                'tag': '测试',
                'file': 'profile',
                'section': '测试',
            })

        _, warnings = BUILD.quality_audit(
            questions,
            cardinality_targets={1: 35, 2: 35, 3: 30, 4: 0},
        )

        self.assertFalse(
            any('正确项数量结构偏离' in warning for warning in warnings)
        )


if __name__ == '__main__':
    unittest.main()
