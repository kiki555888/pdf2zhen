#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
预处理模块：
1. 合并每个 part 内的所有 .md 文件（按自然顺序），写入 output_root 对应 part 目录
2. 复制 images/ 和 imgs/ 到 output_root 对应 part 目录
3. 删除 <details>、<sub>、<sup> 标签
4. 删除 <div> 标签（保留内容），保护 <img> 标签（统一使用 <IMAGExxxxx/> 占位符）
5. 保护 HTML 表格、Markdown 表格、链接、图片、代码、公式等
6. 生成映射文件 (.mapping.json)
7. 占位符格式统一为 <TYPEXXXXX/>
"""

import re
import json
import shutil
from pathlib import Path
from typing import Dict, Tuple, List


def natural_sort_key(s: str) -> List:
    """自然排序键，与 md_merger 保持一致"""
    return [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', s)]


class InlineMarkdownProtector:
    def __init__(self):
        self.mapping = {}
        self.counters = {
            'code': 0, 'math': 0, 'link': 0, 'image': 0,      # image 统一用于所有图片
            'table': 0, 'codeblock': 0, 'mathblock': 0
        }
        self.details_re = re.compile(r'<details>.*?</details>', re.DOTALL)
        self.html_table_re = re.compile(r'<table[^>]*>.*?</table>', re.DOTALL | re.IGNORECASE)
        self.markdown_table_re = re.compile(r'((?:^\s*\|.*\|$[\r\n]?)+)', re.MULTILINE)
        self.codeblock_re = re.compile(r'```.*?```', re.DOTALL)
        self.mathblock_dollar_re = re.compile(r'\$\$[\s\S]*?\$\$')
        self.mathblock_bracket_re = re.compile(r'\\\[[\s\S]*?\\\]')
        self.inline_math_re = re.compile(
            r'(?<![a-zA-Z0-9])\$[^\$\n]+\$(?![a-zA-Z0-9])|'
            r'(?<![a-zA-Z0-9])\\\([^\\\n]+\\\)(?![a-zA-Z0-9])'
        )
        self.inline_code_re = re.compile(r'`([^`]+)`')
        self.link_re = re.compile(r'\[([^\n\]]+)\]\(([^)]+)\)')
        self.image_re = re.compile(r'!\[([^\n\]]*)\]\(([^)]+)\)', re.DOTALL)

        # 新增：删除 <div> 标签（开始和结束），保留内容
        self.div_tag_re = re.compile(r'</?div[^>]*>', re.IGNORECASE)
        # 新增：保护 <img> 标签
        self.img_tag_re = re.compile(r'<img[^>]*>', re.IGNORECASE)

    def _next(self, name: str) -> str:
        pid = self.counters[name]
        self.counters[name] += 1
        hex_str = f"{pid:05X}"
        type_upper = name.upper()
        return f"<{type_upper}{hex_str}/>"

    def protect(self, text: str) -> Tuple[str, Dict[str, str]]:
        self.mapping = {}

        # 删除 <details>、<sub>、<sup> 标签
        text = self.details_re.sub('', text)
        text = re.sub(r'<sub[^>]*>|</sub>', '', text, flags=re.IGNORECASE)
        text = re.sub(r'<sup[^>]*>|</sup>', '', text, flags=re.IGNORECASE)

        # ---- 删除 <div> 标签（保留内容） ----
        text = self.div_tag_re.sub('', text)

        # ---- 保护 <img> 标签（使用 'image' 计数器） ----
        def replace_html_img(m):
            placeholder = self._next('image')
            self.mapping[placeholder] = m.group(0)
            return placeholder
        text = self.img_tag_re.sub(replace_html_img, text)

        # 1. 保护 HTML 表格
        def replace_table(m):
            placeholder = self._next('table')
            self.mapping[placeholder] = m.group(0)
            return placeholder
        text = self.html_table_re.sub(replace_table, text)
        text = self.markdown_table_re.sub(replace_table, text)

        # 2. 保护代码块
        def replace_codeblock(m):
            placeholder = self._next('codeblock')
            self.mapping[placeholder] = m.group(0)
            return placeholder
        text = self.codeblock_re.sub(replace_codeblock, text)

        # 3. 保护公式块
        def replace_mathblock(m):
            placeholder = self._next('mathblock')
            self.mapping[placeholder] = m.group(0)
            return placeholder
        text = self.mathblock_dollar_re.sub(replace_mathblock, text)
        text = self.mathblock_bracket_re.sub(replace_mathblock, text)

        # 4. 保护行内公式
        def replace_math(m):
            placeholder = self._next('math')
            self.mapping[placeholder] = m.group(0)
            return placeholder
        text = self.inline_math_re.sub(replace_math, text)

        # 5. 保护行内代码
        def replace_code(m):
            placeholder = self._next('code')
            self.mapping[placeholder] = f"`{m.group(1)}`"
            return placeholder
        text = self.inline_code_re.sub(replace_code, text)

        # 6. 保护链接
        def replace_link(m):
            placeholder = self._next('link')
            self.mapping[placeholder] = f"[{m.group(1)}]({m.group(2)})"
            return placeholder
        text = self.link_re.sub(replace_link, text)

        # 7. 保护 Markdown 图片
        def replace_image(m):
            placeholder = self._next('image')
            self.mapping[placeholder] = m.group(0)
            return placeholder
        text = self.image_re.sub(replace_image, text)

        return text, self.mapping


class PreprocessMD:
    def __init__(self):
        self.protector = InlineMarkdownProtector()

    def process_folder(self, input_root: Path, output_root: Path) -> None:
        if not input_root.is_dir():
            print(f"❌ 输入目录不存在: {input_root}")
            return

        # ===== 合并 part 内所有 .md 文件并复制到 output_root（保持目录结构） =====
        print("🔄 正在合并 part 内的所有 .md 文件并复制到 output_root...")
        generated_md_files = []

        for paper_dir in input_root.iterdir():
            if not paper_dir.is_dir():
                continue
            out_paper_dir = output_root / paper_dir.name
            out_paper_dir.mkdir(parents=True, exist_ok=True)

            for part_dir in paper_dir.iterdir():
                if not part_dir.is_dir():
                    continue
                if not re.search(r'(^|_)part_\d+$', part_dir.name):
                    continue

                out_part_dir = out_paper_dir / part_dir.name
                out_part_dir.mkdir(parents=True, exist_ok=True)

                merged_filename = part_dir.name + ".md"
                md_files = sorted(
                    [f for f in part_dir.glob("*.md") if f.name != merged_filename],
                    key=lambda p: natural_sort_key(p.name)
                )

                if not md_files:
                    existing_merged = part_dir / merged_filename
                    if existing_merged.exists():
                        dst = out_part_dir / merged_filename
                        shutil.copy2(existing_merged, dst)
                        generated_md_files.append(dst)
                        print(f"   📄 复制已合并文件: {existing_merged} -> {dst}")
                    for img_dir in ["images", "imgs"]:
                        src_img = part_dir / img_dir
                        if src_img.exists() and src_img.is_dir():
                            dst_img = out_part_dir / img_dir
                            if dst_img.exists():
                                shutil.rmtree(dst_img)
                            shutil.copytree(src_img, dst_img)
                            print(f"   📁 复制图片目录: {src_img} -> {dst_img}")
                    continue

                contents = []
                for f in md_files:
                    with open(f, 'r', encoding='utf-8') as inp:
                        contents.append(inp.read())
                merged_content = '\n\n'.join(contents)

                out_md_path = out_part_dir / merged_filename
                with open(out_md_path, 'w', encoding='utf-8') as out:
                    out.write(merged_content)
                generated_md_files.append(out_md_path)
                print(f"   ✅ 合并完成: {part_dir} -> {out_md_path}")

                for img_dir in ["images", "imgs"]:
                    src_img = part_dir / img_dir
                    if src_img.exists() and src_img.is_dir():
                        dst_img = out_part_dir / img_dir
                        if dst_img.exists():
                            shutil.rmtree(dst_img)
                        shutil.copytree(src_img, dst_img)
                        print(f"   📁 复制图片目录: {src_img} -> {dst_img}")

        # ===== 保护处理 =====
        if not generated_md_files:
            print("⚠️ 未生成任何 .md 文件，跳过保护处理。")
            return

        print(f"📋 开始保护处理 {len(generated_md_files)} 个 .md 文件...")
        success = 0
        fail = 0

        for md_file in generated_md_files:
            rel_path = md_file.relative_to(output_root)
            try:
                with open(md_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                content, mapping = self.protector.protect(content)

                with open(md_file, 'w', encoding='utf-8') as f:
                    f.write(content)

                mapping_path = md_file.with_suffix('.mapping.json')
                with open(mapping_path, 'w', encoding='utf-8') as f:
                    json.dump(mapping, f, ensure_ascii=False, indent=2)

                success += 1
                print(f"   ✅ 处理完成: {rel_path}")
            except Exception as e:
                print(f"   ❌ 处理失败 {rel_path}: {e}")
                fail += 1

        print(f"🎉 预处理完成！成功: {success}, 失败: {fail}")
