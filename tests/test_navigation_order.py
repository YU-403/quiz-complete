#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""QuizComplete 专题目录顺序回归测试。"""

import json
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
BUILD_PATH = ROOT / 'build.py'


def question_markdown(heading, metadata=''):
    metadata_block = metadata.strip()
    if metadata_block:
        metadata_block += '\n\n'
    return """\
# {heading}

{metadata}### 第 1 题（判断题）

这是一道用于目录顺序测试的题目（ ）

**答案**：正确

**解析**：测试解析。

**知识回溯**：{heading}·测试
""".format(heading=heading, metadata=metadata_block)


class NavigationOrderTests(unittest.TestCase):
    def build(self, files):
        temp_dir = tempfile.TemporaryDirectory(
            prefix='quiz-complete-navigation-'
        )
        self.addCleanup(temp_dir.cleanup)
        root = pathlib.Path(temp_dir.name)
        input_dir = root / 'input'
        output_dir = root / 'output'
        input_dir.mkdir()
        for filename, content in files:
            (input_dir / filename).write_text(content, encoding='utf-8')

        run = subprocess.run(
            [
                sys.executable,
                str(BUILD_PATH),
                '--input', str(input_dir),
                '--title', '专题目录顺序测试',
                '--output', str(output_dir),
                '--modes', 'topic',
            ],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=60,
        )
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        html = (output_dir / 'index.html').read_text(encoding='utf-8')
        order_match = re.search(
            r'const sectionOrder = (\[.*?\]);',
            html,
            re.DOTALL,
        )
        map_match = re.search(
            r'const sectionMap = (\{.*?\});\n',
            html,
            re.DOTALL,
        )
        self.assertIsNotNone(order_match)
        self.assertIsNotNone(map_match)
        return (
            run.stdout,
            html,
            json.loads(order_match.group(1)),
            json.loads(map_match.group(1)),
        )

    def test_flat_sections_keep_file_order_instead_of_pinyin_sort(self):
        stdout, html, order, section_map = self.build([
            ('00_导言.md', question_markdown('导言')),
            ('01_第一章.md', question_markdown('第一章 语言的功能')),
            ('02_第二章.md', question_markdown('第二章 语言是符号系统')),
            ('03_第三章.md', question_markdown('第三章 语音和音系')),
        ])

        expected = [
            '导言',
            '第一章 语言的功能',
            '第二章 语言是符号系统',
            '第三章 语音和音系',
        ]
        self.assertEqual(order, expected)
        self.assertEqual(list(section_map), expected)
        self.assertIn('专题目录顺序: ' + ' → '.join(expected), stdout)
        self.assertNotIn(
            "a.localeCompare(b, 'zh-CN')",
            html,
        )

    def test_simplified_order_metadata_works_without_board(self):
        _stdout, _html, order, section_map = self.build([
            (
                '00_甲.md',
                question_markdown(
                    '目录位置丙',
                    '**顺序**：30',
                ),
            ),
            (
                '01_乙.md',
                question_markdown(
                    '目录位置甲',
                    '**顺序**：10',
                ),
            ),
            (
                '02_丙.md',
                question_markdown(
                    '目录位置乙',
                    '**顺序**：20',
                ),
            ),
        ])

        expected = ['目录位置甲', '目录位置乙', '目录位置丙']
        self.assertEqual(order, expected)
        self.assertEqual(list(section_map), expected)

    def test_board_and_order_metadata_still_render_two_level_tree(self):
        _stdout, html, order, section_map = self.build([
            (
                '00_甲一.md',
                question_markdown(
                    '甲组后章',
                    '**板块**：甲组\n**顺序**：2',
                ),
            ),
            (
                '01_乙一.md',
                question_markdown(
                    '乙组前章',
                    '**板块**：乙组\n**顺序**：1',
                ),
            ),
            (
                '02_甲二.md',
                question_markdown(
                    '甲组前章',
                    '**板块**：甲组\n**顺序**：1',
                ),
            ),
            (
                '03_乙二.md',
                question_markdown(
                    '乙组后章',
                    '**板块**：乙组\n**顺序**：2',
                ),
            ),
        ])

        self.assertEqual(
            order,
            ['甲组前章', '甲组后章', '乙组前章', '乙组后章'],
        )
        self.assertEqual(list(section_map), order)
        tree_match = re.search(
            r'const sectionTree = (\[.*?\]);',
            html,
            re.DOTALL,
        )
        self.assertIsNotNone(tree_match)
        self.assertEqual(
            json.loads(tree_match.group(1)),
            [
                {'g': '甲组', 's': ['甲组前章', '甲组后章']},
                {'g': '乙组', 's': ['乙组前章', '乙组后章']},
            ],
        )


if __name__ == '__main__':
    unittest.main()
