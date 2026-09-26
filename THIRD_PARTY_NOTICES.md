# 第三方组件声明

本项目包含以下第三方开源组件。它们的版权归原作者所有，按各自的许可协议授权使用。

---

## KaTeX

- **用途**：刷题网站的数学公式渲染（`--katex` 参数启用时使用）
- **位置**：`assets/katex/`
- **版本**：随仓库内文件为准
- **许可**：MIT License
- **版权**：Copyright (c) 2013-2020 Khan Academy and other contributors
- **许可全文**：见 [`assets/katex/LICENSE`](assets/katex/LICENSE)
- **项目主页**：https://katex.org/

**说明**：KaTeX 的脚本（`katex.min.js`）、样式（`katex.min.css`）与 20 个 woff2 字体文件
均随本项目分发，用途是在构建时将其 base64 内联进生成的 HTML，使刷题网站保持
**离线单文件可用**（不产生任何网络请求）。

字体采用 `woff2` 格式，在网络传输中已压缩，无需再经 gzip。

---

## 未包含的依赖

本项目的构建脚本（`build.py`）**仅使用 Python 标准库**
（`os` / `re` / `json` / `hashlib` / `argparse` / `collections` / `base64` / `sys`），
**不依赖任何第三方 Python 包**，因此无需声明其他组件。

Python 标准库本身随 Python 解释器分发，不随本仓库分发。
