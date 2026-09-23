#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
QuizComplete 打包脚本 — 生成可分发的 skill 压缩包

用法:
    python pack.py                    # 输出到 _dist/quiz-complete.zip
    python pack.py --output <路径>     # 指定输出位置
    python pack.py --name <目录名>     # 指定包内顶层目录名（默认 quiz-complete）

设计要点（每一条都对应一次实际踩过的坑）：

1. **顶层目录名用 `quiz-complete`，与 SKILL.md 的 frontmatter 的 `name` 一致。**
   客户端按目录名与 name 识别 skill；若两者不一致，用户解压后还要手动改名才能用。

2. **保留 SKILL.md 的 frontmatter。**
   历史版本的打包流程会剥掉 frontmatter，导致「压缩包版」与「仓库版」内容不一致——
   从仓库 clone 安装能用，从压缩包安装却识别不出 skill。
   本文档所在仓库以源码树为准，压缩包必须与源码一致。

3. **连 assets/ 一起打包。**
   build.py 依赖同目录的 assets/katex/；缺失时 --katex 会静默跳过公式渲染。
   打包后会自动校验关键文件是否齐全。
"""
import argparse
import os
import sys
import zipfile

# 修复 Windows 控制台默认 GBK 编码导致的输出报错（与 build.py 一致）
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
elif hasattr(sys.stdout, 'buffer'):
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 必须打入包内的文件（相对本目录）
REQUIRED_FILES = ['SKILL.md', 'build.py', 'README.md', 'LICENSE']
REQUIRED_DIRS = ['assets/katex']

# 排除项：开发用文件与产物，不应进入分发包
EXCLUDE_PATTERNS = [
    '.git', '.gitignore', '.gitattributes', '__pycache__', '.pytest_cache',
    '_dist', 'pack.py', 'index.html', 'build.bat', '*.pyc', '*.bak', '*.zip',
    '.DS_Store', 'Thumbs.db',
]


def should_exclude(rel_path, name):
    """判断某路径是否应排除出分发包。"""
    parts = rel_path.replace('\\', '/').split('/')
    for pat in EXCLUDE_PATTERNS:
        if pat.startswith('*'):
            if name.endswith(pat[1:]):
                return True
        elif pat in parts:
            return True
    return False


def check_prerequisites(root):
    """校验必需文件是否齐全，并特别检查 frontmatter 是否存在。"""
    problems = []
    for f in REQUIRED_FILES:
        if not os.path.exists(os.path.join(root, f)):
            problems.append('缺少文件: %s' % f)
    for d in REQUIRED_DIRS:
        if not os.path.isdir(os.path.join(root, d)):
            problems.append('缺少目录: %s' % d)

    # 关键检查：SKILL.md 必须带 frontmatter，否则客户端无法识别
    skill = os.path.join(root, 'SKILL.md')
    if os.path.exists(skill):
        with open(skill, encoding='utf-8') as fh:
            text = fh.read()
        if not text.startswith('---'):
            problems.append(
                'SKILL.md 缺少 frontmatter —— 客户端将无法识别此 skill。\n'
                '      请确认文件开头是 "---\\nname: ..." 形式的元数据块。')
        else:
            blocks = text.split('---')
            if len(blocks) < 3:
                problems.append('SKILL.md 的 frontmatter 未正确闭合（缺少结尾的 ---）')
            elif 'name:' not in blocks[1]:
                problems.append('SKILL.md 的 frontmatter 中缺少 name 字段')
    return problems


def main():
    ap = argparse.ArgumentParser(description='打包 QuizComplete skill 压缩包')
    ap.add_argument('--output', default='', help='输出 zip 路径（默认 _dist/quiz-complete.zip）')
    ap.add_argument('--name', default='quiz-complete',
                    help='包内顶层目录名（默认 quiz-complete，应与 frontmatter 的 name 一致）')
    args = ap.parse_args()

    root = os.path.dirname(os.path.abspath(__file__))
    out = args.output or os.path.join(root, '_dist', 'quiz-complete.zip')

    problems = check_prerequisites(root)
    if problems:
        print('❌ 打包前检查未通过：')
        for p in problems:
            print('   · %s' % p)
        sys.exit(1)

    os.makedirs(os.path.dirname(out), exist_ok=True)
    if os.path.exists(out):
        os.remove(out)

    count = 0
    total_bytes = 0
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        for dirpath, dirnames, filenames in os.walk(root):
            # 就地过滤，避免走进被排除的目录
            dirnames[:] = [d for d in dirnames
                           if not should_exclude(os.path.relpath(os.path.join(dirpath, d), root), d)]
            for fn in filenames:
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, root)
                if should_exclude(rel, fn):
                    continue
                arc = args.name + '/' + rel.replace('\\', '/')
                z.write(full, arc)
                count += 1
                total_bytes += os.path.getsize(full)

    size_kb = os.path.getsize(out) / 1024
    print('✅ 打包完成')
    print('   输出: %s' % out)
    print('   大小: %.0f KB（%d 个文件，未压缩合计 %.0f KB）'
          % (size_kb, count, total_bytes / 1024))
    print('   顶层目录: %s/' % args.name)

    # 复核：包内 SKILL.md 是否保留了 frontmatter
    with zipfile.ZipFile(out) as z:
        with z.open(args.name + '/SKILL.md') as fh:
            head = fh.read(80).decode('utf-8', 'replace')
    if head.startswith('---'):
        print('   ✅ SKILL.md 含 frontmatter（客户端可识别）')
    else:
        print('   ❌ SKILL.md 不含 frontmatter，安装后将无法识别！')


if __name__ == '__main__':
    main()
