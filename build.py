#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
《刷题网站生成器》— 统一构建脚本
用法: python build.py --input <题库路径> --title <标题> --output <输出目录>
                      [--modes topic,random,career,wrong,tag] [--style 宣纸|瑞士|卡片]
                      [--katex] [--prefix <存储前缀>]

依赖: Python 标准库（os, re, json, hashlib, argparse），零第三方依赖。

v2.2 变更:
  - 题型标签彩色化: 做题界面用蓝/橙/绿 Badge 醒目显示题型
  - 考试模式自定义题数: 每次开始前弹窗输入题数
  - 递归搜索 .md: 子目录中的题集文件也能被识别
  - 板块列表排序: 用 localeCompare 按中文语义排序，不再乱序
  - 知识点取消回首页: 取消按钮同时返回首页并清除选中状态
"""

import os
import re
import json
import hashlib
import argparse
import sys
import base64

# 修复 Windows GBK 编码问题
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
elif hasattr(sys.stdout, 'buffer'):
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


# ============================================================
# KaTeX 资源（仅在 --katex 时内联进单文件）
# ============================================================
KATEX_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets', 'katex')


def _katex_css_with_inline_fonts():
    """读取 katex.min.css，只保留 woff2 字体并转成 base64，保证单文件离线可用。"""
    css_path = os.path.join(KATEX_DIR, 'katex.min.css')
    with open(css_path, 'r', encoding='utf-8') as f:
        css = f.read()

    def fix_face(m):
        block = m.group(0)

        def fix_url(mm):
            name = mm.group(1)
            fmt = mm.group(2)
            if fmt != 'woff2':
                return ''
            fp = os.path.join(KATEX_DIR, 'fonts', name)
            if not os.path.isfile(fp):
                return ''
            with open(fp, 'rb') as fh:
                b64 = base64.b64encode(fh.read()).decode('ascii')
            return 'url(data:font/woff2;base64,%s) format("woff2")' % b64

        block = re.sub(r'url\(fonts/([^)]+)\)\s*format\("([^"]+)"\)', fix_url, block)
        # 清理删除 woff/ttf 引用后残留的多余逗号
        block = re.sub(r',\s*,', ',', block)
        block = re.sub(r'src:\s*,', 'src:', block)
        block = re.sub(r',\s*\}', '}', block)
        return block

    return re.sub(r'@font-face\{[^}]*\}', fix_face, css)


def load_katex():
    """返回 (css, js)；资源缺失时返回 (None, None)。"""
    css_path = os.path.join(KATEX_DIR, 'katex.min.css')
    js_path = os.path.join(KATEX_DIR, 'katex.min.js')
    if not (os.path.isfile(css_path) and os.path.isfile(js_path)):
        return None, None
    with open(js_path, 'r', encoding='utf-8') as f:
        js = f.read()
    return _katex_css_with_inline_fonts(), js


def json_for_script(obj):
    """内联进 <script> 的 JSON：转义 </ 避免题库内容中的 </script> 提前闭合标签。"""
    return json.dumps(obj, ensure_ascii=False).replace('</', '<\\/')


def normalize_punctuation(text):
    """构建期的中文标点规范化（不改动题库源文件，也不参与题目 ID 与版本哈希计算）。

    - 直引号按出现顺序成对转换：双引号 " → “ ”、单引号 ' → ‘ ’
    - 英文撇号（形如 don't，前后均为 ASCII 字母）保留原样
    - 三个英文句点 ... → 中文省略号 ……
    - 两个连字符 -- → 中文破折号 ——
    - 反引号包裹的代码段整体原样保留
    """
    if not text or ('"' not in text and "'" not in text and '...' not in text and '--' not in text):
        return text
    parts = re.split(r'(```[\s\S]*?```|`[^`\n]*`)', text)
    out = []
    for i, part in enumerate(parts):
        if i % 2 == 1:          # 奇数位是代码段，原样保留
            out.append(part)
            continue
        buf = []
        dq_open = True
        sq_open = True
        for j, ch in enumerate(part):
            if ch == '"':
                buf.append('\u201c' if dq_open else '\u201d')
                dq_open = not dq_open
            elif ch == "'":
                prev = part[j - 1] if j > 0 else ''
                nxt = part[j + 1] if j + 1 < len(part) else ''
                if prev.isascii() and prev.isalpha() and nxt.isascii() and nxt.isalpha():
                    buf.append(ch)                      # 英文撇号，保留原样
                else:
                    buf.append('\u2018' if sq_open else '\u2019')
                    sq_open = not sq_open
            else:
                buf.append(ch)
        s = ''.join(buf)
        s = s.replace('...', '\u2026\u2026')        # ... → ……
        s = s.replace('--', '\u2014\u2014')         # -- → ——
        out.append(s)
    return ''.join(out)


# ============================================================
# HTML 模板（以下划线__大写__为占位符，用 str.replace 注入）
# ============================================================
HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>__TITLE__</title>
<style>
/* ============================================================
   刷题网站 — 统一样式
   风格变量通过 CSS 自定义属性注入
   ============================================================ */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

__STYLE_CSS__

body {
  font-family: __FONT_FAMILY__;
  background: var(--bg-page);
  color: var(--text-primary);
  min-height: 100vh;
  line-height: 1.8;
}

/* --- 顶部提示条 --- */
.top-bar {
  background: linear-gradient(135deg, var(--accent), var(--accent-dark));
  color: var(--bg-page);
  text-align: center;
  padding: 6px 16px;
  font-size: 13px;
  font-family: __SANS_FAMILY__;
  letter-spacing: 0.5px;
}
.top-bar .version-tip { display: none; }
.top-bar .version-tip.show { display: inline; }

/* --- 主容器 --- */
.container { max-width: 800px; margin: 0 auto; padding: 24px 20px 80px; }

/* --- 首页标题 --- */
.site-title { text-align: center; padding: 48px 0 32px; position: relative; }
.site-title h1 { font-size: 32px; font-weight: 700; color: var(--accent-dark); letter-spacing: 6px; }
.site-title .subtitle { font-size: 14px; color: var(--text-light); margin-top: 8px; font-family: __SANS_FAMILY__; letter-spacing: 2px; }
.site-title::after { content: ''; display: block; width: 60px; height: 2px; background: linear-gradient(90deg, transparent, var(--gold), transparent); margin: 20px auto 0; }
.fav-entry {
  position: absolute; top: 4px; right: 0;
  background: transparent; border: 1px solid var(--border-light); border-radius: 18px;
  padding: 4px 12px; font-size: 13px; color: var(--text-secondary);
  cursor: pointer; transition: all 0.25s ease; font-family: __SANS_FAMILY__;
  display: inline-flex; align-items: center; gap: 4px;
}
.fav-entry:hover { border-color: var(--gold); color: var(--text-primary); transform: scale(1.04); }
.fav-entry .fav-entry-count { color: var(--accent); font-weight: 700; }
@media (max-width: 768px) {
  .fav-entry { top: 0; padding: 3px 10px; font-size: 12px; }
  .fav-entry .fav-entry-text { display: none; }
}

/* --- 模式选择卡片 --- */
.mode-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 16px; margin: 24px 0; }
.mode-card {
  background: var(--bg-card); border: 1px solid var(--border-light); border-radius: 12px;
  padding: 24px 20px; cursor: pointer; text-align: center;
  transition: all 0.3s ease; position: relative; overflow: hidden;
}
.mode-card::before {
  content: ''; position: absolute; top: 0; left: 0; right: 0; height: 3px;
  background: linear-gradient(90deg, var(--gold), var(--accent), var(--gold));
  opacity: 0; transition: opacity 0.3s ease;
}
.mode-card:hover { transform: scale(1.04); box-shadow: 0 8px 24px var(--shadow); }
.mode-card:hover::before { opacity: 1; }
.mode-card:active { transform: scale(0.96); }
.mode-card .icon { font-size: 36px; margin-bottom: 12px; display: block; }
.mode-card .name { font-size: 18px; font-weight: 600; color: var(--text-primary); font-family: __SANS_FAMILY__; }
.mode-card .desc { font-size: 13px; color: var(--text-secondary); margin-top: 6px; line-height: 1.6; }
.mode-card { position: relative; }
.mode-badge {
  position: absolute; top: 10px; right: 10px;
  font-size: 11px; font-weight: 600; padding: 2px 9px; border-radius: 10px;
  background: var(--accent-light); color: var(--accent-dark);
  font-family: __SANS_FAMILY__;
}
.mode-badge.zero { background: var(--border-light); color: var(--text-light); font-weight: 400; }
.home-summary {
  display: flex; flex-wrap: wrap; gap: 6px 22px;
  margin: 16px 0 2px; font-size: 14px; color: var(--text-secondary);
  font-family: __SANS_FAMILY__;
}
.home-summary b { color: var(--accent-dark); font-size: 18px; font-weight: 700; margin: 0 2px; }

/* --- 页面切换 --- */
.page { display: none; opacity: 0; }
.page.active { display: block; animation: page-slide-in 0.35s ease forwards; }
@keyframes page-slide-in {
  from { opacity: 0; transform: translateY(16px); }
  to { opacity: 1; transform: translateY(0); }
}

/* --- 板块选择页 --- */
.section-list { display: grid; gap: 12px; margin: 20px 0; }
.section-item {
  background: var(--bg-card); border: 1px solid var(--border-light); border-radius: 10px;
  padding: 18px 20px; cursor: pointer; transition: all 0.3s ease;
  display: flex; align-items: center; justify-content: space-between;
}
.section-item:hover { transform: scale(1.02); box-shadow: 0 4px 12px var(--shadow); }
.section-item:active { transform: scale(0.98); }
.section-item .sec-name { font-size: 17px; font-weight: 600; }
.section-item .sec-count { font-size: 13px; color: var(--text-light); font-family: __SANS_FAMILY__; }

/* --- 知识点树状选择 --- */
.modal.modal-wide { max-width: 960px; }
.picked-count {
  font-family: __SANS_FAMILY__; font-size: 12px; color: var(--accent-dark);
  background: rgba(184, 69, 30, 0.12);
  background: color-mix(in srgb, var(--accent) 14%, transparent);
  padding: 2px 10px; border-radius: 10px; margin-left: 6px;
}
.tag-tree { border: 1px solid var(--border-light); border-radius: 12px; overflow-y: auto; max-height: 52vh; }
.tree-group + .tree-group { border-top: 1px solid var(--border-light); }
.group-head {
  display: flex; align-items: center; gap: 10px; padding: 12px 16px;
  cursor: pointer; user-select: none; font-family: __SANS_FAMILY__; transition: background 0.2s ease;
}
.group-head:hover { background: rgba(0, 0, 0, 0.035); }
.group-head .caret { font-size: 11px; color: var(--text-light); transition: transform 0.22s ease; width: 12px; text-align: center; }
.tree-group.open .caret { transform: rotate(90deg); }
.group-name { font-size: 15px; font-weight: 600; }
.group-count { font-size: 12px; color: var(--text-light); margin-left: auto; }
.group-all {
  font-size: 12px; font-family: __SANS_FAMILY__; padding: 3px 12px; border-radius: 12px;
  border: 1px solid var(--border); background: var(--bg-card); color: var(--text-secondary);
  cursor: pointer; transition: all 0.2s ease; margin-left: 4px;
}
.group-all:hover { border-color: var(--gold); color: var(--accent-dark); }
.group-all.on { background: var(--accent); border-color: var(--accent); color: #fff; }
.group-body { display: none; flex-wrap: wrap; gap: 8px; padding: 2px 16px 16px 38px; }
.tree-group.open .group-body { display: flex; }
.tag-item {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 6px 13px; border: 1px solid var(--border-light); border-radius: 16px;
  background: var(--bg-card); cursor: pointer; font-size: 13px; transition: all 0.2s ease;
}
.tag-item:hover { border-color: var(--gold); }
.tag-item.checked { background: var(--accent); border-color: var(--accent); color: #fff; }
.tag-item .tick { font-size: 11px; opacity: 0.45; font-family: __SANS_FAMILY__; }
.tag-item.checked .tick { opacity: 1; }
@media (max-width: 768px) {
  .modal.modal-wide { max-width: 94vw; }
  .group-body { padding-left: 16px; }
  .group-count { display: none; }
}

/* --- 答题区 --- */
.question-area {
  background: var(--bg-card); border: 1px solid var(--border-light);
  border-radius: 12px; padding: 28px 24px; margin: 16px 0;
  box-shadow: 0 2px 12px var(--shadow);
}
.q-header { margin-bottom: 16px; font-family: __SANS_FAMILY__; }
.q-top { display: grid; grid-template-columns: 1fr auto 1fr; align-items: center; min-height: 38px; }
.q-top .q-type { grid-column: 2; justify-self: center; }
.q-top .q-flag-btn { grid-column: 3; justify-self: end; }
.q-bottom { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-top: 8px; }
.q-number { font-size: 14px; color: var(--text-light); font-weight: 500; }
.q-type { font-size: 13px; font-weight: 700; padding: 3px 12px; border-radius: 4px; letter-spacing: 1px; }
.q-type.single { color: #fff; background: #3b82f6; }
.q-type.multiple { color: #fff; background: #f59e0b; }
.q-type.judge { color: #fff; background: #10b981; }
.q-section { font-size: 12px; color: var(--gold); background: var(--gold-light); padding: 2px 10px; border-radius: 10px; }
.q-text { font-size: 17px; line-height: 1.9; margin-bottom: 20px; padding: 12px 0; border-bottom: 1px dashed var(--border-light); }

/* --- 选项（单选） --- */
.options { display: flex; flex-direction: column; gap: 10px; }
.opt-item {
  padding: 12px 16px; border: 1px solid var(--border-light); border-radius: 8px;
  cursor: pointer; transition: all 0.3s ease; background: #fff;
  animation: opt-in 0.3s ease backwards;
  display: flex; gap: 12px; align-items: flex-start;
}
.opt-label {
  flex: 0 0 auto; width: 26px; height: 26px; margin-top: 1px;
  display: inline-flex; align-items: center; justify-content: center;
  border: 1px solid var(--border); border-radius: 7px;
  font-family: __SANS_FAMILY__; font-size: 13px; font-weight: 700;
  color: var(--text-secondary); background: transparent;
  transition: all 0.25s ease;
}
.opt-body { flex: 1 1 auto; min-width: 0; }
.opt-item:hover { transform: scale(1.04); border-color: var(--gold); background: var(--bg-card-hover); }
.opt-item:hover .opt-label { border-color: var(--gold); }
.opt-item.selected .opt-label { background: var(--accent); border-color: var(--accent); color: #fff; }
.opt-item.correct .opt-label { background: var(--success); border-color: var(--success); color: #fff; }
.opt-item.wrong .opt-label { background: var(--error); border-color: var(--error); color: #fff; }
.opt-item.selected {
  border-color: var(--accent); background: rgba(184, 69, 30, 0.06);
  animation: select-pulse 0.35s ease;
}
@keyframes select-pulse {
  0% { box-shadow: 0 0 0 0 var(--accent-light); }
  100% { box-shadow: 0 0 0 10px rgba(184, 69, 30, 0); }
}
.opt-item.submitted { pointer-events: none; }
.opt-item.correct {
  border-color: var(--success); background: var(--success-bg);
  animation: correct-glow 2s ease-in-out infinite;
}
@keyframes correct-glow {
  0%, 100% { box-shadow: 0 0 0 0 rgba(74, 124, 89, 0.15); }
  50% { box-shadow: 0 0 0 6px rgba(74, 124, 89, 0.08); }
}
.opt-item.wrong { border-color: var(--error); background: var(--error-bg); animation: shake 0.4s ease; }
@keyframes opt-in { from { opacity: 0; margin-top: 8px; } to { opacity: 1; margin-top: 0; } }

/* --- 题目切换方向性过渡 --- */
@keyframes slide-out-left {
  from { opacity: 1; transform: translateX(0); }
  to { opacity: 0; transform: translateX(-30px); }
}
@keyframes slide-in-right {
  from { opacity: 0; transform: translateX(30px); }
  to { opacity: 1; transform: translateX(0); }
}
@keyframes slide-out-right {
  from { opacity: 1; transform: translateX(0); }
  to { opacity: 0; transform: translateX(30px); }
}
@keyframes slide-in-left {
  from { opacity: 0; transform: translateX(-30px); }
  to { opacity: 1; transform: translateX(0); }
}

/* --- 答错抖动 --- */
@keyframes shake {
  0%, 100% { transform: translateX(0); }
  20%, 60% { transform: translateX(-5px); }
  40%, 80% { transform: translateX(5px); }
}

/* --- 选项（判断） --- */
.judge-options { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin: 16px 0; }
.judge-btn {
  padding: 18px; text-align: center; border: 1px solid var(--border-light);
  border-radius: 10px; cursor: pointer; font-size: 18px; font-weight: 600;
  transition: all 0.3s ease; background: #fff; font-family: __FONT_FAMILY__;
}
.judge-btn:hover { transform: scale(1.04); border-color: var(--gold); }
.judge-btn.selected { border-color: var(--accent); background: rgba(184, 69, 30, 0.06); }
.judge-btn.submitted { pointer-events: none; }
.judge-btn.correct { border-color: var(--success); background: var(--success-bg); }
.judge-btn.wrong { border-color: var(--error); background: var(--error-bg); animation: shake 0.4s ease; }

/* --- 按钮 --- */
.action-row { display: flex; gap: 12px; margin-top: 20px; flex-wrap: wrap; justify-content: flex-end; }
.btn {
  padding: 10px 24px; border: 1px solid var(--border); border-radius: 8px;
  cursor: pointer; font-size: 14px; font-family: __SANS_FAMILY__;
  transition: all 0.3s ease; background: var(--bg-card); color: var(--text-primary);
}
.btn:hover { transform: scale(1.04); }
.btn:active { transform: scale(0.96); }
.btn-primary { background: var(--accent); color: #fff; border-color: var(--accent); }
.btn-primary:hover { background: var(--accent-dark); border-color: var(--accent-dark); }
.btn-secondary { background: var(--gold); color: #fff; border-color: var(--gold); }
.btn-secondary:hover { opacity: 0.9; }
.btn-outline { background: transparent; border-color: var(--border); }
.btn-cta {
  font-weight: 700; letter-spacing: .04em; border-color: var(--accent-dark);
  box-shadow: 0 0 0 3px rgba(0, 0, 0, 0.07);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 16%, transparent),
              0 3px 10px color-mix(in srgb, var(--accent) 24%, transparent);
}
.btn-cta:hover {
  border-color: var(--accent-dark);
  box-shadow: 0 0 0 4px color-mix(in srgb, var(--accent) 22%, transparent),
              0 5px 16px color-mix(in srgb, var(--accent) 32%, transparent);
}
.btn-outline:hover { border-color: var(--text-secondary); }

.nav-row { display: none; gap: 12px; margin-top: 16px; justify-content: center; }
.nav-row.show { display: flex; }

/* --- 收藏按钮 --- */
.q-flag-btn {
  width: 36px; height: 36px; line-height: 1; font-size: 16px; cursor: pointer;
  border: 1.5px solid var(--gold); border-radius: 8px;
  background: rgba(201, 168, 76, 0.13);
  background: color-mix(in srgb, var(--gold) 13%, transparent);
  display: inline-flex; align-items: center; justify-content: center;
  box-shadow: 0 0 0 3px rgba(201, 168, 76, 0.12);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--gold) 12%, transparent);
  transition: all 0.25s ease;
}
.q-flag-btn .star { display: block; line-height: 1; opacity: 0.68; transition: all 0.25s ease; }
.q-flag-btn:hover { transform: scale(1.06); background: color-mix(in srgb, var(--gold) 24%, transparent); }
.q-flag-btn:hover .star { opacity: 1; }
.q-flag-btn.on {
  background: color-mix(in srgb, var(--gold) 30%, transparent);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--gold) 24%, transparent);
}
.q-flag-btn.on .star { opacity: 1; filter: saturate(1.25) drop-shadow(0 0 5px rgba(201, 168, 76, 0.9)); }

/* --- 答题卡 --- */
.sheet-toggle {
  position: fixed; right: 20px; bottom: 24px; z-index: 900;
  padding: 10px 16px; border-radius: 24px; border: 1px solid var(--border);
  background: var(--bg-card); color: var(--text-primary); cursor: pointer;
  font-size: 14px; font-family: __SANS_FAMILY__; box-shadow: 0 6px 18px var(--shadow);
  transition: all 0.3s ease; display: none;
}
.sheet-toggle.show { display: inline-block; }
.sheet-toggle:hover { transform: scale(1.04); border-color: var(--gold); }
.sheet-toggle .cnt { color: var(--accent); font-weight: 700; margin-left: 4px; }

.sheet-overlay {
  position: fixed; top: 0; left: 0; right: 0; bottom: 0;
  background: rgba(61, 50, 41, 0.42); z-index: 950; opacity: 0; pointer-events: none;
  transition: opacity 0.25s ease;
}
.sheet-overlay.show { opacity: 1; pointer-events: auto; }
.sheet-panel {
  position: fixed; top: 0; right: 0; bottom: 0; width: 360px; max-width: 92vw;
  background: var(--bg-card); border-left: 1px solid var(--border);
  z-index: 960; display: flex; flex-direction: column;
  transform: translateX(105%); transition: transform 0.3s ease;
  box-shadow: -8px 0 32px rgba(61, 50, 41, 0.15);
}
.sheet-panel.show { transform: translateX(0); }
.sheet-head { display: flex; align-items: flex-start; justify-content: space-between; padding: 20px 20px 12px; }
.sheet-title { font-size: 18px; font-weight: 700; color: var(--accent-dark); font-family: __SANS_FAMILY__; }
.sheet-sub { font-size: 12px; color: var(--text-light); margin-top: 4px; }
.sheet-close {
  background: transparent; border: 1px solid var(--border-light); border-radius: 8px;
  width: 32px; height: 32px; cursor: pointer; color: var(--text-secondary); font-size: 14px;
}
.sheet-close:hover { border-color: var(--text-secondary); }
.sheet-legend { display: flex; flex-wrap: wrap; gap: 10px; padding: 0 20px 12px; font-size: 12px; color: var(--text-secondary); }
.sheet-legend .lg { display: inline-flex; align-items: center; gap: 4px; }
.sheet-legend .dot { width: 12px; height: 12px; border-radius: 3px; border: 1px solid var(--border); display: inline-block; }
.sheet-legend .dot.d-unanswered { background: var(--bg-page); }
.sheet-legend .dot.d-correct { background: var(--success-bg); border-color: var(--success); }
.sheet-legend .dot.d-wrong { background: var(--error-bg); border-color: var(--error); }
.sheet-legend .dot.d-flag { background: var(--gold-light); border-color: var(--gold); }
.sheet-legend .dot.d-answered { background: var(--accent-light); border-color: var(--accent); }
.sheet-legend .lg-answered { display: none; }
.sheet-legend.exam-neutral .lg-answered { display: inline-flex; }
.sheet-legend.exam-neutral .lg-correct,
.sheet-legend.exam-neutral .lg-wrong { display: none; }
.sheet-grid {
  flex: 1; overflow-y: auto; display: grid; gap: 8px; padding: 4px 20px 24px;
  grid-template-columns: repeat(auto-fill, minmax(44px, 1fr)); align-content: start;
}
.sheet-cell {
  position: relative; height: 44px; border-radius: 8px; border: 1px solid var(--border-light);
  background: var(--bg-page); color: var(--text-secondary); font-size: 13px;
  font-family: __SANS_FAMILY__; cursor: pointer; transition: all 0.2s ease;
  display: flex; align-items: center; justify-content: center;
}
.sheet-cell:hover { transform: scale(1.06); border-color: var(--gold); }
.sheet-cell.current { outline: 2px solid var(--accent); outline-offset: 1px; font-weight: 700; }
.sheet-cell.correct { background: var(--success-bg); border-color: var(--success); color: var(--success); }
.sheet-cell.wrong { background: var(--error-bg); border-color: var(--error); color: var(--error); }
.sheet-cell.answered { background: var(--accent-light); border-color: var(--accent); color: var(--accent-dark); }
.sheet-cell.unanswered { color: var(--text-light); opacity: 0.8; }
.sheet-cell.unanswered.locked { cursor: not-allowed; }
.sheet-cell.unanswered.locked:hover { transform: none; border-color: var(--border-light); }
.sheet-cell .star { position: absolute; top: -5px; right: -3px; font-size: 12px; line-height: 1; }

/* --- 智能抽题开关 --- */
.smart-switch {
  margin-top: 10px; display: inline-flex; align-items: center; gap: 6px;
  font-size: 12px; color: var(--text-secondary);
  border: 1px solid var(--border-light); border-radius: 16px; padding: 3px 10px;
  background: var(--bg-page); cursor: pointer; transition: all 0.25s ease;
}
.smart-switch:hover { border-color: var(--gold); }
.smart-switch .sw-state { font-weight: 700; color: var(--text-light); }
.smart-switch .sw-state.on { color: var(--success); }

/* --- 收藏列表页 --- */
.fav-list { display: flex; flex-direction: column; gap: 10px; margin: 16px 0; }
.fav-item {
  border: 1px solid var(--border-light); border-radius: 10px; padding: 14px 16px;
  background: var(--bg-card); cursor: pointer; transition: all 0.25s ease;
}
.fav-item:hover { transform: scale(1.01); border-color: var(--gold); }
.fav-item .fav-q { font-size: 15px; line-height: 1.6; color: var(--text-primary); }
.fav-meta { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-top: 8px; font-size: 12px; color: var(--text-light); }
.fav-status.ok { color: var(--success); }
.fav-status.bad { color: var(--error); }
.fav-status.none { color: var(--text-light); }
.fav-unstar {
  margin-left: auto; background: transparent; border: none; cursor: pointer;
  color: var(--gold); font-size: 16px;
}

/* --- 轻提示 --- */
.toast-mini {
  position: fixed; left: 50%; bottom: 96px; transform: translateX(-50%);
  background: rgba(0, 0, 0, 0.78); color: #fff; padding: 9px 16px; border-radius: 20px;
  font-size: 13px; z-index: 1200; opacity: 0; pointer-events: none; transition: opacity 0.2s ease;
}
.toast-mini.show { opacity: 1; }

@media (max-width: 768px) {
  .sheet-panel {
    top: auto; left: 0; right: 0; bottom: 0; width: 100%; height: 72vh;
    border-left: none; border-top: 1px solid var(--border);
    transform: translateY(105%);
  }
  .sheet-panel.show { transform: translateY(0); }
  .sheet-toggle { right: 14px; bottom: 16px; }
}

/* --- 裁决区 --- */
.verdict-area {
  margin-top: 20px; padding: 16px 20px; border-radius: 10px;
  animation: verdict-bounce 0.4s ease backwards;
}
.verdict-area.hidden { display: none; }
.verdict-area.correct { background: var(--success-bg); border-left: 4px solid var(--success); }
.verdict-area.wrong { background: var(--error-bg); border-left: 4px solid var(--error); }
@keyframes verdict-bounce {
  0% { opacity: 0; transform: translateY(-8px); }
  60% { transform: translateY(3px); }
  100% { opacity: 1; transform: translateY(0); }
}
.verdict-badge { font-size: 18px; font-weight: 700; margin-bottom: 8px; font-family: __SANS_FAMILY__; }

/* --- 结果块 --- */
.result-box {
  padding: 10px 14px; border-radius: 6px; margin-top: 8px; font-size: 14px; line-height: 1.7;
  opacity: 0; animation: fade-in 0.3s ease forwards;
}
.result-box:nth-child(2) { animation-delay: 0.12s; }
.result-box:nth-child(3) { animation-delay: 0.24s; }
.result-box:nth-child(4) { animation-delay: 0.36s; }
@keyframes fade-in { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }
.answer-box { background: #f0ede6; border-left: 3px solid var(--gold); }
.expl-box { background: #f5f2eb; border-left: 3px solid var(--accent-light); }
.tag-box { background: #edebe3; border-left: 3px solid var(--border); font-size: 12px; color: var(--text-light); font-family: __SANS_FAMILY__; }
.result-box .rb-label { font-weight: 600; margin-right: 6px; font-size: 13px; }
.answer-box .rb-label { color: var(--gold); }
.expl-box .rb-label { color: var(--accent); }
.tag-box .rb-label { color: var(--text-light); }

/* --- 进度条 --- */
.progress-bar-wrap {
  width: 100%; height: 6px; background: var(--border-light);
  border-radius: 3px; margin: 12px 0; overflow: hidden; position: relative;
}
.progress-bar {
  height: 100%; border-radius: 3px; transition: width 0.5s ease;
  background: linear-gradient(135deg, var(--gold), var(--accent)); position: relative;
}
.progress-bar::after {
  content: ''; position: absolute; top: 0; left: 0; right: 0; bottom: 0;
  background: linear-gradient(135deg, transparent 30%, rgba(255,255,255,0.25) 50%, transparent 70%);
  animation: shine 2s infinite;
}
@keyframes shine { 0% { transform: translateX(-100%); } 100% { transform: translateX(100%); } }

/* --- 进度条分段标记 --- */
.progress-bar-wrap { position: relative; }
.progress-dots { position: absolute; top: 0; left: 0; right: 0; bottom: 0; pointer-events: none; z-index: 2; }
.progress-dots .dot {
  position: absolute; width: 14px; height: 14px; border-radius: 50%;
  background: var(--bg-card); border: 2px solid var(--border);
  top: 50%; transform: translate(-50%, -50%);
  transition: all 0.35s ease;
  box-shadow: 0 0 0 0 var(--accent);
}
.progress-dots .dot.done {
  background: var(--accent); border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-light);
}
.progress-text { font-size: 13px; color: var(--text-light); font-family: __SANS_FAMILY__; text-align: right; }
.exam-timer {
  font-size: 14px; color: var(--accent-dark); font-family: __SANS_FAMILY__;
  text-align: right; margin-top: -4px; font-weight: 700; letter-spacing: 1px;
}

/* --- 连对标记 --- */
.streak-badge {
  display: none; background: linear-gradient(135deg, var(--gold), #d4a843);
  color: #fff; padding: 4px 14px; border-radius: 20px; font-size: 13px;
  font-weight: 600; font-family: __SANS_FAMILY__;
  animation: streak-pulse 0.6s ease backwards;
}
.streak-badge.show { display: inline-block; }
@keyframes streak-pulse {
  0% { opacity: 0; transform: scale(0.8); }
  50% { transform: scale(1.15); }
  100% { opacity: 1; transform: scale(1); }
}

/* --- 弹窗 --- */
.modal-overlay {
  position: fixed; top: 0; left: 0; right: 0; bottom: 0;
  background: rgba(61, 50, 41, 0.5); backdrop-filter: blur(4px);
  z-index: 1000; display: none; align-items: center; justify-content: center;
}
.modal-overlay.show { display: flex; }
.modal {
  background: var(--bg-card); border: 1px solid var(--border);
  border-radius: 16px; padding: 32px; max-width: 480px; width: 90%;
  max-height: 80vh; overflow-y: auto;
  box-shadow: 0 16px 48px rgba(61, 50, 41, 0.15);
  animation: modal-in 0.3s ease backwards;
}
@keyframes modal-in {
  from { opacity: 0; transform: scale(0.95) translateY(10px); }
  to { opacity: 1; transform: scale(1) translateY(0); }
}
.modal h2 { font-size: 22px; margin-bottom: 12px; color: var(--accent-dark); }
.modal p, .modal li { font-size: 14px; line-height: 1.8; color: var(--text-secondary); margin-bottom: 6px; }
.modal ul { padding-left: 20px; }
.modal .btn-row { margin-top: 20px; display: flex; gap: 12px; justify-content: flex-end; }
.countdown { font-size: 48px; font-weight: 700; text-align: center; color: var(--accent); margin: 20px 0; font-family: __SANS_FAMILY__; }

/* --- 完成页 --- */
.complete-page { text-align: center; padding: 40px 0; }
.complete-page .big-icon { font-size: 64px; margin-bottom: 16px; animation: badge-pop 0.7s cubic-bezier(0.34, 1.56, 0.64, 1) backwards; }
.complete-page h2 { font-size: 26px; color: var(--accent-dark); margin-bottom: 8px; }
.stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 16px; margin: 24px 0; }
.stat-card { background: var(--bg-card); border: 1px solid var(--border-light); border-radius: 12px; padding: 20px; }
.stat-card .stat-num { font-size: 36px; font-weight: 700; color: var(--accent); font-family: __SANS_FAMILY__; }
.stat-card .stat-label { font-size: 13px; color: var(--text-light); margin-top: 4px; }

/* --- 页脚 --- */
.footer { text-align: center; padding: 16px; font-size: 12px; color: var(--text-light); font-family: __SANS_FAMILY__; border-top: 1px solid var(--border-light); margin-top: 40px; }

/* --- 响应式 --- */
@media (max-width: 768px) {
  .container { padding: 12px; }
  .q-text { font-size: 16px; }
  .opt-item { gap: 10px; }
  .opt-label { width: 22px; height: 22px; font-size: 12px; }
}
.confetti-container {
  position: fixed; top: 0; left: 0; width: 100%; height: 100%;
  pointer-events: none; z-index: 9999; overflow: hidden;
}
.confetti-piece {
  position: absolute; top: -10px; border-radius: 3px;
  animation: confetti-fall linear forwards;
}
@keyframes confetti-fall {
  0% { transform: translateY(-10px) rotate(0deg); opacity: 1; }
  100% { transform: translateY(100vh) rotate(720deg); opacity: 0; }
}
@keyframes badge-pop {
  0% { transform: scale(0) rotate(-15deg); }
  70% { transform: scale(1.25) rotate(3deg); }
  100% { transform: scale(1) rotate(0); }
}

/* ============================================================
   富文本渲染（Markdown 子集）
   ============================================================ */
.md-table { border-collapse: collapse; margin: 12px 0; font-size: 15px; max-width: 100%; }
.md-table th, .md-table td { border: 1px solid var(--border-light); padding: 6px 12px; text-align: left; }
.md-table th { font-weight: 600; background: rgba(0,0,0,0.045); }
.md-table tbody tr:nth-child(even) { background: rgba(0,0,0,0.015); }
.md-blockquote { margin: 10px 0; padding: 6px 14px; border-left: 3px solid var(--border); color: var(--text-light); }
.md-list { margin: 8px 0; padding-left: 22px; }
.md-list li { margin: 3px 0; }
.md-code { background: rgba(0,0,0,0.05); padding: 10px 12px; border-radius: 6px; overflow-x: auto; margin: 10px 0; }
.md-code code { background: none; padding: 0; font-size: 13px; }
.md-inline-code { background: rgba(0,0,0,0.05); padding: 1px 5px; border-radius: 4px; font-size: 0.92em; font-family: __SANS_FAMILY__; }
.q-text p, .result-box p { margin: 0 0 8px; }
.q-text > *:last-child, .result-box p:last-child { margin-bottom: 0; }
.katex { font-size: 1.05em; }
.katex-display { margin: 12px 0; overflow-x: auto; overflow-y: hidden; }
__KATEX_CSS__
</style>
</head>
<body>

<div class="top-bar">
  <span>请刷新获得最新版本 · 按 F11 全屏</span>
  <span class="version-tip" id="versionTip"> · 题库已更新，请刷新页面</span>
</div>

<div class="container" id="app">

  <div class="page active" id="page-home">
    <div class="site-title">
      <button class="fav-entry" id="favEntry" onclick="window.openFavPage()" title="我的收藏">⭐<span class="fav-entry-text">我的收藏</span><span class="fav-entry-count" id="favEntryCount">0</span></button>
      <h1>__TITLE__</h1>
      <div class="subtitle">__SUBTITLE__</div>
    </div>
    <div class="home-summary" id="homeSummary"></div>
    <div class="mode-grid" id="modeGrid"></div>
  </div>

  <div class="page" id="page-section">
    <div class="back-row"><button class="btn btn-outline" onclick="window.showPage('page-home')">← 返回首页</button></div>
    <h2 style="font-size:22px;color:var(--accent-dark);">📖 选择板块</h2>
    <p style="font-size:14px;color:var(--text-secondary);margin:6px 0 16px;">选择一个板块开始顺序刷题</p>
    <div class="section-list" id="sectionList"></div>
  </div>

  <div class="page" id="page-tags">
    <div class="back-row"><button class="btn btn-outline" onclick="window.showPage('page-home')">← 返回首页</button></div>
    <h2 style="font-size:22px;color:var(--accent-dark);">🏷️ 选择知识点</h2>
    <p style="font-size:14px;color:var(--text-secondary);margin:6px 0 16px;">选择一个知识点标签，筛选对应题目</p>
    <div class="filter-grid" id="tagGrid"></div>
  </div>

  <div class="page" id="page-quiz">
    <div class="back-row"><button class="btn btn-outline" id="btnBack" onclick="window.exitQuiz()">← 返回</button></div>
    <div class="progress-bar-wrap"><div class="progress-bar" id="progressBar" style="width:0%"></div><div class="progress-dots" id="progressDots"></div></div>
    <div class="progress-text" id="progressText">0 / 0</div>
    <div class="exam-timer" id="examTimer" style="display:none;">⏱ 00:00</div>
    <div class="streak-badge" id="streakBadge">🔥 连对 0 题</div>
    <div class="question-area" id="questionArea">
      <div class="q-header">
        <div class="q-top">
          <span class="q-type" id="qType"></span>
          <button class="q-flag-btn" id="btnFlag" onclick="window.toggleFlag()" aria-pressed="false" title="收藏本题" aria-label="收藏本题"><span class="star">⭐</span></button>
        </div>
        <div class="q-bottom">
          <span class="q-number" id="qNumber">第 0 题</span>
          <span class="q-section" id="qSection"></span>
        </div>
      </div>
      <div class="q-text" id="qText"></div>
      <div id="optionsContainer"></div>
      <div class="action-row" id="actionRow">
        <button class="btn btn-primary btn-cta" id="btnSubmit" onclick="window.submitAnswer()">提交答案</button>
        <button class="btn btn-primary btn-cta" id="btnExamSubmit" style="display:none;" onclick="window.submitExam()">交卷</button>
      </div>
      <div class="verdict-area hidden" id="verdictArea">
        <div class="verdict-badge" id="verdictBadge"></div>
        <div id="resultBoxes"></div>
      </div>
      <div class="nav-row" id="navRow">
        <button class="btn btn-outline" id="btnPrev" onclick="window.prevQuestion()">← 上一题</button>
        <button class="btn btn-outline" id="btnReturn" style="display:none;" onclick="window.backToCurrent()">回到当前进度</button>
        <button class="btn btn-outline" id="btnNext" onclick="window.nextQuestion()">下一题 →</button>
      </div>
    </div>
  </div>

  <button class="sheet-toggle" id="btnSheet" onclick="window.openSheet()" aria-label="打开答题卡">答题卡<span class="cnt" id="sheetProgress">0/0</span></button>

  <div class="sheet-overlay" id="sheetOverlay" onclick="window.closeSheet()"></div>
  <div class="sheet-panel" id="sheetPanel" role="dialog" aria-label="答题卡">
    <div class="sheet-head">
      <div>
        <div class="sheet-title">答题卡</div>
        <div class="sheet-sub" id="sheetSummary"></div>
      </div>
      <button class="sheet-close" onclick="window.closeSheet()" aria-label="关闭答题卡">✕</button>
    </div>
    <div class="sheet-legend" id="sheetLegend">
      <span class="lg lg-unanswered"><span class="dot d-unanswered"></span>未答</span>
      <span class="lg lg-answered"><span class="dot d-answered"></span>已答</span>
      <span class="lg lg-correct"><span class="dot d-correct"></span><span id="lgCorrect">正确</span></span>
      <span class="lg lg-wrong"><span class="dot d-wrong"></span><span id="lgWrong">错误</span></span>
      <span class="lg lg-flag"><span class="dot d-flag"></span>⭐ 收藏</span>
    </div>
    <div class="sheet-grid" id="sheetGrid"></div>
  </div>

  <div class="page" id="page-complete">
    <div class="complete-page">
      <div class="big-icon">🎉</div>
      <h2 id="completeTitle">恭喜完成！</h2>
      <p id="completeDesc" style="color:var(--text-secondary);font-size:14px;"></p>
      <div class="stats-grid" id="statsGrid"></div>
      <div class="btn-row" style="justify-content:center;flex-wrap:wrap;">
        <button class="btn btn-secondary" id="btnRetryWrong" style="display:none;" onclick="window.retryRoundWrong()">🔁 重练本轮错题</button>
        <button class="btn btn-primary" onclick="window.showPage('page-home')">返回首页</button>
      </div>
    </div>
  </div>

  <div class="page" id="page-fav">
    <div class="back-row"><button class="btn btn-outline" onclick="window.showPage('page-home')">← 返回首页</button></div>
    <h2 style="font-size:22px;color:var(--accent-dark);">⭐ 我的收藏</h2>
    <p style="font-size:14px;color:var(--text-secondary);margin:6px 0 16px;" id="favSummary"></p>
    <div class="fav-list" id="favList"></div>
  </div>

</div>

<div class="toast-mini" id="toastMini"></div>

<div class="modal-overlay" id="modalStartup">
  <div class="modal" style="text-align:center;">
    <h2>__TITLE__</h2>
    <p style="font-size:14px;color:var(--text-secondary);margin:12px 0;">欢迎来到刷题库！页面将在倒计时后自动进入。</p>
    <p style="font-size:12px;color:var(--text-light);margin-top:16px;padding-top:12px;border-top:1px solid var(--border-light);">题库与刷题网站均由AI生成，或有错误，请注意辨别。</p>
    <div class="countdown" id="countdown">5</div>
    <button class="btn btn-primary" id="btnEnter" onclick="window.closeStartupModal()" disabled>请等待 5 秒</button>
  </div>
</div>

<div class="modal-overlay" id="modalHelp">
  <div class="modal">
    <h2>💡 使用说明</h2>
    <div id="helpContent"></div>
    <div class="btn-row"><button class="btn btn-primary" onclick="window.closeHelp()">知道了</button></div>
  </div>
</div>

<div class="modal-overlay" id="modalResume">
  <div class="modal">
    <h2>📂 发现未完成的进度</h2>
    <p id="resumeText" style="margin:12px 0;"></p>
    <div class="btn-row">
      <button class="btn btn-outline" onclick="window.dismissResume()">重新开始</button>
      <button class="btn btn-primary" onclick="window.acceptResume()">继续上次的进度</button>
    </div>
  </div>
</div>

<div class="modal-overlay" id="modalTagSelect">
  <div class="modal modal-wide">
    <h2>🏷️ 知识点专项</h2>
    <p style="margin:8px 0 16px;font-size:14px;">请选择要练习的知识点（可多选，至少选一个）：<span class="picked-count" id="tagPickedCount">已选 0 个</span></p>
    <div class="tag-tree" id="modalTagTree"></div>
    <div class="btn-row" style="margin-top:20px;padding-top:16px;border-top:1px solid var(--border-light);">
      <button class="btn btn-outline" onclick="window.cancelTagSelection()">取消</button>
      <button class="btn btn-primary" id="btnTagConfirm" onclick="window.confirmTagSelection()" disabled>开始练习</button>
    </div>
  </div>
</div>

<div class="modal-overlay" id="modalSmart">
  <div class="modal">
    <h2>🎲 智能抽题</h2>
    <p style="font-size:13px;color:var(--text-secondary);margin-bottom:12px;">根据你已有的作答数据，优先抽取薄弱知识点；数据不足时以随机为主。</p>
    <div id="smartSummary" style="font-size:14px;line-height:1.8;"></div>
    <div id="smartExcludeWrap" style="margin-top:12px;"></div>
    <div class="btn-row" style="margin-top:20px;padding-top:16px;border-top:1px solid var(--border-light);flex-wrap:wrap;">
      <button class="btn btn-outline" onclick="window.resetSmartStats()">重置统计</button>
      <button class="btn btn-outline" onclick="window.startPureRandom()">改用纯随机</button>
      <button class="btn btn-primary" onclick="window.confirmSmartStart()">开始智能练习</button>
    </div>
  </div>
</div>

<div class="modal-overlay" id="modalRandomDone">
  <div class="modal" style="text-align:center;">
    <h2>🎉 所有题目已完成</h2>
    <p style="font-size:14px;color:var(--text-secondary);margin:12px 0;">随机模式下暂无可抽的题目。你可以重置随机模式的完成记录，重新开始一轮。</p>
    <div class="btn-row" style="justify-content:center;">
      <button class="btn btn-outline" onclick="window.closeModal('modalRandomDone'); window.showPage('page-home');">返回首页</button>
      <button class="btn btn-primary" onclick="window.resetRandomProgress()">重置并重新开始</button>
    </div>
  </div>
</div>

<div class="modal-overlay" id="modalExamUnanswered">
  <div class="modal">
    <h2>📋 还有题目未作答</h2>
    <p id="examUnansweredText" style="font-size:14px;color:var(--text-secondary);margin:12px 0;line-height:1.8;"></p>
    <div class="btn-row">
      <button class="btn btn-outline" onclick="window.closeModal('modalExamUnanswered')">继续检查</button>
      <button class="btn btn-primary" onclick="window.goToUnanswered()">去答题</button>
    </div>
  </div>
</div>

<div class="modal-overlay" id="modalExamConfirm">
  <div class="modal" style="text-align:center;">
    <h2>✅ 确认交卷？</h2>
    <p id="examConfirmText" style="font-size:14px;color:var(--text-secondary);margin:12px 0;"></p>
    <p style="font-size:13px;color:var(--text-light);">交卷后不可修改答案，并进入复盘阶段。</p>
    <div class="btn-row" style="justify-content:center;">
      <button class="btn btn-outline" onclick="window.closeModal('modalExamConfirm')">再检查一下</button>
      <button class="btn btn-primary" onclick="window.finalizeExam()">确认交卷</button>
    </div>
  </div>
</div>

<div class="modal-overlay" id="modalExamResult">
  <div class="modal" style="text-align:center;">
    <h2>🎉 考试完成</h2>
    <div class="stats-grid" id="examResultStats" style="margin:18px 0;"></div>
    <div class="btn-row" style="justify-content:center;">
      <button class="btn btn-outline" onclick="window.goHomeAfterExam()">返回首页</button>
      <button class="btn btn-primary" onclick="window.reviewFromResult()">查看复盘</button>
    </div>
  </div>
</div>

<div class="modal-overlay" id="modalExamQuit">
  <div class="modal" style="text-align:center;">
    <h2>⚠️ 退出考试？</h2>
    <p style="font-size:14px;color:var(--text-secondary);margin:12px 0;">退出将放弃本次考试，不记录成绩，也不计入统计与错题池。</p>
    <div class="btn-row" style="justify-content:center;">
      <button class="btn btn-outline" onclick="window.closeModal('modalExamQuit')">继续考试</button>
      <button class="btn btn-primary" onclick="window.discardExam()">确认退出</button>
    </div>
  </div>
</div>

<div class="footer"><span>__TITLE__</span> · 版本 <span id="versionDisplay">__VERSION_HASH__</span> · <span id="footerTime"></span></div>

__KATEX_JS__
<script>var KATEX_ENABLED = __KATEX_FLAG__;</script>
<script>
(function() {
  // ============================================================
  // 配置注入
  // ============================================================
  const STORAGE_PREFIX = '__STORAGE_PREFIX__';
  const VERSION_HASH = '__VERSION_HASH__';
  const ENABLED_MODES = '__ENABLED_MODES__';
const allQuestions = __QUESTIONS_JSON__;
const sectionMap = __SECTIONS_JSON__;
const allTags = __TAGS_JSON__;
// 判断题术语按题库语体显示（构建时注入）；判分与存储一律用简体值
const JUDGE_TRUE_LABEL = '__JUDGE_TRUE__';
const JUDGE_FALSE_LABEL = '__JUDGE_FALSE__';

  // ============================================================
  // 工具函数
  // ============================================================
  function esc(str) {
    var d = document.createElement('div');
    d.textContent = str;
    return d.innerHTML;
  }

  // ============================================================
  // 富文本渲染（Markdown 子集 + 可选 KaTeX）
  // 安全策略：先把代码/公式抽成占位符，再整体转义，最后拼接受控标签
  // ============================================================
  var KATEX_ON = (typeof KATEX_ENABLED !== 'undefined') && KATEX_ENABLED === true
                 && (typeof katex !== 'undefined');
  var MD_SLOT_A = '\uE000', MD_SLOT_B = '\uE001';

  function texHTML(tex, display) {
    var raw = (display ? '$$' : '$') + tex + (display ? '$$' : '$');
    if (!KATEX_ON) return esc(raw);
    try {
      return katex.renderToString(tex, {
        displayMode: !!display, throwOnError: false, output: 'html', strict: false
      });
    } catch (e) {
      return esc(raw);
    }
  }

  function mdInline(raw) {
    var stash = [];
    function hold(html) { stash.push(html); return MD_SLOT_A + (stash.length - 1) + MD_SLOT_B; }
    var s = String(raw == null ? '' : raw);

    // 行内代码优先，其内部不再解析公式与强调
    s = s.replace(/`([^`\n]+)`/g, function(m, p1) {
      return hold('<code class="md-inline-code">' + esc(p1) + '</code>');
    });
    // 块级公式与行内公式
    s = s.replace(/\$\$([\s\S]+?)\$\$/g, function(m, p1) { return hold(texHTML(p1, true)); });
    s = s.replace(/\$([^$\n]+?)\$/g, function(m, p1) { return hold(texHTML(p1, false)); });

    // 整体转义（占位符位于私有区，不受影响）
    s = esc(s);

    // 强调与上下标；不支持单星号/下划线斜体，避免误伤语言学的 *构拟形式 与 _词素边界_
    s = s.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>');
    s = s.replace(/~([^~\s]+)~/g, '<sub>$1</sub>');
    s = s.replace(/\^([^\^\s]+)\^/g, '<sup>$1</sup>');

    s = s.replace(new RegExp(MD_SLOT_A + '(\\d+)' + MD_SLOT_B, 'g'), function(m, i) {
      return stash[Number(i)];
    });
    return s;
  }

  function splitTableRow(line) {
    return line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map(function(c) { return c.trim(); });
  }

  function mdBlock(raw) {
    var text = String(raw == null ? '' : raw).replace(/\r\n?/g, '\n');
    if (!text.trim()) return '';
    var lines = text.split('\n');
    var out = [], para = [], i = 0;

    function flushPara() {
      if (!para.length) return;
      out.push('<p>' + para.map(mdInline).join('<br>') + '</p>');
      para = [];
    }

    while (i < lines.length) {
      var line = lines[i];

      // 代码块 ``` ... ```
      if (/^\s*```/.test(line)) {
        i++;
        var code = [];
        while (i < lines.length && !/^\s*```/.test(lines[i])) { code.push(lines[i]); i++; }
        if (i < lines.length) i++;
        out.push('<pre class="md-code"><code>' + esc(code.join('\n')) + '</code></pre>');
        continue;
      }

      // 表格：表头行 + 分隔行
      if (/^\s*\|.*\|\s*$/.test(line) && i + 1 < lines.length
          && /^\s*\|[\s:|-]+\|\s*$/.test(lines[i + 1]) && /-/.test(lines[i + 1])) {
        flushPara();
        var head = splitTableRow(line);
        i += 2;
        var body = [];
        while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) { body.push(splitTableRow(lines[i])); i++; }
        var html = '<table class="md-table"><thead><tr>';
        head.forEach(function(c) { html += '<th>' + mdInline(c) + '</th>'; });
        html += '</tr></thead><tbody>';
        body.forEach(function(r) {
          html += '<tr>';
          for (var k = 0; k < head.length; k++) html += '<td>' + mdInline(r[k] == null ? '' : r[k]) + '</td>';
          html += '</tr>';
        });
        html += '</tbody></table>';
        out.push(html);
        continue;
      }

      // 引用块
      if (/^\s*>\s?/.test(line)) {
        flushPara();
        var quote = [];
        while (i < lines.length && /^\s*>\s?/.test(lines[i])) {
          quote.push(lines[i].replace(/^\s*>\s?/, '')); i++;
        }
        out.push('<blockquote class="md-blockquote">' + quote.map(mdInline).join('<br>') + '</blockquote>');
        continue;
      }

      // 列表
      if (/^\s*(?:[-*+]|\d+\.)\s+/.test(line)) {
        flushPara();
        var ordered = /^\s*\d+\.\s+/.test(line);
        var items = [];
        while (i < lines.length && /^\s*(?:[-*+]|\d+\.)\s+/.test(lines[i])) {
          items.push(lines[i].replace(/^\s*(?:[-*+]|\d+\.)\s+/, '')); i++;
        }
        var tag = ordered ? 'ol' : 'ul';
        out.push('<' + tag + ' class="md-list">' + items.map(function(t) {
          return '<li>' + mdInline(t) + '</li>';
        }).join('') + '</' + tag + '>');
        continue;
      }

      // 空行 → 段落分隔
      if (!line.trim()) { flushPara(); i++; continue; }

      para.push(line);
      i++;
    }
    flushPara();
    return out.join('');
  }

  function shuffle(arr) {
    for (var i = arr.length - 1; i > 0; i--) {
      var j = Math.floor(Math.random() * (i + 1));
      var tmp = arr[i]; arr[i] = arr[j]; arr[j] = tmp;
    }
    return arr;
  }

  function loadStore(key, fallback) {
    try {
      var raw = localStorage.getItem(STORAGE_PREFIX + key);
      return raw ? JSON.parse(raw) : fallback;
    } catch (e) { return fallback; }
  }
  function saveStore(key, val) {
    try {
      localStorage.setItem(STORAGE_PREFIX + key, JSON.stringify(val));
      return true;
    } catch (e) {
      if (!saveStoreWarned) {
        saveStoreWarned = true;
        console.warn('[QuizComplete] 本地存储写入失败：', e);
        showToast('本地存储不可用或已满，进度可能无法保存');
      }
      return false;
    }
  }

  // ============================================================
  // 音效
  // ============================================================
  var audioCtx = null;
  function getAudioCtx() {
    if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    return audioCtx;
  }
  function playClick() {
    try {
      var ctx = getAudioCtx();
      var osc = ctx.createOscillator(), gain = ctx.createGain();
      osc.connect(gain); gain.connect(ctx.destination);
      osc.frequency.value = 880; osc.type = 'sine';
      gain.gain.setValueAtTime(0.15, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.06);
      osc.start(ctx.currentTime); osc.stop(ctx.currentTime + 0.06);
    } catch(e) {}
  }
  function playCorrect() {
    try {
      var ctx = getAudioCtx();
      [660, 880].forEach(function(f, i) {
        var osc = ctx.createOscillator(), gain = ctx.createGain();
        osc.connect(gain); gain.connect(ctx.destination);
        osc.frequency.value = f; osc.type = 'sine';
        gain.gain.setValueAtTime(0.12, ctx.currentTime + i * 0.1);
        gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.25);
        osc.start(ctx.currentTime + i * 0.1); osc.stop(ctx.currentTime + 0.25);
      });
    } catch(e) {}
  }
  function playWrong() {
    try {
      var ctx = getAudioCtx();
      var osc = ctx.createOscillator(), gain = ctx.createGain();
      osc.connect(gain); gain.connect(ctx.destination);
      osc.frequency.value = 200; osc.type = 'sawtooth';
      gain.gain.setValueAtTime(0.1, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.3);
      osc.start(ctx.currentTime); osc.stop(ctx.currentTime + 0.3);
    } catch(e) {}
  }

  // ============================================================
  // 状态
  // ============================================================
  var currentMode = null;
  var currentIdx = 0;
  var isSubmitted = false;
  var isTransitioning = false;  // 题目切换动效中
  var streak = 0;
  var questionQueue = [];
  var correctCount = 0;
  var totalCount = 0;
  var currentTags = [];
  var currentSection = null;
  var answerLog = {};        // id -> { selected, correct, ts, attempts }
  var flaggedIds = [];       // 收藏题目 id 列表
  var toastTimer = null;
  var smartRandom = false;   // 随机模式：智能优先开关
  var statsResetAt = 0;      // 学习统计的重置时间戳
  var smartExcludeTags = []; // 本轮排除的知识点标签
  var skipSmartPanel = false;// 防止抽题面板重复弹出
  var forcePureRandom = false; // 本次强制纯随机
  var examActive = false;      // 考试进行中（尚未交卷）
  var examSubmitted = false;   // 考试已交卷（复盘阶段）
  var examSelections = {};     // 考试中已选答案：qid -> selected
  var examStartTime = 0;       // 考试开始时间戳
  var examElapsedSec = 0;      // 交卷后的总用时
  var examTimerId = null;      // 计时器句柄
  var roundLog = {};           // 本轮作答记录：qid -> { selected, correct }
  var saveStoreWarned = false; // 存储写入失败只提示一次

  // ============================================================
  // 模式定义
  // ============================================================
  var MODE_DEFS = {
    topic: { label: '专题模式', icon: '📖', desc: '按板块顺序刷题，退出保存进度', needSection: true, needTag: false },
    random: { label: '随机模式', icon: '🎲', desc: '从总题库随机抽题，永不重复', needSection: false, needTag: false },
    career: { label: '生涯模式', icon: '🎯', desc: '答对移除，答错入池，通关存档', needSection: false, needTag: false },
    wrong: { label: '错题专项', icon: '📝', desc: '只显示做错的题，全对后清空', needSection: false, needTag: false },
    tag: { label: '知识点专项', icon: '🏷️', desc: '按知识点标签选择范围后刷题', needSection: false, needTag: true },
    exam: { label: '考试模拟', icon: '📋', desc: '可自定义题数，答完显示分数', needSection: false, needTag: false }
  };
  var enabledModes = ENABLED_MODES.split(',');

  // ============================================================
  // 版本检测
  // ============================================================
  (function() {
    var oldVer = localStorage.getItem(STORAGE_PREFIX + 'version');
    if (oldVer && oldVer !== VERSION_HASH) {
      document.getElementById('versionTip').classList.add('show');
    }
    localStorage.setItem(STORAGE_PREFIX + 'version', VERSION_HASH);
    document.getElementById('versionDisplay').textContent = VERSION_HASH;
  })();

  // ============================================================
  // 渲染首页
  // ============================================================
  function renderHome() {
    var grid = document.getElementById('modeGrid');
    grid.innerHTML = '';
    enabledModes.forEach(function(id) {
      var m = MODE_DEFS[id];
      if (!m) return;
      var card = document.createElement('div');
      card.className = 'mode-card';
      card.innerHTML = '<span class="icon">' + m.icon + '</span><div class="name">' + m.label + '</div><div class="desc">' + m.desc + '</div>';
      var badge = modeBadge(id);
      if (badge) {
        var bEl = document.createElement('span');
        bEl.className = 'mode-badge' + (badge.zero ? ' zero' : '');
        bEl.textContent = badge.text;
        card.appendChild(bEl);
      }
      card.onclick = function() { playClick(); enterMode(id); };
      if (id === 'random') {
        var sw = document.createElement('div');
        sw.className = 'smart-switch';
        sw.innerHTML = '<span class="sw-label">智能优先</span><span class="sw-state' + (smartRandom ? ' on' : '') + '">' + (smartRandom ? '开' : '关') + '</span>';
        sw.onclick = function(ev) {
          ev.stopPropagation();
          smartRandom = !smartRandom;
          saveStore('smart_random', smartRandom);
          renderHome();
          showToast(smartRandom ? '已开启智能优先' : '已关闭智能优先');
        };
        card.appendChild(sw);
      }
      grid.appendChild(card);
    });
    var favEntry = document.getElementById('favEntry');
    var favCountEl = document.getElementById('favEntryCount');
    if (favCountEl) favCountEl.textContent = flaggedIds.length;
    if (favEntry) favEntry.title = flaggedIds.length ? ('我的收藏：' + flaggedIds.length + ' 题') : '我的收藏（暂无）';
    renderHomeSummary();
  }

  // 模式卡片右上角徽标：让首页一眼看出各模式的待办规模
  function modeBadge(id) {
    if (id === 'wrong') {
      var n = loadStore('wrong_set', []).length;
      return { text: n ? n + ' 题' : '已清空', zero: n === 0 };
    }
    if (id === 'career') {
      var leftC = Math.max(0, allQuestions.length - loadStore('career_done', []).length);
      return { text: '剩余 ' + leftC + ' 题', zero: leftC === 0 };
    }
    if (id === 'random') {
      var leftR = Math.max(0, allQuestions.length - loadStore('random_done', []).length);
      return { text: '剩余 ' + leftR + ' 题', zero: leftR === 0 };
    }
    if (id === 'topic') return { text: Object.keys(sectionMap).length + ' 个板块', zero: false };
    if (id === 'tag') return { text: allTags.length + ' 个标签', zero: false };
    return null;
  }

  // 首页学习概览（统计口径：所有模式累计，每道题取最近一次作答）
  function renderHomeSummary() {
    var el = document.getElementById('homeSummary');
    if (!el) return;
    var done = 0, right = 0;
    Object.keys(answerLog).forEach(function(k) {
      var r = answerLog[k];
      if (!r) return;
      done++;
      if (r.correct) right++;
    });
    var acc = done ? Math.round(right / done * 100) : 0;
    el.innerHTML =
      '<span>已练 <b>' + done + '</b> / ' + allQuestions.length + ' 题</span>' +
      '<span>正确率 <b>' + acc + '%</b></span>' +
      '<span>错题 <b>' + loadStore('wrong_set', []).length + '</b> 题</span>';
  }

  // ============================================================
  // 进入模式
  // ============================================================
  function enterMode(modeId) {
    playClick();
    currentMode = modeId;
    var m = MODE_DEFS[modeId];
    if (m.needSection) { renderSections(); showPage('page-section'); return; }
    if (m.needTag) { showTagModal(); return; }
    startQuiz(modeId);
  }

  function renderSections() {
    var list = document.getElementById('sectionList');
    list.innerHTML = '';
    Object.keys(sectionMap).sort(function(a, b) { return a.localeCompare(b, 'zh-CN'); }).forEach(function(section) {
      var indices = sectionMap[section];
      var item = document.createElement('div');
      item.className = 'section-item';
      item.innerHTML = '<span class="sec-name">' + esc(section) + '</span><span class="sec-count">共 ' + indices.length + ' 题</span>';
      item.onclick = function() { playClick(); currentSection = section; startQuiz('topic', section); };
      list.appendChild(item);
    });
  }

  // ============================================================
  // 知识点专项：按章节分组的树状选择面板
  // ============================================================
  var tagTreeGroups = [];   // [{ section, tags, allBtn, items }]
  var tagTreeOpen = {};     // 章节展开状态（按章节名记录，跨次打开保留）

  function updateTagPickedCount() {
    var el = document.getElementById('tagPickedCount');
    if (el) el.textContent = '已选 ' + currentTags.length + ' 个';
    var btn = document.getElementById('btnTagConfirm');
    if (btn) btn.disabled = (currentTags.length === 0);
  }

  function syncTagGroupButtons() {
    tagTreeGroups.forEach(function(g) {
      var all = g.tags.every(function(t) { return currentTags.indexOf(t) !== -1; });
      g.allBtn.textContent = all ? '取消全选' : '全选';
      g.allBtn.classList.toggle('on', all);
    });
  }

  function toggleTagPick(tag, el) {
    var i = currentTags.indexOf(tag);
    if (i === -1) currentTags.push(tag); else currentTags.splice(i, 1);
    if (el) el.classList.toggle('checked', currentTags.indexOf(tag) !== -1);
    syncTagGroupButtons();
    updateTagPickedCount();
  }

  function toggleTagGroup(section) {
    var g = null;
    tagTreeGroups.forEach(function(x) { if (x.section === section) g = x; });
    if (!g) return;
    var allPicked = g.tags.every(function(t) { return currentTags.indexOf(t) !== -1; });
    g.tags.forEach(function(t) {
      var i = currentTags.indexOf(t);
      if (allPicked) { if (i !== -1) currentTags.splice(i, 1); }
      else if (i === -1) { currentTags.push(t); }
    });
    g.items.forEach(function(it) {
      it.el.classList.toggle('checked', currentTags.indexOf(it.tag) !== -1);
    });
    syncTagGroupButtons();
    updateTagPickedCount();
  }

  function renderTagTree() {
    var wrap = document.getElementById('modalTagTree');
    if (!wrap) return;
    wrap.innerHTML = '';
    wrap.scrollTop = 0;
    tagTreeGroups = [];
    // 按 sectionMap 的键顺序分组（即构建时的文件顺序），保证章节顺序稳定
    Object.keys(sectionMap).forEach(function(section) {
      var tags = [];
      (sectionMap[section] || []).forEach(function(idx) {
        var q = allQuestions[idx];
        if (q && q.tag && tags.indexOf(q.tag) === -1) tags.push(q.tag);
      });
      if (!tags.length) return;

      var group = document.createElement('div');
      group.className = 'tree-group' + (tagTreeOpen[section] ? ' open' : '');

      var head = document.createElement('div');
      head.className = 'group-head';
      var caret = document.createElement('span');
      caret.className = 'caret'; caret.textContent = '▶';
      var nameEl = document.createElement('span');
      nameEl.className = 'group-name'; nameEl.textContent = section;
      var countEl = document.createElement('span');
      countEl.className = 'group-count'; countEl.textContent = tags.length + ' 个知识点';
      var allBtn = document.createElement('button');
      allBtn.type = 'button'; allBtn.className = 'group-all'; allBtn.textContent = '全选';
      allBtn.onclick = function(ev) { ev.stopPropagation(); playClick(); toggleTagGroup(section); };
      head.appendChild(caret); head.appendChild(nameEl); head.appendChild(countEl); head.appendChild(allBtn);
      head.onclick = function() {
        playClick();
        tagTreeOpen[section] = !tagTreeOpen[section];
        group.classList.toggle('open', !!tagTreeOpen[section]);
      };

      var body = document.createElement('div');
      body.className = 'group-body';
      var items = [];
      tags.forEach(function(tag) {
        var item = document.createElement('span');
        item.className = 'tag-item' + (currentTags.indexOf(tag) !== -1 ? ' checked' : '');
        var tick = document.createElement('span');
        tick.className = 'tick'; tick.textContent = '✓';
        var txt = document.createElement('span');
        txt.textContent = tag;
        item.appendChild(tick); item.appendChild(txt);
        item.onclick = function() { playClick(); toggleTagPick(tag, item); };
        body.appendChild(item);
        items.push({ tag: tag, el: item });
      });

      group.appendChild(head);
      group.appendChild(body);
      wrap.appendChild(group);
      tagTreeGroups.push({ section: section, tags: tags, allBtn: allBtn, items: items });
    });
    syncTagGroupButtons();
  }

  function showTagModal() {
    currentTags = [];
    tagTreeOpen = {};
    renderTagTree();
    updateTagPickedCount();
    showModal('modalTagSelect');
  }

  // ============================================================
  // 开始答题
  // ============================================================
  function startQuiz(modeId, section) {
    playClick();
    var useSmart = (modeId === 'random' && smartRandom && !forcePureRandom);
    forcePureRandom = false;
    if (modeId === 'random' && smartRandom && !skipSmartPanel) { showSmartPanel(); return; }
    skipSmartPanel = false;
    var pool = [];
    if (modeId === 'topic' && section) {
      var indices = sectionMap[section] || [];
      pool = indices.map(function(i) { return allQuestions[i]; });
      currentSection = section;
    } else if (modeId === 'tag' && currentTags.length) {
      pool = allQuestions.filter(function(q) { return currentTags.indexOf(q.tag) !== -1; });
    } else if (modeId === 'career') {
      var done = loadStore('career_done', []);
      var wrongIds = loadStore('career_wrong', []);
      // 先放未答过的题，再将错题追加到末尾（错题只出现一次）
      pool = allQuestions.filter(function(q) { return done.indexOf(q.id) === -1 && wrongIds.indexOf(q.id) === -1; });
      pool = pool.concat(wrongIds.map(function(id) {
        return allQuestions.find(function(q) { return q.id === id; });
      }).filter(Boolean));
    } else if (modeId === 'wrong') {
      var wrongIds = loadStore('wrong_set', []);
      pool = allQuestions.filter(function(q) { return wrongIds.indexOf(q.id) !== -1; });
      if (pool.length === 0) { alert('🎉 错题池为空！'); showPage('page-home'); return; }
    } else if (modeId === 'exam') {
      // 考试模拟：让用户自定义题数，随机抽题
      var totalAvailable = allQuestions.length;
      var input = prompt('请输入本次考试的题目数量（1~' + totalAvailable + '）：', '25');
      var num = parseInt(input, 10);
      if (isNaN(num) || num < 1) { showPage('page-home'); return; }
      if (num > totalAvailable) num = totalAvailable;
      pool = shuffle(allQuestions.slice()).slice(0, num);
    } else {
      var doneRandom = loadStore('random_done', []);
      pool = allQuestions.filter(function(q) { return doneRandom.indexOf(q.id) === -1; });
      if (useSmart) { pool = smartOrder(pool.slice(), smartExcludeTags); smartExcludeTags = []; }
    }
    if (pool.length === 0) {
      if (modeId === 'random') { showPage('page-home'); showModal('modalRandomDone'); return; }
      alert('🎉 所有题目已完成！'); showPage('page-home'); return;
    }
    if (modeId === 'random' && !useSmart) pool = shuffle(pool.slice());

    questionQueue = pool; currentIdx = 0; correctCount = 0; totalCount = pool.length; streak = 0;
    roundLog = {};
    if (modeId === 'exam') {
      examActive = true; examSubmitted = false; examSelections = {}; examElapsedSec = 0;
      startExamTimer();
    } else {
      examActive = false; examSubmitted = false;
      stopExamTimer();
      var timerEl0 = document.getElementById('examTimer');
      if (timerEl0) timerEl0.style.display = 'none';
    }

    if (modeId === 'topic' && section) {
      var saved = loadStore('topic_' + section, null);
      if (saved && saved.id) {
        var savedIdx = pool.findIndex(function(qi) { return qi.id === saved.id; });
        if (savedIdx >= 0) { showResumeModal(savedIdx + 1, section); return; }
      }
    }
    showPage('page-quiz'); renderQuestion();
  }

  // ============================================================
  // 渲染题目
  // ============================================================
  // 选项渲染：把开头的 "A." 抽成独立字母模块，正文单独一栏，实现多行悬挂对齐
  function renderOptionBody(item, opt) {
    var text = String(opt == null ? '' : opt);
    var m = text.match(/^\s*([A-E])\s*[.、）)]\s*([\s\S]*)$/);
    item.dataset.value = m ? m[1] : text.charAt(0);
    var body = document.createElement('span');
    body.className = 'opt-body';
    body.innerHTML = mdInline(m ? m[2] : text);
    if (m) {
      var lab = document.createElement('span');
      lab.className = 'opt-label';
      lab.textContent = m[1];
      item.appendChild(lab);
    }
    item.appendChild(body);
  }

  function renderQuestion() {
    isSubmitted = false;
    var q = questionQueue[currentIdx];
    if (!q) return;

    document.getElementById('qNumber').textContent = '第 ' + (currentIdx + 1) + ' 题（共 ' + totalCount + ' 题）';
    document.getElementById('qSection').textContent = q.file;
    document.getElementById('qText').innerHTML = mdBlock(q.question);
    var typeMap = { single: '单选题', multiple: '不定项选择题', judge: '判断题' };
    var typeEl = document.getElementById('qType');
    typeEl.textContent = typeMap[q.type] || q.type;
    typeEl.className = 'q-type ' + q.type;
    document.getElementById('progressBar').style.width = ((currentIdx) / totalCount * 100) + '%';
    updateProgressDots(((currentIdx) / totalCount * 100));
    document.getElementById('progressText').textContent = (currentIdx) + ' / ' + totalCount;

    if (streak >= 3) {
      var badge = document.getElementById('streakBadge');
      badge.textContent = '🔥 连对 ' + streak + ' 题'; badge.className = 'streak-badge show';
    } else {
      document.getElementById('streakBadge').className = 'streak-badge';
    }

    var container = document.getElementById('optionsContainer');
    container.innerHTML = '';
    document.getElementById('verdictArea').className = 'verdict-area hidden';
    document.getElementById('navRow').className = 'nav-row';
    document.getElementById('resultBoxes').innerHTML = '';
    document.getElementById('btnSubmit').style.display = '';
    document.getElementById('actionRow').style.display = '';

    if (q.type === 'single') {
      var div = document.createElement('div'); div.className = 'options';
      q.options.forEach(function(opt, idx) {
        var item = document.createElement('div');
        item.className = 'opt-item'; item.style.animationDelay = (idx * 0.05) + 's';
        renderOptionBody(item, opt);
        item.onclick = function() {
          if (isSubmitted) return; playClick();
          div.querySelectorAll('.opt-item').forEach(function(el) { el.classList.remove('selected'); });
          item.classList.add('selected');
          if (currentMode === 'exam' && examActive) recordExamSelection(q);
        };
        div.appendChild(item);
      });
      container.appendChild(div);
    } else if (q.type === 'multiple') {
      // 不定项选择：可切换选中/取消，多项可同时选中
      var div = document.createElement('div'); div.className = 'options';
      var hint = document.createElement('div');
      hint.style.cssText = 'font-size:12px;color:var(--text-light);margin-bottom:8px;';
      hint.textContent = '（可多选，点击选项切换选中状态）';
      div.appendChild(hint);
      q.options.forEach(function(opt, idx) {
        var item = document.createElement('div');
        item.className = 'opt-item'; item.style.animationDelay = (idx * 0.05) + 's';
        renderOptionBody(item, opt);
        item.onclick = function() {
          if (isSubmitted) return; playClick();
          item.classList.toggle('selected');
          if (currentMode === 'exam' && examActive) recordExamSelection(q);
        };
        div.appendChild(item);
      });
      container.appendChild(div);
    } else {
      var jdiv = document.createElement('div'); jdiv.className = 'judge-options';
      // dataset.value 固定用简体（与解析后的答案比对），显示文字按题库语体
      [[JUDGE_TRUE_LABEL, '正确'], [JUDGE_FALSE_LABEL, '错误']].forEach(function(pair) {
        var btn = document.createElement('div');
        btn.className = 'judge-btn'; btn.textContent = pair[0]; btn.dataset.value = pair[1];
        btn.onclick = function() {
          if (isSubmitted) return; playClick();
          jdiv.querySelectorAll('.judge-btn').forEach(function(el) { el.classList.remove('selected'); });
          btn.classList.add('selected');
          if (currentMode === 'exam' && examActive) recordExamSelection(q);
        };
        jdiv.appendChild(btn);
      });
      container.appendChild(jdiv);
    }

    // 导航按钮还原默认行为
    var btnPrevEl = document.getElementById('btnPrev');
    var btnNextEl = document.getElementById('btnNext');
    btnPrevEl.style.display = '';
    btnNextEl.textContent = '下一题 →';
    btnNextEl.setAttribute('onclick', 'window.nextQuestion()');
    var backBtnEl = document.getElementById('btnBack');
    if (backBtnEl) { backBtnEl.textContent = '← 返回'; backBtnEl.setAttribute('onclick', 'window.exitQuiz()'); }
    var btnReturnEl = document.getElementById('btnReturn');
    if (btnReturnEl) btnReturnEl.style.display = 'none';

    var isFavReview = (currentMode === 'fav');
    var rec = ((currentMode === 'exam') || isFavReview) ? answerLog[q.id] : roundLog[q.id];
    var examPhase = (currentMode === 'exam');
    var examNeutral = examPhase && examActive && !examSubmitted;
    document.getElementById('btnExamSubmit').style.display = examNeutral ? '' : 'none';
    var timerEl = document.getElementById('examTimer');
    if (timerEl) timerEl.style.display = examPhase ? '' : 'none';
    if (examPhase) document.getElementById('streakBadge').className = 'streak-badge';

    if (examNeutral) {
      isSubmitted = false;
      document.getElementById('btnSubmit').style.display = 'none';
      document.getElementById('navRow').className = 'nav-row show';
      if (examSelections[q.id]) preselectByValue(q, examSelections[q.id]);
      updateExamTimerDisplay();
    } else if (rec) {
      // 已作答（本轮作答 / 考试复盘 / 收藏回看）一律只读，任何导航路径都不可重新作答
      applyReviewState(q, rec);
    } else if (isFavReview) {
      isSubmitted = true;
      document.getElementById('btnSubmit').style.display = 'none';
      document.getElementById('navRow').className = 'nav-row show';
      showToast('该题尚未作答，暂无可回看内容');
    } else {
      document.getElementById('btnSubmit').style.display = '';
    }
    updateFlagButton();
    updateSheetProgress();
    window.scrollTo(0, 0);
  }

  function preselectByValue(q, selected) {
    if (!selected) return;
    var vals = String(selected).split(' · ');
    document.querySelectorAll('.opt-item, .judge-btn').forEach(function(el) {
      if (vals.indexOf(el.dataset.value) !== -1) el.classList.add('selected');
    });
  }
  function preselectAnswer(q, rec) { if (rec && rec.selected) preselectByValue(q, rec.selected); }

  function applyReviewState(q, rec) {
    isSubmitted = true;
    preselectAnswer(q, rec);
    markOptions(q, rec.selected, rec.correct);
    renderVerdict(q, rec.selected, rec.correct);
    document.getElementById('btnSubmit').style.display = 'none';
    document.getElementById('navRow').className = 'nav-row show';
    var btnPrev = document.getElementById('btnPrev');
    var btnNext = document.getElementById('btnNext');
    btnPrev.style.display = '';
    btnNext.textContent = '下一题 →';
    btnNext.setAttribute('onclick', 'window.nextQuestion()');
    var btnReturn = document.getElementById('btnReturn');
    if (btnReturn) btnReturn.style.display = (currentMode === 'exam' || currentMode === 'fav') ? 'none' : '';
    if (currentMode === 'exam') {
      var backBtn = document.getElementById('btnBack');
      if (backBtn) { backBtn.textContent = '← 返回结算'; backBtn.setAttribute('onclick', 'window.showExamResult()'); }
    }
  }

  // ============================================================
  // 提交答案
  // ============================================================
  function markOptions(q, selected, isCorrect) {
    if (q.type === 'single') {
      document.querySelectorAll('.opt-item').forEach(function(el) {
        el.classList.add('submitted');
        if (el.dataset.value === q.answer) el.classList.add('correct');
        if (el.dataset.value === selected && !isCorrect) el.classList.add('wrong');
      });
    } else if (q.type === 'multiple') {
      var correctAnswers = q.answer.split(' · ');
      document.querySelectorAll('.opt-item').forEach(function(el) {
        el.classList.add('submitted');
        if (correctAnswers.indexOf(el.dataset.value) !== -1) el.classList.add('correct');
        if (el.classList.contains('selected') && correctAnswers.indexOf(el.dataset.value) === -1) el.classList.add('wrong');
      });
    } else {
      document.querySelectorAll('.judge-btn').forEach(function(el) {
        el.classList.add('submitted');
        if (el.dataset.value === q.answer) el.classList.add('correct');
        if (el.dataset.value === selected && !isCorrect) el.classList.add('wrong');
      });
    }
  }

  function renderVerdict(q, selected, isCorrect) {
    var verdict = document.getElementById('verdictArea');
    verdict.className = 'verdict-area ' + (isCorrect ? 'correct' : 'wrong');
    document.getElementById('verdictBadge').textContent = isCorrect
      ? ('✅ 回答' + JUDGE_TRUE_LABEL + '！')
      : ('❌ 回答' + JUDGE_FALSE_LABEL + '！');

    var boxes = document.getElementById('resultBoxes'); boxes.innerHTML = '';
    var ansText = q.type === 'judge'
      ? (q.answer === '正确' ? JUDGE_TRUE_LABEL : JUDGE_FALSE_LABEL)
      : (JUDGE_TRUE_LABEL + '答案 ' + q.answer);
    var ansBox = document.createElement('div');
    ansBox.className = 'result-box answer-box';
    ansBox.innerHTML = '<span class="rb-label">📌 答案</span>' + esc(ansText);
    boxes.appendChild(ansBox);

    if (selected) {
      var myBox = document.createElement('div');
      myBox.className = 'result-box tag-box';
      var selText = (q.type === 'judge')
        ? (selected === '正确' ? JUDGE_TRUE_LABEL : JUDGE_FALSE_LABEL)
        : selected;
      myBox.innerHTML = '<span class="rb-label">✍️ 你的作答</span>' + esc(selText);
      boxes.appendChild(myBox);
    }
    if (q.explanation) {
      var explBox = document.createElement('div');
      explBox.className = 'result-box expl-box';
      explBox.innerHTML = '<span class="rb-label">📖 解析</span>' + mdBlock(q.explanation);
      boxes.appendChild(explBox);
    }
    if (q.tag) {
      var tagBox = document.createElement('div');
      tagBox.className = 'result-box tag-box';
      tagBox.innerHTML = '<span class="rb-label">🏷️</span> ' + mdInline(q.tag);
      boxes.appendChild(tagBox);
    }
    setTimeout(function() { verdict.scrollIntoView({ behavior: 'smooth', block: 'center' }); }, 100);
  }

  function submitAnswer() {
    if (isSubmitted) return;
    var q = questionQueue[currentIdx];
    var selected = null;

    if (q.type === 'single') {
      var sel = document.querySelector('.opt-item.selected');
      if (!sel) { alert('请选择一个选项'); return; }
      selected = sel.dataset.value;
    } else if (q.type === 'multiple') {
      var sels = document.querySelectorAll('.opt-item.selected');
      if (sels.length === 0) { alert('请至少选择一个选项'); return; }
      selected = Array.from(sels).map(function(el) { return el.dataset.value; }).sort().join(' · ');
    } else {
      var sel = document.querySelector('.judge-btn.selected');
      if (!sel) { alert('请选择一个答案'); return; }
      selected = sel.dataset.value;
    }

    isSubmitted = true; playClick();
    var isCorrect;
    if (q.type === 'multiple') {
      isCorrect = (selected === q.answer);
    } else {
      isCorrect = (selected === q.answer);
    }
    if (isCorrect) { streak++; correctCount++; playCorrect(); }
    else { streak = 0; playWrong(); }

    markOptions(q, selected, isCorrect);
    renderVerdict(q, selected, isCorrect);
    roundLog[q.id] = { selected: selected, correct: isCorrect };
    answerLog[q.id] = {
      selected: selected,
      correct: isCorrect,
      ts: Date.now(),
      attempts: answerLog[q.id] && answerLog[q.id].attempts ? answerLog[q.id].attempts + 1 : 1
    };
    saveStore('answers', answerLog);
    saveProgress(isCorrect, q);
    document.getElementById('btnSubmit').style.display = 'none';
    document.getElementById('navRow').className = 'nav-row show';
    updateFlagButton();
    updateSheetProgress();

    var pct = ((currentIdx + 1) / totalCount * 100);
    document.getElementById('progressBar').style.width = pct + '%';
    document.getElementById('progressText').textContent = (currentIdx + 1) + ' / ' + totalCount;
    updateProgressDots(pct);
  }

  function saveProgress(isCorrect, q) {
    if (currentMode === 'topic' && currentSection) {
      if (q) saveStore('topic_' + currentSection, { id: q.id });
    }
    if (currentMode === 'random') {
      var done = loadStore('random_done', []);
      if (done.indexOf(q.id) === -1) done.push(q.id);
      saveStore('random_done', done);
    }
    if (currentMode === 'career') {
      if (isCorrect) {
        var done = loadStore('career_done', []);
        if (done.indexOf(q.id) === -1) done.push(q.id);
        saveStore('career_done', done);
        var wrong = loadStore('career_wrong', []);
        var idx = wrong.indexOf(q.id); if (idx !== -1) wrong.splice(idx, 1);
        saveStore('career_wrong', wrong);
      } else {
        var wrong = loadStore('career_wrong', []);
        if (wrong.indexOf(q.id) === -1) wrong.push(q.id);
        saveStore('career_wrong', wrong);
      }
    }
    if (currentMode === 'tag' && currentTags.length) {
      var tagKey = 'tag_' + currentTags.slice().sort().join('|');
      var tagDone = loadStore(tagKey, []);
      if (tagDone.indexOf(q.id) === -1) tagDone.push(q.id);
      saveStore(tagKey, tagDone);
    }
    // 错题池（掌握制）：任何模式答错入池，任何模式答对出池；考试在交卷判分后同样走这里
    var wrongSet = loadStore('wrong_set', []);
    var wi = wrongSet.indexOf(q.id);
    if (isCorrect) {
      if (wi !== -1) wrongSet.splice(wi, 1);
    } else if (wi === -1) {
      wrongSet.push(q.id);
    }
    saveStore('wrong_set', wrongSet);
  }

  // ============================================================
  // 收藏与答题卡
  // ============================================================
  function isFlagged(id) { return flaggedIds.indexOf(id) !== -1; }

  function updateFlagButton() {
    var btn = document.getElementById('btnFlag');
    var q = questionQueue[currentIdx];
    if (!btn) return;
    if (!q) { btn.style.visibility = 'hidden'; return; }
    btn.style.visibility = '';
    var on = isFlagged(q.id);
    var starEl = btn.querySelector('.star');
    if (starEl) starEl.textContent = '⭐';
    btn.classList.toggle('on', on);
    btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    btn.title = on ? '取消收藏' : '收藏本题';
  }

  function toggleFlag() {
    var q = questionQueue[currentIdx];
    if (!q) return;
    var i = flaggedIds.indexOf(q.id);
    if (i === -1) { flaggedIds.push(q.id); showToast('已加入收藏'); }
    else { flaggedIds.splice(i, 1); showToast('已取消收藏'); }
    saveStore('flagged', flaggedIds);
    updateFlagButton();
    renderSheet();
    if (document.getElementById('page-home').classList.contains('active')) renderHome();
  }

  function removeFlag(id) {
    var i = flaggedIds.indexOf(id);
    if (i !== -1) { flaggedIds.splice(i, 1); saveStore('flagged', flaggedIds); }
    updateFlagButton();
  }

  function answeredCount() {
    var n = 0;
    questionQueue.forEach(function(q) {
      if (currentMode === 'exam') {
        if (examSubmitted ? answerLog[q.id] : examSelections[q.id]) n++;
      } else if (currentMode === 'fav') {
        if (answerLog[q.id]) n++;
      } else if (roundLog[q.id]) {
        n++;
      }
    });
    return n;
  }

  function updateSheetProgress() {
    var el = document.getElementById('sheetProgress');
    if (el) el.textContent = answeredCount() + '/' + totalCount;
  }

  function renderSheet() {
    var grid = document.getElementById('sheetGrid');
    if (!grid) return;
    grid.innerHTML = '';
    var examNeutral = (currentMode === 'exam' && examActive && !examSubmitted);
    var legendEl = document.getElementById('sheetLegend');
    if (legendEl) legendEl.classList.toggle('exam-neutral', examNeutral);
    var correctN = 0, wrongN = 0, flagN = 0, answeredN = 0;
    questionQueue.forEach(function(q, idx) {
      var rec = null, isAnswered = false;
      if (currentMode === 'exam') {
        if (examSubmitted) { rec = answerLog[q.id] || null; isAnswered = !!rec; }
        else { isAnswered = !!examSelections[q.id]; }
      } else if (currentMode === 'fav') {
        rec = answerLog[q.id] || null; isAnswered = !!rec;
      } else {
        rec = roundLog[q.id] || null; isAnswered = !!rec;
      }
      if (isAnswered) answeredN++;
      if (rec && !examNeutral) { if (rec.correct) correctN++; else wrongN++; }
      if (isFlagged(q.id)) flagN++;
      var cell = document.createElement('button');
      cell.type = 'button';
      cell.className = 'sheet-cell';
      if (isAnswered) {
        if (examNeutral) cell.classList.add('answered');
        else cell.classList.add(rec ? (rec.correct ? 'correct' : 'wrong') : 'answered');
      } else {
        cell.classList.add('unanswered');
      }
      if (idx === currentIdx) cell.classList.add('current');
      if (!isAnswered && currentMode !== 'exam') {
        cell.classList.add('locked');
        cell.setAttribute('aria-disabled', 'true');
      }
      cell.textContent = String(idx + 1);
      var aria = '第 ' + (idx + 1) + ' 题';
      if (isAnswered) aria += (rec && !examNeutral) ? (rec.correct ? '，已答对' : '，已答错') : '，已作答';
      else aria += '，未作答';
      cell.setAttribute('aria-label', aria);
      if (isFlagged(q.id)) {
        var star = document.createElement('span');
        star.className = 'star'; star.textContent = '⭐';
        cell.appendChild(star);
      }
      cell.onclick = function() { jumpToQuestion(idx); };
      grid.appendChild(cell);
    });
    var summary = document.getElementById('sheetSummary');
    if (summary) {
      summary.textContent = examNeutral
        ? ('已答 ' + answeredN + '/' + totalCount + ' · 未答 ' + (totalCount - answeredN) + ' · 收藏 ' + flagN)
        : ('已答 ' + answeredN + '/' + totalCount + ' · ' + JUDGE_TRUE_LABEL + ' ' + correctN + ' · ' + JUDGE_FALSE_LABEL + ' ' + wrongN + ' · 收藏 ' + flagN);
    }
    updateSheetProgress();
  }

  function openSheet() {
    playClick();
    renderSheet();
    document.getElementById('sheetOverlay').classList.add('show');
    document.getElementById('sheetPanel').classList.add('show');
  }

  function closeSheet() {
    document.getElementById('sheetOverlay').classList.remove('show');
    document.getElementById('sheetPanel').classList.remove('show');
  }

  function jumpToQuestion(idx) {
    var q = questionQueue[idx];
    if (!q) return;
    if (currentMode === 'fav') {
      if (!answerLog[q.id]) { showToast('该题尚未作答，暂无可回看内容'); return; }
    } else if (currentMode !== 'exam' && !roundLog[q.id]) {
      showToast('学习模式需先作答本题，不能跳题');
      return;
    }
    closeSheet();
    currentIdx = idx;
    renderQuestion();
  }

  function backToCurrent() {
    playClick();
    if (currentMode === 'fav') { openFavPage(); return; }
    var target = -1;
    for (var i = 0; i < questionQueue.length; i++) {
      if (!roundLog[questionQueue[i].id]) { target = i; break; }
    }
    if (target === -1) target = questionQueue.length - 1;
    currentIdx = target;
    renderQuestion();
  }

  function openFavPage() {
    var qs = flaggedIds.map(function(id) {
      return allQuestions.find(function(q) { return q.id === id; });
    }).filter(Boolean);
    var list = document.getElementById('favList');
    list.innerHTML = '';
    document.getElementById('favSummary').textContent = qs.length
      ? ('共 ' + qs.length + ' 题，点击查看作答情况与解析')
      : '还没有收藏题目。做题时点题干右上角的 ⭐ 即可收藏。';
    var typeMap = { single: '单选', multiple: '不定项', judge: '判断' };
    qs.forEach(function(q) {
      var rec = answerLog[q.id];
      var item = document.createElement('div');
      item.className = 'fav-item';
      var snippet = q.question.length > 46 ? q.question.slice(0, 46) + '…' : q.question;
      var qEl = document.createElement('div');
      qEl.className = 'fav-q'; qEl.textContent = snippet;
      item.appendChild(qEl);
      var meta = document.createElement('div');
      meta.className = 'fav-meta';
      var typeEl = document.createElement('span');
      typeEl.className = 'q-type ' + q.type;
      typeEl.style.cssText = 'font-size:11px;padding:2px 8px;';
      typeEl.textContent = typeMap[q.type] || q.type;
      meta.appendChild(typeEl);
      if (q.tag) { var tagEl = document.createElement('span'); tagEl.textContent = '🏷️ ' + q.tag; meta.appendChild(tagEl); }
      var st = document.createElement('span');
      if (rec) { st.className = 'fav-status ' + (rec.correct ? 'ok' : 'bad'); st.textContent = rec.correct ? '✅ 已答对' : '❌ 已答错'; }
      else { st.className = 'fav-status none'; st.textContent = '未作答'; }
      meta.appendChild(st);
      var unstar = document.createElement('button');
      unstar.className = 'fav-unstar'; unstar.textContent = '⭐';
      unstar.title = '取消收藏'; unstar.setAttribute('aria-label', '取消收藏');
      unstar.onclick = function(ev) { ev.stopPropagation(); removeFlag(q.id); openFavPage(); };
      meta.appendChild(unstar);
      item.appendChild(meta);
      item.onclick = function() {
        playClick();
        if (!rec) { showToast('该题尚未作答，先练一次才能回看解析'); return; }
        questionQueue = [q]; totalCount = 1; currentIdx = 0; correctCount = 0; streak = 0;
        currentMode = 'fav';
        showPage('page-quiz'); renderQuestion();
      };
      list.appendChild(item);
    });
    showPage('page-fav');
  }

  function showToast(msg) {
    var el = document.getElementById('toastMini');
    if (!el) return;
    el.textContent = msg;
    el.classList.add('show');
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(function() { el.classList.remove('show'); }, 1800);
  }

  // ============================================================
  // 智能抽题（仅作用于随机模式）
  // ============================================================
  function getStats() {
    var perTag = {};
    var total = 0;
    allQuestions.forEach(function(q) {
      var rec = answerLog[q.id];
      if (!rec || !rec.ts || rec.ts < statsResetAt) return;
      total++;
      if (!q.tag) return;
      var t = perTag[q.tag] || { seen: 0, correct: 0 };
      t.seen++;
      if (rec.correct) t.correct++;
      perTag[q.tag] = t;
    });
    return { perTag: perTag, total: total };
  }

  function weakTags(n) {
    var s = getStats();
    var arr = [];
    Object.keys(s.perTag).forEach(function(tag) {
      var t = s.perTag[tag];
      if (t.seen < 3) return;
      arr.push({ tag: tag, seen: t.seen, correct: t.correct, acc: t.correct / t.seen });
    });
    arr.sort(function(a, b) { return a.acc - b.acc; });
    return arr.slice(0, n);
  }

  function pickWeightedIndex(remaining, s, excludeTags) {
    var weights = remaining.map(function(q) {
      if (!q.tag) return 1.3;
      if (excludeTags.indexOf(q.tag) !== -1) return 0;
      var t = s.perTag[q.tag];
      if (!t || t.seen < 3) return 1.3;
      return 1 + 2 * (1 - (t.correct / t.seen));
    });
    var total = weights.reduce(function(a, b) { return a + b; }, 0);
    if (total <= 0) return Math.floor(Math.random() * remaining.length);
    var r = Math.random() * total, acc = 0;
    for (var i = 0; i < remaining.length; i++) {
      acc += weights[i];
      if (r <= acc) return i;
    }
    return remaining.length - 1;
  }

  function smartOrder(pool, excludeTags) {
    var s = getStats();
    if (s.total < 20) { showToast('数据不足，本轮以随机为主'); return shuffle(pool.slice()); }
    var remaining = pool.slice(), order = [];
    while (remaining.length) {
      var idx = (Math.random() < 0.7)
        ? pickWeightedIndex(remaining, s, excludeTags || [])
        : Math.floor(Math.random() * remaining.length);
      order.push(remaining.splice(idx, 1)[0]);
    }
    return order;
  }

  function showSmartPanel() {
    var weak = weakTags(5);
    var s = getStats();
    var summary = document.getElementById('smartSummary');
    if (s.total < 20) {
      summary.innerHTML = '<p>当前统计样本不足（已记录 ' + s.total + ' 题，少于 20 题），本轮将以<b>随机为主</b>，同时继续收集数据。</p>';
    } else if (weak.length === 0) {
      summary.innerHTML = '<p>暂无明显薄弱标签（各标签作答量还不均衡），本轮将以随机为主。</p>';
    } else {
      var html = '<p>本次将优先练习以下薄弱知识点（按正确率从低到高）：</p><ul style="padding-left:18px;margin:6px 0;">';
      weak.forEach(function(w) {
        html += '<li>' + esc(w.tag) + '：正确率 ' + Math.round(w.acc * 100) + '%（已练 ' + w.seen + ' 题）</li>';
      });
      html += '</ul>';
      summary.innerHTML = html;
    }
    var wrap = document.getElementById('smartExcludeWrap');
    wrap.innerHTML = '';
    if (weak.length) {
      var tip = document.createElement('div');
      tip.style.cssText = 'font-size:13px;color:var(--text-secondary);margin-bottom:6px;';
      tip.textContent = '本次不练（可多选）：';
      wrap.appendChild(tip);
      weak.forEach(function(w) {
        var row = document.createElement('label');
        row.style.cssText = 'display:flex;align-items:center;gap:8px;font-size:13px;margin:4px 0;cursor:pointer;';
        var cb = document.createElement('input');
        cb.type = 'checkbox'; cb.value = w.tag; cb.className = 'smart-exclude-cb';
        var span = document.createElement('span');
        span.textContent = w.tag;
        row.appendChild(cb); row.appendChild(span);
        wrap.appendChild(row);
      });
    }
    showModal('modalSmart');
  }

  function confirmSmartStart() {
    smartExcludeTags = [];
    document.querySelectorAll('.smart-exclude-cb').forEach(function(cb) {
      if (cb.checked) smartExcludeTags.push(cb.value);
    });
    closeModal('modalSmart');
    skipSmartPanel = true;
    startQuiz('random');
  }

  function startPureRandom() {
    closeModal('modalSmart');
    forcePureRandom = true;
    skipSmartPanel = true;
    startQuiz('random');
  }

  function resetSmartStats() {
    statsResetAt = Date.now();
    saveStore('stats_reset_at', statsResetAt);
    showToast('学习统计已重置');
    showSmartPanel();
  }

  function resetRandomProgress() {
    localStorage.removeItem(STORAGE_PREFIX + 'random_done');
    closeModal('modalRandomDone');
    skipSmartPanel = true;
    startQuiz('random');
  }

  // ============================================================
  // 考试模式（延迟判分 + 交卷复盘）
  // ============================================================
  function captureSelected(q) {
    if (q.type === 'multiple') {
      var sels = document.querySelectorAll('.opt-item.selected');
      if (!sels.length) return null;
      return Array.from(sels).map(function(el) { return el.dataset.value; }).sort().join(' · ');
    }
    if (q.type === 'single') {
      var sel = document.querySelector('.opt-item.selected');
      return sel ? sel.dataset.value : null;
    }
    var jsel = document.querySelector('.judge-btn.selected');
    return jsel ? jsel.dataset.value : null;
  }

  function recordExamSelection(q) {
    var sel = captureSelected(q);
    if (sel) examSelections[q.id] = sel;
    else delete examSelections[q.id];
    renderSheet();
    updateSheetProgress();
  }

  function examElapsed() { return Math.max(0, Math.floor((performance.now() - examStartTime) / 1000)); }

  function fmtDuration(sec) {
    var m = Math.floor(sec / 60), s = sec % 60;
    return (m < 10 ? '0' : '') + m + ':' + (s < 10 ? '0' : '') + s;
  }

  function updateExamTimerDisplay() {
    var el = document.getElementById('examTimer');
    if (!el) return;
    if (!examActive && !examSubmitted) { el.style.display = 'none'; return; }
    var sec = examSubmitted ? examElapsedSec : examElapsed();
    el.textContent = '⏱ ' + fmtDuration(sec);
    el.style.display = '';
  }

  function startExamTimer() {
    stopExamTimer();
    examStartTime = performance.now();
    updateExamTimerDisplay();
    examTimerId = setInterval(updateExamTimerDisplay, 1000);
  }

  function stopExamTimer() {
    if (examTimerId) { clearInterval(examTimerId); examTimerId = null; }
  }

  function submitExam() {
    var unanswered = [];
    questionQueue.forEach(function(q, idx) {
      if (!examSelections[q.id]) unanswered.push(idx + 1);
    });
    if (unanswered.length) {
      document.getElementById('examUnansweredText').textContent =
        '还有 ' + unanswered.length + ' 题未作答：第 ' + unanswered.join('、') + ' 题。答完全部题目后才能交卷。';
      showModal('modalExamUnanswered');
      return;
    }
    document.getElementById('examConfirmText').textContent = '本次考试共 ' + totalCount + ' 题，已全部作答。';
    showModal('modalExamConfirm');
  }

  function goToUnanswered() {
    closeModal('modalExamUnanswered');
    for (var i = 0; i < questionQueue.length; i++) {
      if (!examSelections[questionQueue[i].id]) {
        currentIdx = i; renderQuestion(); return;
      }
    }
  }

  function finalizeExam() {
    if (!examActive || examSubmitted) return;
    closeModal('modalExamConfirm');
    examElapsedSec = examElapsed();
    stopExamTimer();
    correctCount = 0;
    questionQueue.forEach(function(q) {
      var selected = examSelections[q.id];
      var isCorrect = (selected === q.answer);
      if (isCorrect) correctCount++;
      answerLog[q.id] = {
        selected: selected,
        correct: isCorrect,
        ts: Date.now(),
        attempts: answerLog[q.id] && answerLog[q.id].attempts ? answerLog[q.id].attempts + 1 : 1
      };
      saveProgress(isCorrect, q);
    });
    saveStore('answers', answerLog);
    examActive = false;
    examSubmitted = true;
    renderSheet();
    updateExamTimerDisplay();
    updateFlagButton();
    showExamResult();
  }

  function showExamResult() {
    var acc = totalCount > 0 ? Math.round(correctCount / totalCount * 100) : 0;
    var grid = document.getElementById('examResultStats');
    grid.innerHTML = '';
    [
      { label: '题量', value: totalCount + ' 题' },
      { label: '正确率', value: acc + '%' },
      { label: '用时', value: fmtDuration(examElapsedSec) }
    ].forEach(function(s) {
      var card = document.createElement('div'); card.className = 'stat-card';
      var num = document.createElement('div'); num.className = 'stat-num'; num.textContent = s.value;
      var lab = document.createElement('div'); lab.className = 'stat-label'; lab.textContent = s.label;
      card.appendChild(num); card.appendChild(lab); grid.appendChild(card);
    });
    showModal('modalExamResult');
  }

  function reviewFromResult() {
    closeModal('modalExamResult');
    showPage('page-quiz');
    currentIdx = 0;
    renderSheet();
    renderQuestion();
  }

  function goHomeAfterExam() {
    closeModal('modalExamResult');
    stopExamTimer();
    examActive = false; examSubmitted = false; examSelections = {}; examElapsedSec = 0;
    var el = document.getElementById('examTimer');
    if (el) el.style.display = 'none';
    showPage('page-home');
    renderHome();
  }

  function discardExam() {
    closeModal('modalExamQuit');
    stopExamTimer();
    examActive = false; examSubmitted = false; examSelections = {}; examElapsedSec = 0;
    var el = document.getElementById('examTimer');
    if (el) el.style.display = 'none';
    currentIdx = 0;
    showPage('page-home');
  }

  function transitionSlide(dir, callback) {
    if (isTransitioning) return;
    isTransitioning = true;
    var area = document.getElementById('questionArea');
    var outAnim = dir === 'next' ? 'slide-out-left 0.25s ease forwards' : 'slide-out-right 0.25s ease forwards';
    var inAnim = dir === 'next' ? 'slide-in-right 0.3s ease' : 'slide-in-left 0.3s ease';
    area.style.animation = outAnim;
    setTimeout(function() {
      callback();
      void area.offsetHeight;
      area.style.animation = inAnim;
      setTimeout(function() {
        area.style.animation = '';
        isTransitioning = false;
      }, 300);
    }, 250);
  }
  function nextQuestion() {
    playClick();
    if (currentIdx < questionQueue.length - 1) { currentIdx++; transitionSlide('next', renderQuestion); }
    else if (currentMode === 'exam' && examActive && !examSubmitted) { showToast('已是最后一题，请点击"交卷"'); }
    else if (currentMode === 'exam' && examSubmitted) { showToast('已是最后一题'); }
    else if (currentMode === 'fav') { openFavPage(); }
    else { showComplete(); }
  }
  function prevQuestion() {
    playClick();
    if (currentIdx > 0) { currentIdx--; transitionSlide('prev', renderQuestion); }
  }

  function exitQuiz() {
    if (currentMode === 'exam' && examActive && !examSubmitted) { showModal('modalExamQuit'); return; }
    showPage('page-home');
    if (currentMode === 'topic' && currentSection) {
      var curQ = questionQueue[currentIdx];
      saveStore('topic_' + currentSection, { id: curQ ? curQ.id : null });
    }
  }

  // 本轮错题列表（按作答顺序，去重）
  function roundWrongList() {
    var list = [];
    questionQueue.forEach(function(q) {
      if (list.indexOf(q) !== -1) return;
      var rec = roundLog[q.id];
      if (rec && !rec.correct) list.push(q);
    });
    return list;
  }

  // 重练本轮错题：复用错题专项规则（学习模式、不可跳题、已答只读）
  function retryRoundWrong() {
    playClick();
    var wrongQs = roundWrongList();
    if (wrongQs.length === 0) { showToast('本轮没有错题'); return; }
    currentMode = 'wrong';
    currentSection = null;
    currentTags = [];
    questionQueue = wrongQs;
    currentIdx = 0; correctCount = 0; totalCount = wrongQs.length; streak = 0;
    roundLog = {};
    examActive = false; examSubmitted = false;
    stopExamTimer();
    var timerEl = document.getElementById('examTimer');
    if (timerEl) timerEl.style.display = 'none';
    showPage('page-quiz');
    renderQuestion();
  }

  function showComplete() {
    showPage('page-complete');
    // 徽章弹出重触发
    var icon = document.querySelector('.complete-page .big-icon');
    icon.style.animation = 'none'; void icon.offsetHeight; icon.style.animation = '';
    // 纸屑
    launchConfetti();
    document.getElementById('completeTitle').textContent = '🎉 全部完成！';
    document.getElementById('completeDesc').textContent = '你已完成 ' + totalCount + ' 道题目。';
    var wrongN = roundWrongList().length;
    var retryBtn = document.getElementById('btnRetryWrong');
    if (retryBtn) {
      retryBtn.style.display = wrongN ? '' : 'none';
      retryBtn.textContent = wrongN ? ('🔁 重练本轮错题（' + wrongN + '）') : '🔁 重练本轮错题';
    }
    var stats = [
      { label: '总题数', value: totalCount },
      { label: '答对数', value: correctCount },
      { label: '正确率', value: totalCount > 0 ? Math.round(correctCount / totalCount * 100) : 0 }
    ];
    var grid = document.getElementById('statsGrid'); grid.innerHTML = '';
    stats.forEach(function(s) {
      var card = document.createElement('div'); card.className = 'stat-card';
      var numEl = document.createElement('div'); numEl.className = 'stat-num'; numEl.textContent = '0';
      card.appendChild(numEl);
      var labelEl = document.createElement('div'); labelEl.className = 'stat-label'; labelEl.textContent = s.label;
      card.appendChild(labelEl); grid.appendChild(card);
      var target = s.value, step = Math.max(1, Math.floor(target / 30)), cur = 0;
      var timer = setInterval(function() {
        cur += step; if (cur >= target) { cur = target; clearInterval(timer); }
        numEl.textContent = s.label === '正确率' ? cur + '%' : cur;
      }, 40);
    });
  }

  // ============================================================
  // 进度条分段标记
  // ============================================================
  function initProgressDots() {
    var container = document.getElementById('progressDots');
    [20, 40, 60, 80, 100].forEach(function(pct) {
      var dot = document.createElement('span');
      dot.className = 'dot'; dot.style.left = pct + '%';
      container.appendChild(dot);
    });
  }
  function updateProgressDots(pct) {
    var dots = document.querySelectorAll('.progress-dots .dot');
    dots.forEach(function(dot) {
      var pos = parseFloat(dot.style.left);
      if (pct >= pos) { dot.classList.add('done'); }
      else { dot.classList.remove('done'); }
    });
  }

  // ============================================================
  // 完成页庆祝
  // ============================================================
  function launchConfetti() {
    var container = document.createElement('div');
    container.className = 'confetti-container';
    var colors = ['var(--accent)', 'var(--gold)', 'var(--success)', 'var(--accent-light)', 'var(--gold-light)', 'var(--accent-dark)'];
    for (var i = 0; i < 35; i++) {
      var piece = document.createElement('div');
      piece.className = 'confetti-piece';
      var size = 6 + Math.random() * 6;
      var left = Math.random() * 100;
      var dur = 2 + Math.random() * 2.5;
      var delay = Math.random() * 0.8;
      piece.style.cssText = 'left:' + left + '%;width:' + size + 'px;height:' + size + 'px;animation-duration:' + dur + 's;animation-delay:' + delay + 's;background:' + colors[i % colors.length];
      container.appendChild(piece);
    }
    document.body.appendChild(container);
    setTimeout(function() { if (container.parentNode) container.remove(); }, 6000);
  }

  // ============================================================
  // 弹窗管理
  // ============================================================
  function showModal(id) { document.getElementById(id).classList.add('show'); }
  function closeModal(id) { document.getElementById(id).classList.remove('show'); }
  function closeStartupModal() { closeModal('modalStartup'); }
  function closeHelp() { closeModal('modalHelp'); }
  function confirmTagSelection() {
    if (!currentTags.length) return;
    closeModal('modalTagSelect');
    startQuiz('tag');
  }
  function cancelTagSelection() {
    currentTags = [];
    closeModal('modalTagSelect');
    showPage('page-home');
  }
  function showResumeModal(idx, section) {
    document.getElementById('resumeText').textContent = '在「' + section + '」中，你已完成 ' + idx + ' 题。是否继续上次的进度？';
    showModal('modalResume');
  }
  function acceptResume() {
    closeModal('modalResume');
    var saved = loadStore('topic_' + currentSection, {}); currentIdx = saved.id ? questionQueue.findIndex(function(qi) { return qi.id === saved.id; }) + 1 : 0; if (currentIdx >= questionQueue.length) { currentIdx = questionQueue.length - 1; } if (currentIdx < 0) { currentIdx = 0; }
    showPage('page-quiz'); renderQuestion();
  }
  function dismissResume() {
    closeModal('modalResume');
    localStorage.removeItem(STORAGE_PREFIX + 'topic_' + currentSection);
    currentIdx = 0; showPage('page-quiz'); renderQuestion();
  }

  // ============================================================
  // 页面切换
  // ============================================================
  function showPage(pageId) {
    document.querySelectorAll('.page').forEach(function(p) { p.classList.remove('active'); });
    var page = document.getElementById(pageId);
    page.classList.add('active');
    page.style.animation = 'none'; void page.offsetHeight; page.style.animation = '';
    var sheetBtn = document.getElementById('btnSheet');
    if (sheetBtn) sheetBtn.classList.toggle('show', pageId === 'page-quiz');
    if (pageId !== 'page-quiz') closeSheet();
    if (pageId === 'page-home') renderHome();
  }

  // ============================================================
  // 键盘快捷键
  // ============================================================
  document.addEventListener('keydown', function(e) {
    var tag = (e.target && e.target.tagName) ? e.target.tagName.toLowerCase() : '';
    if (tag === 'input' || tag === 'textarea') return;
    if ((e.key === 'f' || e.key === 'F') && document.getElementById('page-quiz').classList.contains('active')) { toggleFlag(); return; }
    if (e.key === 'Enter' && !isSubmitted && document.getElementById('btnSubmit').style.display !== 'none') submitAnswer();
    if (isSubmitted) {
      if (e.key === 'ArrowRight' || e.key === ' ') nextQuestion();
      if (e.key === 'ArrowLeft') prevQuestion();
    }
    if (e.key >= '1' && e.key <= '4' && !isSubmitted) {
      var opts = document.querySelectorAll('.opt-item, .judge-btn');
      var idx = parseInt(e.key) - 1;
      if (opts[idx]) opts[idx].click();
    }
  });

  // ============================================================
  // 暴露全局函数（供 HTML onclick 属性使用）
  // ============================================================
  window.showPage = showPage;
  window.submitAnswer = submitAnswer;
  window.prevQuestion = prevQuestion;
  window.nextQuestion = nextQuestion;
  window.exitQuiz = exitQuiz;
  window.closeStartupModal = closeStartupModal;
  window.closeHelp = closeHelp;
  window.confirmTagSelection = confirmTagSelection;
  window.cancelTagSelection = cancelTagSelection;
  window.acceptResume = acceptResume;
  window.dismissResume = dismissResume;
  window.toggleFlag = toggleFlag;
  window.openSheet = openSheet;
  window.closeSheet = closeSheet;
  window.backToCurrent = backToCurrent;
  window.removeFlag = removeFlag;
  window.confirmSmartStart = confirmSmartStart;
  window.startPureRandom = startPureRandom;
  window.resetSmartStats = resetSmartStats;
  window.resetRandomProgress = resetRandomProgress;
  window.closeModal = closeModal;
  window.submitExam = submitExam;
  window.goToUnanswered = goToUnanswered;
  window.finalizeExam = finalizeExam;
  window.showExamResult = showExamResult;
  window.reviewFromResult = reviewFromResult;
  window.goHomeAfterExam = goHomeAfterExam;
  window.discardExam = discardExam;
  window.openFavPage = openFavPage;
  window.retryRoundWrong = retryRoundWrong;

  // ============================================================
  // 启动弹窗 + 页脚时间
  // ============================================================
  showModal('modalStartup');
  var count = 5, el = document.getElementById('countdown');
  var btnEnter = document.getElementById('btnEnter');
  var timer = setInterval(function() {
    count--;
    if (count <= 0) {
      clearInterval(timer);
      el.textContent = '0';
      btnEnter.disabled = false;
      btnEnter.textContent = '立即进入';
    } else {
      el.textContent = count;
      btnEnter.textContent = '请等待 ' + count + ' 秒';
    }
  }, 1000);
  document.getElementById('footerTime').textContent = new Date().toLocaleString('zh-CN');

  // ============================================================
  // 初始化
  // ============================================================
  smartRandom = loadStore('smart_random', false);
  statsResetAt = loadStore('stats_reset_at', 0);
  answerLog = loadStore('answers', {});
  if (!answerLog || typeof answerLog !== 'object') answerLog = {};
  flaggedIds = loadStore('flagged', []);
  if (!Array.isArray(flaggedIds)) flaggedIds = [];
  var validIdMap = {};
  allQuestions.forEach(function(q) { validIdMap[q.id] = true; });
  flaggedIds = flaggedIds.filter(function(id) { return validIdMap[id]; });
  saveStore('flagged', flaggedIds);
  ['wrong_set', 'random_done', 'career_done', 'career_wrong'].forEach(function(key) {
    var arr = loadStore(key, []);
    if (!Array.isArray(arr)) { saveStore(key, []); return; }
    var filtered = arr.filter(function(id) { return validIdMap[id]; });
    if (filtered.length !== arr.length) saveStore(key, filtered);
  });
  renderHome();
  // 答题卡图例中的判断题术语按题库语体显示
  (function () {
    var a = document.getElementById('lgCorrect');
    if (a) a.textContent = JUDGE_TRUE_LABEL;
    var b = document.getElementById('lgWrong');
    if (b) b.textContent = JUDGE_FALSE_LABEL;
  })();
  initProgressDots();
})();
</script>
</body>
</html>"""


# ============================================================
# 风格定义
# ============================================================
STYLES = {
    "宣纸": {
        "font": "'Noto Serif SC', 'Songti SC', 'SimSun', Georgia, serif",
        "sans": "'Noto Sans SC', 'PingFang SC', 'Microsoft YaHei', sans-serif",
        "css": """
:root {
  --bg-page: #f5f0e8;
  --bg-card: #faf8f2;
  --bg-card-hover: #f7f3ea;
  --text-primary: #3d3229;
  --text-secondary: #6b5d50;
  --text-light: #9a8b7a;
  --accent: #b8451e;
  --accent-light: #e8c4b0;
  --accent-dark: #8c3516;
  --gold: #c9a84c;
  --gold-light: #e8d9a8;
  --border: #d9cdbc;
  --border-light: #e8dfd2;
  --success: #4a7c59;
  --success-bg: #e2efe4;
  --error: #b8451e;
  --error-bg: #f5e0d8;
  --shadow: rgba(61, 50, 41, 0.08);
}
body { background-image: radial-gradient(ellipse at 20% 50%, rgba(201, 168, 76, 0.04) 0%, transparent 60%), radial-gradient(ellipse at 80% 20%, rgba(184, 69, 30, 0.03) 0%, transparent 50%); }
"""
    },
    "瑞士": {
        "font": "'Noto Sans SC', 'Inter', 'Helvetica Neue', Arial, sans-serif",
        "sans": "'Noto Sans SC', 'Inter', 'Helvetica Neue', Arial, sans-serif",
        "css": """
:root {
  --bg-page: #ffffff;
  --bg-card: #f8f8f8;
  --bg-card-hover: #f0f0f0;
  --text-primary: #1a1a1a;
  --text-secondary: #555555;
  --text-light: #999999;
  --accent: #0052cc;
  --accent-light: #cce0ff;
  --accent-dark: #003399;
  --gold: #0052cc;
  --gold-light: #e6f0ff;
  --border: #d0d0d0;
  --border-light: #e0e0e0;
  --success: #00875a;
  --success-bg: #e3fcef;
  --error: #de350b;
  --error-bg: #ffe8e5;
  --shadow: rgba(0, 0, 0, 0.06);
}
"""
    },
    "卡片": {
        "font": "'Noto Sans SC', 'PingFang SC', 'Microsoft YaHei', sans-serif",
        "sans": "'Noto Sans SC', 'PingFang SC', 'Microsoft YaHei', sans-serif",
        "css": """
:root {
  --bg-page: #f0f2f5;
  --bg-card: #ffffff;
  --bg-card-hover: #fafafa;
  --text-primary: #2c3e50;
  --text-secondary: #5a6a7a;
  --text-light: #95a5a6;
  --accent: #e67e22;
  --accent-light: #fdebd0;
  --accent-dark: #c96b1a;
  --gold: #3498db;
  --gold-light: #d6eaf8;
  --border: #dcdde1;
  --border-light: #e8e8e8;
  --success: #27ae60;
  --success-bg: #e8f8f0;
  --error: #e74c3c;
  --error-bg: #fdedec;
  --shadow: rgba(0, 0, 0, 0.08);
}
.question-area { border-radius: 16px; }
.mode-card { border-radius: 16px; }
"""
    }
}


# ============================================================
# 题库解析器
# ============================================================

# ============================================================
# 判断题答案归一 与 题库语体判断
# ============================================================
_JUDGE_TRUE_WORDS = ('正确', '正確', '对', '對', '是')
_JUDGE_FALSE_WORDS = ('错误', '錯誤', '错', '錯', '否')
_JUDGE_TRUE_SYMBOLS = ('✔', '√', '✓', '☑')
_JUDGE_FALSE_SYMBOLS = ('✘', '✗', '×', '☒')


def normalize_judge_answer(raw):
    """把判断题答案的常见写法归一为 '正确' / '错误'；无法判定时返回 None。

    兼容：正确 / 正確 / 对 / 對 / 是 / ✔ / √ / ✓ 与 错误 / 錯誤 / 错 / 錯 / 否 / ✘ / ×，
    也兼容英文 true / false，以及「✘ 錯誤」这类符号加文字的混写。
    """
    if not raw:
        return None
    t = raw.strip()
    if not t:
        return None
    # 先处理「不对 / 不正确」这类否定式，避免被单字「对」误判
    if ('不对' in t) or ('不對' in t) or ('不正确' in t) or ('不正確' in t) or ('不对的' in t):
        return '错误'
    for w in _JUDGE_TRUE_WORDS:
        if w in t:
            return '正确'
    for w in _JUDGE_FALSE_WORDS:
        if w in t:
            return '错误'
    for s in _JUDGE_TRUE_SYMBOLS:
        if s in t:
            return '正确'
    for s in _JUDGE_FALSE_SYMBOLS:
        if s in t:
            return '错误'
    low = t.lower()
    if low in ('t', 'true', 'yes', 'y'):
        return '正确'
    if low in ('f', 'false', 'no', 'n'):
        return '错误'
    return None


# 繁简一一对应的特征字（用于粗判题库语体，避免引入额外依赖）
_VARIANT_PAIRS = [
    ('爲', '为'), ('為', '为'), ('於', '于'), ('說', '说'), ('對', '对'), ('這', '这'),
    ('個', '个'), ('們', '们'), ('來', '来'), ('時', '时'), ('會', '会'), ('學', '学'),
    ('國', '国'), ('體', '体'), ('發', '发'), ('萬', '万'), ('與', '与'), ('從', '从'),
    ('無', '无'), ('漢', '汉'), ('語', '语'), ('詞', '词'), ('讀', '读'), ('寫', '写'),
    ('歸', '归'), ('錯', '错'), ('誤', '误'), ('確', '确'), ('義', '义'), ('釋', '释'),
]


def detect_variant(text):
    """粗判题库语体：繁体特征字更多则返回 'zh-Hant'，否则 'zh-Hans'。"""
    trad = sum(text.count(t) for t, _ in _VARIANT_PAIRS)
    simp = sum(text.count(s) for _, s in _VARIANT_PAIRS)
    return 'zh-Hant' if trad > simp else 'zh-Hans'


def parse_question_block(text, filename):
    num_m = re.search(r'###\s*第\s*(\d+)\s*[题題]', text)
    if not num_m:
        return None
    qid = int(num_m.group(1))
    has_options = bool(re.search(r'\n[A-E][.、）)\s]', text))

    if has_options:
        q_text_m = re.search(
            r'###\s*第\s*\d+\s*[题題](?:[（(][^)）]*[)）])?\s*\n+(.*?)\n[A-E]', text, re.DOTALL
        )
        if not q_text_m:
            return None
        q_text = q_text_m.group(1).strip()
        options = []
        for m in re.finditer(r'\n([A-E])\s*[.、）)\s]\s*(.*?)(?=\n[A-E]|\n\n|\*\*答案|$)', '\n' + text):
            opt_content = m.group(2).strip().replace('**', '').strip()
            options.append(m.group(1) + '. ' + opt_content)
        # 先尝试匹配不定项选择（多字母答案如 A · B · D）
        ans_m = re.search(r'\*\*答案\*\*\s*[:：]\s*(.*?)(?=\n|$)', text)
        if ans_m:
            ans_raw = ans_m.group(1).strip()
            multi_m = re.findall(r'[A-E]', ans_raw)
            if len(multi_m) >= 2 or '全選' in ans_raw or '全选' in ans_raw:
                # 不定项选择
                answer = ' · '.join(multi_m)
                qtype = "multiple"
            else:
                # 单项选择
                ans_single = re.search(r'\*\*答案\*\*\s*[:：]\s*([A-E])', text)
                answer = ans_single.group(1) if ans_single else None
                qtype = "single"
        else:
            answer = None
            qtype = "single"
    else:
        q_text_m = re.search(
            r'###\s*第\s*\d+\s*[题題](?:[（(][^)）]*[)）])?\s*\n+(.*?)(?=\n\*\*答案\*\*)', text, re.DOTALL
        )
        if not q_text_m:
            return None
        q_text = re.sub(r'[（(]\s*[)）]\s*$', '', q_text_m.group(1).strip()).strip()
        ans_m = re.search(r'\*\*答案\*\*\s*[:：]\s*(.*?)(?=\n|$)', text)
        answer = normalize_judge_answer(ans_m.group(1)) if ans_m else None
        options = []
        qtype = "judge"

    if answer is None:
        return None

    expl_m = re.search(r'\*\*解析\*\*\s*[:：]\s*(.*?)(?=\n\*\*(?:知识|知識)回溯)', text, re.DOTALL)
    explanation = expl_m.group(1).strip() if expl_m else ""
    tag_m = re.search(r'\*\*(?:知识|知識)回溯\*\*\s*[:：]\s*(.*?)(?=\n|$)', text)
    tag = tag_m.group(1).strip() if tag_m else ""

    return {
        "id": qid, "file": filename, "type": qtype,
        "question": q_text, "options": options,
        "answer": answer, "explanation": explanation, "tag": tag
    }


def parse_file(filepath):
    """返回 (section_name, questions, failed)。

    failed 记录「看起来是题目块但没解析成功」的条目，供构建后对账与定位使用。
    """
    filename = os.path.splitext(os.path.basename(filepath))[0]
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    section_m = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
    section_name = section_m.group(1).strip() if section_m else filename
    # 按「### 第 N 題」切分，而不是按 --- 分隔线：
    # 旧题库里存在连续排列、题与题之间没有 --- 的段落，按分隔线切会整段丢失；
    # 按题号切分同时兼容标准写法（--- 会落在上一题块尾，不影响解析）
    blocks = re.split(r'(?m)^(?=\s*###\s*第\s*\d+\s*[题題])', content)
    questions = []
    failed = []
    seen_ids = set()
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        q = parse_question_block(block, filename)
        if q:
            # 内容哈希作ID（改题干不影响其他题进度）
            q['id'] = 'q_' + hashlib.md5((section_name + q['question']).encode('utf-8')).hexdigest()[:8]
            if q['id'] in seen_ids:
                print(f"  [!] 警告: {filename} 中题号 {q['id']} 重复")
            seen_ids.add(q['id'])
            q['section'] = section_name
            questions.append(q)
        elif re.search(r'###\s*第\s*\d+\s*[题題]', block):
            num_m = re.search(r'###\s*第\s*(\d+)\s*[题題]', block)
            ans_m = re.search(r'\*\*答案\*\*\s*[:：]\s*(.*?)(?=\n|$)', block)
            failed.append({
                'num': num_m.group(1) if num_m else '?',
                'answer': (ans_m.group(1).strip()[:20] if ans_m else '（未找到答案行）'),
                'head': re.sub(r'\s+', ' ', block[:48]),
            })
    return section_name, questions, failed


# ============================================================
# 主函数
# ============================================================

def main():
    parser = argparse.ArgumentParser(description='刷题网站生成器')
    parser.add_argument('--input', required=True, help='题库 Markdown 文件夹路径')
    parser.add_argument('--title', required=True, help='网站标题')
    parser.add_argument('--output', required=True, help='输出目录')
    parser.add_argument('--modes', default='topic,random,career,wrong,tag',
                        help='启用的模式，逗号分隔（默认: topic,random,career,wrong,tag）')
    parser.add_argument('--style', choices=list(STYLES.keys()), default='宣纸',
                        help='视觉风格')
    parser.add_argument('--katex', action='store_true', help='启用 KaTeX 公式渲染')
    parser.add_argument('--no-smart-quotes', '--no-punct-fix', dest='no_punct_fix',
                        action='store_true',
                        help='关闭构建期的中文标点规范化（引号 / 省略号 / 破折号）')
    parser.add_argument('--subtitle', default='', help='副标题')
    parser.add_argument('--prefix', default='', help='localStorage 存储前缀（自动生成）')
    parser.add_argument('--custom-css', default='', help='自定义 CSS 代码或 CSS 变量覆盖（注入到 :root 中）')
    args = parser.parse_args()

    print("=" * 50)
    print(f"  刷题网站生成器 — 构建脚本")
    print(f"  题库: {args.input}")
    print(f"  标题: {args.title}")
    print(f"  风格: {args.style}")
    print(f"  模式: {args.modes}")
    print("=" * 50)

    # 解析题库
    md_files = sorted([os.path.join(dirpath, f) for dirpath, _, filenames in os.walk(args.input) for f in filenames if f.endswith('.md')])
    if not md_files:
        print("[!] 未找到 .md 文件"); return

    all_questions = []
    total_blocks = 0
    total_parsed = 0
    failed_all = []
    section_map = {}
    all_text_for_variant = []

    for fp in md_files:
        fname = os.path.basename(fp)
        print(f"\n📄 解析: {fname}")
        with open(fp, 'r', encoding='utf-8') as _f:
            raw_content = _f.read()
        all_text_for_variant.append(raw_content)
        total_blocks += len(re.findall(r'###\s*第\s*\d+\s*[题題]', raw_content))
        section_name, questions, failed = parse_file(fp)
        total_parsed += len(questions)
        if failed:
            failed_all.append((fname, failed))
        for q in questions:
            if q['type'] == 'single':
                for opt in q['options']:
                    bold_m = re.search(r'\*\*([A-E])\*\*', opt)
                    if bold_m and bold_m.group(1) != q['answer']:
                        print(f"  [!] 交叉校验冲突: {fname} 第 {q['id']} 题")
        start_idx = len(all_questions)
        all_questions.extend(questions)
        section_map[section_name] = list(range(start_idx, len(all_questions)))
        print(f"  → {len(questions)} 题（累计 {len(all_questions)} 题）")

    # 对账
    print(f"\n{'=' * 50}")
    print(f"📊 解析结果")
    print(f"  文件内题块: {total_blocks}")
    print(f"  成功解析  : {total_parsed}")
    if total_blocks != total_parsed:
        print(f"  ⚠️  {total_blocks - total_parsed} 题未能解析：")
        for fname, failed in failed_all:
            print(f"     · {fname}")
            for fb in failed[:6]:
                print(f"         第 {fb['num']} 題 | 答案=「{fb['answer']}」| {fb['head']}…")
            if len(failed) > 6:
                print(f"         …另有 {len(failed) - 6} 题")
        print(f"  提示：多为「**答案**」行写法或选项格式未识别，请对照源文件检查")
    else:
        print(f"  ✅ 全部解析成功！")

    all_tags = sorted(set(q['tag'] for q in all_questions if q['tag']))
    print(f"🏷️  知识点标签: {len(all_tags)} 个")

    # 版本哈希
    content_hash = hashlib.md5(json.dumps(all_questions, ensure_ascii=False).encode()).hexdigest()[:8]
    print(f"🔑 版本: {content_hash}")

    # 中文标点规范化（放在题目 ID 与版本哈希计算之后，避免影响既有刷题进度）
    if not args.no_punct_fix:
        dq_n = sq_n = ell_n = dash_n = 0
        for q in all_questions:
            for field in ('question', 'explanation', 'tag'):
                src = q.get(field) or ''
                dq_n += src.count('"')
                sq_n += src.count("'")
                ell_n += src.count('...')
                dash_n += src.count('--')
                q[field] = normalize_punctuation(src)
            if q.get('options'):
                for o in q['options']:
                    dq_n += o.count('"')
                    sq_n += o.count("'")
                    ell_n += o.count('...')
                    dash_n += o.count('--')
                q['options'] = [normalize_punctuation(o) for o in q['options']]
        if dq_n or sq_n or ell_n or dash_n:
            print(f"❝ 标点规范化: 双引号 {dq_n}、单引号 {sq_n}、省略号 {ell_n}、破折号 {dash_n} 处")

    # 存储前缀
    prefix = args.prefix or 'quiz_' + os.path.basename(os.path.normpath(args.output)) + '_'

    # 注入数据
    style = STYLES[args.style]
    html = HTML_TEMPLATE
    html = html.replace('__TITLE__', args.title)
    html = html.replace('__SUBTITLE__', args.subtitle)
    html = html.replace('__STYLE_CSS__', style['css'] + (('\n' + args.custom_css) if args.custom_css else ''))
    html = html.replace('__FONT_FAMILY__', style['font'])
    html = html.replace('__SANS_FAMILY__', style['sans'])
    html = html.replace('__VERSION_HASH__', content_hash)
    html = html.replace('__STORAGE_PREFIX__', prefix)
    html = html.replace('__ENABLED_MODES__', args.modes)
    html = html.replace('__QUESTIONS_JSON__', json_for_script(all_questions))
    html = html.replace('__SECTIONS_JSON__', json_for_script(section_map))
    html = html.replace('__TAGS_JSON__', json_for_script(all_tags))

    # 判断题术语按题库语体注入（繁体题库显示「正確 / 錯誤」，简体题库显示「正确 / 错误」）
    variant = detect_variant(''.join(all_text_for_variant))
    judge_true = '正確' if variant == 'zh-Hant' else '正确'
    judge_false = '錯誤' if variant == 'zh-Hant' else '错误'
    html = html.replace('__JUDGE_TRUE__', judge_true)
    html = html.replace('__JUDGE_FALSE__', judge_false)
    print(f"🔤 题库语体: {'繁体' if variant == 'zh-Hant' else '简体'}　判断题按钮显示「{judge_true} / {judge_false}」")

    # KaTeX（可选，内联进单文件；不启用时占位符清空，行为与旧版一致）
    katex_css, katex_js = (None, None)
    if args.katex:
        katex_css, katex_js = load_katex()
        if katex_css is None:
            print("⚠️  未找到 KaTeX 资源（assets/katex/），本次跳过公式渲染")
    if katex_css and katex_js:
        html = html.replace('__KATEX_CSS__', katex_css)
        html = html.replace('__KATEX_JS__', '<script>' + katex_js + '</script>')
        html = html.replace('__KATEX_FLAG__', 'true')
        print("🧮 已内联 KaTeX（含 woff2 字体 base64）")
    else:
        html = html.replace('__KATEX_CSS__', '')
        html = html.replace('__KATEX_JS__', '')
        html = html.replace('__KATEX_FLAG__', 'false')

    # 输出
    os.makedirs(args.output, exist_ok=True)
    output_path = os.path.join(args.output, 'index.html')
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"\n✅ 已生成: {output_path} ({len(html)} 字节)")


if __name__ == '__main__':
    main()
