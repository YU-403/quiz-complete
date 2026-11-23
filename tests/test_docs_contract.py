#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""QuizComplete 宿主与跨平台命令文档契约测试。"""

import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class DocumentationContractTests(unittest.TestCase):
    def test_readme_lists_supported_agent_hosts_and_paths(self):
        readme = (ROOT / 'README.md').read_text(encoding='utf-8')

        for host in ('Codex', 'WorkBuddy', 'Claude Code', 'DeepSeek Harness（DSH）'):
            self.assertIn(host, readme)
        for path in (
            '%USERPROFILE%\\.codex\\skills\\quiz-complete\\',
            '%USERPROFILE%\\.workbuddy\\skills\\quiz-complete\\',
            '%USERPROFILE%\\.claude\\skills\\quiz-complete\\',
            '%USERPROFILE%\\.dsh\\skills\\quiz-complete\\',
            '~/.codex/skills/quiz-complete/',
            '~/.workbuddy/skills/quiz-complete/',
            '~/.claude/skills/quiz-complete/',
            '~/.dsh/skills/quiz-complete/',
        ):
            self.assertIn(path, readme)
        self.assertIn('下载压缩包（安装无需运行 Python）', readme)
        self.assertNotIn('兼容 Claude Agent', readme)
        self.assertNotIn('Cherry Studio', readme)

    def test_build_commands_cover_windows_and_unix(self):
        skill = (ROOT / 'SKILL.md').read_text(encoding='utf-8')
        readme = (ROOT / 'README.md').read_text(encoding='utf-8')
        pack = (ROOT / 'pack.py').read_text(encoding='utf-8')

        self.assertIn('支持 Agent Skills 与本地文件访问的宿主', skill)
        self.assertIn('py -3 "<skill_dir>\\build.py"', skill)
        self.assertIn('python3 "<skill_dir>/build.py"', skill)
        self.assertIn('py -3 build.py', readme)
        self.assertIn('python3 build.py', readme)
        self.assertIn('py -3 pack.py', readme)
        self.assertIn('python3 pack.py', readme)
        self.assertIn('py -3 pack.py', pack)
        self.assertIn('python3 pack.py', pack)


if __name__ == '__main__':
    unittest.main()
