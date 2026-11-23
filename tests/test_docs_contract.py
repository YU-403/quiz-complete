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
        build_guide = (ROOT / 'references/建站指南.md').read_text(
            encoding='utf-8'
        )

        self.assertIn('支持 Agent Skills 与本地文件访问的宿主', skill)
        self.assertIn('py -3 "<skill_dir>\\build.py"', build_guide)
        self.assertIn('python3 "<skill_dir>/build.py"', build_guide)
        self.assertIn('py -3 build.py', readme)
        self.assertIn('python3 build.py', readme)
        self.assertIn('py -3 pack.py', readme)
        self.assertIn('python3 pack.py', readme)
        self.assertIn('py -3 pack.py', pack)
        self.assertIn('python3 pack.py', pack)
        self.assertIn('--allow-missing-katex', build_guide)
        self.assertIn('--allow-missing-katex', readme)
        self.assertNotIn('静默失效', readme)
        self.assertNotIn('会提示资源缺失并跳过公式渲染', build_guide)
        self.assertIn('不生成或覆盖页面', readme)
        self.assertIn('不生成或覆盖 `index.html`', build_guide)

    def test_requirements_document_is_the_single_project_source(self):
        skill = (ROOT / 'SKILL.md').read_text(encoding='utf-8')
        readme = (ROOT / 'README.md').read_text(encoding='utf-8')
        template_path = ROOT / 'references/需求文档模板.md'
        template = template_path.read_text(encoding='utf-8')

        self.assertTrue(template_path.is_file())
        self.assertFalse((ROOT / 'references/项目状态模板.md').exists())
        self.assertIn('一次只问一个问题', skill)
        self.assertIn('默认：无（必须选择）', skill)
        self.assertIn('REQUIREMENTS.md', skill)
        self.assertIn('不能放入 `题库/`', skill)
        self.assertIn('REQUIREMENTS.md', readme)
        self.assertNotIn('FACT.md', skill)
        self.assertNotIn('JOURNAL', skill)
        self.assertNotIn('长期记忆中的项目状态', readme)
        self.assertIn('唯一的需求、决策、验收和跨会话恢复来源', template)
        self.assertIn('## 当前有效需求', template)
        self.assertIn('## 需求复核记录', template)

    def test_skill_uses_progressive_disclosure(self):
        skill_path = ROOT / 'SKILL.md'
        skill = skill_path.read_text(encoding='utf-8')
        lines = skill.splitlines()

        self.assertLessEqual(len(lines), 250)
        self.assertLessEqual(
            max(
                (
                    len(line) - len(line.lstrip('#'))
                    for line in lines
                    if line.startswith('#')
                ),
                default=0,
            ),
            3,
        )
        for reference in (
            'references/需求采集.md',
            'references/出题规范.md',
            'references/建站指南.md',
            'references/需求文档模板.md',
            'references/模板维护.md',
        ):
            self.assertIn(reference, skill)
            self.assertTrue((ROOT / reference).is_file())

    def test_ci_workflow_covers_supported_release_matrix(self):
        workflow_path = ROOT / '.github/workflows/tests.yml'
        workflow = workflow_path.read_text(encoding='utf-8')
        readme = (ROOT / 'README.md').read_text(encoding='utf-8')

        self.assertTrue(workflow_path.is_file())
        self.assertIn('ubuntu-latest', workflow)
        self.assertIn('windows-latest', workflow)
        self.assertIn('"3.8"', workflow)
        self.assertIn('"3.12"', workflow)
        self.assertIn('node-version: "22"', workflow)
        self.assertIn('python -m unittest discover -s tests -v', workflow)
        self.assertIn('## 测试与持续集成', readme)


if __name__ == '__main__':
    unittest.main()
