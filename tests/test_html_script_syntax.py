#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""QuizComplete 生成页面内联 JavaScript 语法测试。"""

import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
BUILD_PATH = ROOT / 'build.py'
NODE_PATH = shutil.which('node')
QUESTION_MARKDOWN = """\
# 脚本语法测试

### 第 1 题（判断题）

公式 $x^2$ 成立（ ）

**答案**：正确

**解析**：公式为 $x^2$。

**知识回溯**：测试·公式
"""


@unittest.skipUnless(NODE_PATH, '需要 Node.js 执行 JavaScript 语法检查')
class HtmlScriptSyntaxTests(unittest.TestCase):
    def test_generated_inline_scripts_are_valid_javascript(self):
        for use_katex in (False, True):
            with self.subTest(katex=use_katex):
                with tempfile.TemporaryDirectory(
                    prefix='quiz-complete-js-syntax-'
                ) as tmp:
                    root = pathlib.Path(tmp)
                    input_dir = root / 'input'
                    output_dir = root / 'output'
                    input_dir.mkdir()
                    (input_dir / 'questions.md').write_text(
                        QUESTION_MARKDOWN,
                        encoding='utf-8',
                    )
                    command = [
                        sys.executable,
                        str(BUILD_PATH),
                        '--input', str(input_dir),
                        '--title', '脚本语法测试',
                        '--output', str(output_dir),
                    ]
                    if use_katex:
                        command.append('--katex')
                    build_run = subprocess.run(
                        command,
                        cwd=str(ROOT),
                        capture_output=True,
                        text=True,
                        encoding='utf-8',
                        errors='replace',
                        timeout=60,
                    )
                    self.assertEqual(
                        build_run.returncode,
                        0,
                        build_run.stdout + build_run.stderr,
                    )

                    html = (output_dir / 'index.html').read_text(encoding='utf-8')
                    scripts = re.findall(
                        r'<script\b[^>]*>(.*?)</script>',
                        html,
                        re.DOTALL | re.IGNORECASE,
                    )
                    self.assertTrue(scripts)
                    script_path = root / 'inline.js'
                    script_path.write_text(
                        '\n;\n'.join(scripts),
                        encoding='utf-8',
                    )

                    syntax_run = subprocess.run(
                        [NODE_PATH, '--check', str(script_path)],
                        capture_output=True,
                        text=True,
                        encoding='utf-8',
                        errors='replace',
                        timeout=60,
                    )
                    self.assertEqual(
                        syntax_run.returncode,
                        0,
                        syntax_run.stdout + syntax_run.stderr,
                    )


if __name__ == '__main__':
    unittest.main()
