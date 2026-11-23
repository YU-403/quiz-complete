#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""QuizComplete KaTeX 失败与降级契约测试。"""

import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
BUILD_PATH = ROOT / 'build.py'
QUESTION_MARKDOWN = """\
# 公式测试

### 第 1 题（判断题）

公式 $x^2$ 成立（ ）

**答案**：正确

**解析**：公式为 $x^2$。

**知识回溯**：测试·公式
"""


def run_build(build_path, input_dir, output_dir, *extra_args):
    return subprocess.run(
        [
            sys.executable,
            str(build_path),
            '--input', str(input_dir),
            '--title', '公式测试',
            '--output', str(output_dir),
            *extra_args,
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        timeout=60,
    )


class KatexContractTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix='quiz-complete-katex-')
        self.root = pathlib.Path(self.temp_dir.name)
        self.input_dir = self.root / 'input'
        self.input_dir.mkdir()
        (self.input_dir / 'questions.md').write_text(
            QUESTION_MARKDOWN,
            encoding='utf-8',
        )
        self.missing_build = self.root / 'missing' / 'build.py'
        self.missing_build.parent.mkdir()
        shutil.copy2(BUILD_PATH, self.missing_build)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_katex_with_assets_enables_formula_rendering(self):
        output_dir = self.root / 'with-assets'
        run = run_build(BUILD_PATH, self.input_dir, output_dir, '--katex')

        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        html = (output_dir / 'index.html').read_text(encoding='utf-8')
        self.assertIn('var KATEX_ENABLED = true;', html)
        self.assertIn('已内联 KaTeX', run.stdout)

    def test_katex_without_assets_fails_before_overwriting_output(self):
        output_dir = self.root / 'missing-fail'
        output_dir.mkdir()
        index_path = output_dir / 'index.html'
        index_path.write_text('OLD INDEX', encoding='utf-8')

        run = run_build(self.missing_build, self.input_dir, output_dir, '--katex')

        self.assertEqual(run.returncode, 2, run.stdout + run.stderr)
        self.assertIn('无法满足 --katex 请求', run.stdout)
        self.assertEqual(index_path.read_text(encoding='utf-8'), 'OLD INDEX')

    def test_explicit_fallback_allows_build_without_formulas(self):
        output_dir = self.root / 'missing-fallback'
        run = run_build(
            self.missing_build,
            self.input_dir,
            output_dir,
            '--katex',
            '--allow-missing-katex',
        )

        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn('显式降级参数继续', run.stdout)
        html = (output_dir / 'index.html').read_text(encoding='utf-8')
        self.assertIn('var KATEX_ENABLED = false;', html)

    def test_build_without_katex_does_not_require_assets(self):
        output_dir = self.root / 'without-katex'
        run = run_build(self.missing_build, self.input_dir, output_dir)

        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        html = (output_dir / 'index.html').read_text(encoding='utf-8')
        self.assertIn('var KATEX_ENABLED = false;', html)


if __name__ == '__main__':
    unittest.main()
