#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""QuizComplete 发布包契约回归测试。"""

import pathlib
import subprocess
import sys
import tempfile
import unittest
import zipfile


ROOT = pathlib.Path(__file__).resolve().parents[1]
PACK_SCRIPT = ROOT / 'pack.py'
TOP_LEVEL = 'quiz-complete/'
REQUIRED_FILES = {
    TOP_LEVEL + 'SKILL.md',
    TOP_LEVEL + 'build.py',
    TOP_LEVEL + 'README.md',
    TOP_LEVEL + 'LICENSE',
    TOP_LEVEL + 'THIRD_PARTY_NOTICES.md',
    TOP_LEVEL + 'references/模板维护.md',
    TOP_LEVEL + 'references/需求文档模板.md',
}
EXCLUDED_PREFIXES = (
    TOP_LEVEL + 'pack.py',
    TOP_LEVEL + 'tests/',
    TOP_LEVEL + '.github/',
    TOP_LEVEL + '.gitignore',
    TOP_LEVEL + '.gitattributes',
    TOP_LEVEL + '__pycache__/',
)


class PackageContractTests(unittest.TestCase):
    def test_release_package_contains_runtime_files_only(self):
        with tempfile.TemporaryDirectory(prefix='quiz-complete-package-') as tmp:
            tmp_path = pathlib.Path(tmp)
            output_zip = tmp_path / 'quiz-complete.zip'

            run = subprocess.run(
                [
                    sys.executable,
                    str(PACK_SCRIPT),
                    '--output', str(output_zip),
                ],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=60,
            )
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertTrue(output_zip.is_file())

            with zipfile.ZipFile(output_zip) as archive:
                names = {
                    name for name in archive.namelist()
                    if not name.endswith('/')
                }
                self.assertTrue(
                    all(name.startswith(TOP_LEVEL) for name in names),
                    names,
                )
                self.assertTrue(REQUIRED_FILES.issubset(names), sorted(names))
                self.assertFalse(any(
                    name.startswith(EXCLUDED_PREFIXES)
                    for name in names
                ), sorted(names))
                self.assertTrue(any(
                    name.startswith(TOP_LEVEL + 'assets/katex/fonts/')
                    and name.endswith('.woff2')
                    for name in names
                ))

                skill_md = archive.read(TOP_LEVEL + 'SKILL.md').decode('utf-8')
                self.assertTrue(skill_md.startswith('---\nname: quiz-complete\n'))
                readme = archive.read(TOP_LEVEL + 'README.md').decode('utf-8')
                self.assertIn(
                    '不能直接在下载后的 Release 目录中运行',
                    readme,
                )
                self.assertIn('WorkBuddy', readme)
                self.assertIn('DeepSeek Harness（DSH）', readme)
                self.assertIn('REQUIREMENTS.md', readme)
                self.assertNotIn(
                    TOP_LEVEL + 'references/项目状态模板.md',
                    names,
                )

            extracted = tmp_path / 'extracted'
            with zipfile.ZipFile(output_zip) as archive:
                archive.extractall(extracted)
            help_run = subprocess.run(
                [
                    sys.executable,
                    str(extracted / TOP_LEVEL / 'build.py'),
                    '--help',
                ],
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=60,
            )
            self.assertEqual(
                help_run.returncode,
                0,
                help_run.stdout + help_run.stderr,
            )
            self.assertIn('--input', help_run.stdout)


if __name__ == '__main__':
    unittest.main()
