#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""QuizComplete 构建失败退出码与写入保护测试。"""

import pathlib
import subprocess
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
BUILD_PATH = ROOT / 'build.py'
VALID_QUESTION = """\
# 测试章节

### 第 1 题（判断题）

这是一道有效题目（ ）

**答案**：正确

**解析**：有效解析。

**知识回溯**：测试·有效
"""
INVALID_QUESTION = """\
# 测试章节

### 第 2 题（单选题）

这是一道坏题（ ）

A. 甲
B. 乙
C. 丙
D. 丁

**答案**：

**解析**：坏题。

**知识回溯**：测试·错误
"""


class BuildFailureContractTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(
            prefix='quiz-complete-build-failure-'
        )
        self.root = pathlib.Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def run_build(self, input_dir, output_dir):
        return subprocess.run(
            [
                sys.executable,
                str(BUILD_PATH),
                '--input', str(input_dir),
                '--title', '构建失败契约测试',
                '--output', str(output_dir),
            ],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=60,
        )

    def test_missing_input_directory_fails(self):
        output_dir = self.root / 'output-missing-input'
        run = self.run_build(self.root / 'does-not-exist', output_dir)

        self.assertEqual(run.returncode, 2, run.stdout + run.stderr)
        self.assertIn('题库目录不存在或不是文件夹', run.stdout)
        self.assertFalse((output_dir / 'index.html').exists())

    def test_empty_directory_fails(self):
        input_dir = self.root / 'empty'
        input_dir.mkdir()
        output_dir = self.root / 'output-empty'
        run = self.run_build(input_dir, output_dir)

        self.assertEqual(run.returncode, 2, run.stdout + run.stderr)
        self.assertIn('没有 Markdown 文件', run.stdout)
        self.assertFalse((output_dir / 'index.html').exists())

    def test_markdown_without_question_blocks_fails(self):
        input_dir = self.root / 'no-blocks'
        input_dir.mkdir()
        (input_dir / 'README.md').write_text(
            '# 只有说明，没有题目\n',
            encoding='utf-8',
        )
        output_dir = self.root / 'output-no-blocks'
        run = self.run_build(input_dir, output_dir)

        self.assertEqual(run.returncode, 2, run.stdout + run.stderr)
        self.assertIn('没有可识别的题目块', run.stdout)
        self.assertFalse((output_dir / 'index.html').exists())

    def test_invalid_only_question_fails_without_output(self):
        input_dir = self.root / 'invalid-only'
        input_dir.mkdir()
        (input_dir / 'invalid.md').write_text(
            INVALID_QUESTION,
            encoding='utf-8',
        )
        output_dir = self.root / 'output-invalid-only'
        run = self.run_build(input_dir, output_dir)

        self.assertEqual(run.returncode, 2, run.stdout + run.stderr)
        self.assertIn('存在未解析题目', run.stdout)
        self.assertFalse((output_dir / 'index.html').exists())

    def test_partial_parse_failure_preserves_existing_output(self):
        input_dir = self.root / 'mixed'
        input_dir.mkdir()
        (input_dir / 'mixed.md').write_text(
            VALID_QUESTION + '\n---\n\n' + INVALID_QUESTION,
            encoding='utf-8',
        )
        output_dir = self.root / 'output-mixed'
        output_dir.mkdir()
        index_path = output_dir / 'index.html'
        index_path.write_text('OLD VALID INDEX', encoding='utf-8')

        run = self.run_build(input_dir, output_dir)

        self.assertEqual(run.returncode, 2, run.stdout + run.stderr)
        self.assertIn('存在未解析题目', run.stdout)
        self.assertEqual(index_path.read_text(encoding='utf-8'), 'OLD VALID INDEX')

    def test_valid_question_builds_successfully(self):
        input_dir = self.root / 'valid'
        input_dir.mkdir()
        (input_dir / 'valid.md').write_text(
            VALID_QUESTION,
            encoding='utf-8',
        )
        output_dir = self.root / 'output-valid'
        run = self.run_build(input_dir, output_dir)

        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertTrue((output_dir / 'index.html').is_file())
        self.assertIn('全部解析成功', run.stdout)


if __name__ == '__main__':
    unittest.main()
