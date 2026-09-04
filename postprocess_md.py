#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
还原占位符模块：将翻译后的 MD 文件中的占位符替换为原始内容
映射文件：与 MD 同目录、同名的 .mapping.json
增强功能：
1. 将 mapping 中存储的 HTML 表格（<table>...</table>）转换为 Markdown 表格
2. 分组替换（每 128 个一组），提供动态进度
3. 替换数量不足时发出警告
"""

import json
import html.parser
from pathlib import Path
from typing import Dict, List


class HTMLTableToMarkdown(html.parser.HTMLParser):
    """简单的 HTML 表格转 Markdown 表格的解析器"""
    def __init__(self):
        super().__init__()
        self.in_table = False
        self.in_tr = False
        self.in_td = False
        self.current_row = []
        self.current_cell = []
        self.all_rows = []

    def handle_starttag(self, tag, attrs):
        if tag == 'table':
            self.in_table = True
            self.all_rows = []
        elif tag == 'tr':
            self.in_tr = True
            self.current_row = []
        elif tag == 'td':
            self.in_td = True
            self.current_cell = []

    def handle_endtag(self, tag):
        if tag == 'td':
            cell_text = ''.join(self.current_cell).strip()
            self.current_row.append(cell_text)
            self.current_cell = []
            self.in_td = False
        elif tag == 'tr':
            if self.in_tr:
                self.all_rows.append(self.current_row)
                self.current_row = []
                self.in_tr = False
        elif tag == 'table':
            self.in_table = False

    def handle_data(self, data):
        if self.in_td:
            self.current_cell.append(data)

    def get_markdown(self) -> str:
        """将解析出的表格转换为 Markdown 格式"""
        if not self.all_rows:
            return ''
        header = self.all_rows[0]
        num_cols = len(header)
        body = self.all_rows[1:] if len(self.all_rows) > 1 else []
        # 补齐列数
        for i, row in enumerate(body):
            if len(row) < num_cols:
                row += [''] * (num_cols - len(row))
            elif len(row) > num_cols:
                body[i] = row[:num_cols]
        header_line = '| ' + ' | '.join(header) + ' |'
        separator = '| ' + ' | '.join(['---'] * num_cols) + ' |'
        body_lines = ['| ' + ' | '.join(row) + ' |' for row in body]
        if body_lines:
            return '\n'.join([header_line, separator] + body_lines)
        else:
            return '\n'.join([header_line, separator])


def convert_html_table_to_md(html_table: str) -> str:
    """将 HTML 表格字符串转换为 Markdown 表格字符串，失败则返回原字符串"""
    try:
        parser = HTMLTableToMarkdown()
        parser.feed(html_table)
        parser.close()
        md_table = parser.get_markdown()
        return md_table if md_table else html_table
    except Exception:
        return html_table


def is_html_table(text: str) -> bool:
    """判断文本是否以 HTML 表格开头"""
    return text.strip().startswith('<table')


class PostprocessMD:
    def process_folder(self, input_root: Path) -> None:
        """处理文件夹内所有 MD 文件及其映射"""
        if not input_root.is_dir():
            print(f"❌ 目录不存在: {input_root}")
            return

        md_files = list(input_root.rglob("*.md"))
        if not md_files:
            print("⚠️ 未找到任何 .md 文件")
            return

        print(f"📂 发现 {len(md_files)} 个 MD 文件，开始还原占位符...")
        success = 0
        fail = 0
        skipped = 0

        for md_path in md_files:
            mapping_path = md_path.with_suffix('.mapping.json')
            if not mapping_path.exists():
                print(f"   ⚠️ 跳过 {md_path.name}：未找到映射文件 {mapping_path.name}")
                skipped += 1
                continue

            try:
                with open(mapping_path, 'r', encoding='utf-8') as f:
                    mapping: Dict[str, str] = json.load(f)
                if not mapping:
                    print(f"   ℹ️ 映射为空，跳过 {md_path.name}")
                    skipped += 1
                    continue

                with open(md_path, 'r', encoding='utf-8') as f:
                    content = f.read()

                # 第一步：将映射中原始内容为 HTML 表格的转换为 Markdown 表格
                converted_mapping = {}
                for placeholder, original in mapping.items():
                    if is_html_table(original):
                        md_table = convert_html_table_to_md(original)
                        converted_mapping[placeholder] = md_table
                    else:
                        converted_mapping[placeholder] = original

                # 第二步：分组替换占位符（每 128 个一组）
                items = list(converted_mapping.items())
                total = len(items)
                batch_size = 128
                replaced_total = 0

                print(f"   🔄 开始替换 {total} 个占位符 (每 {batch_size} 个一组)")
                for i in range(0, total, batch_size):
                    batch = items[i:i + batch_size]
                    for placeholder, original in batch:
                        if placeholder in content:
                            content = content.replace(placeholder, original)
                            replaced_total += 1
                    processed = min(i + batch_size, total)
                    print(f"      ✅ 已处理 {processed}/{total} 个占位符")

                if replaced_total < total:
                    print(f"   ⚠️ 仅替换了 {replaced_total}/{total} 个占位符")

                with open(md_path, 'w', encoding='utf-8') as f:
                    f.write(content)

                print(f"   ✅ 还原成功: {md_path.name} (替换 {replaced_total} 个占位符)")
                success += 1

            except Exception as e:
                print(f"   ❌ 还原失败 {md_path.name}: {e}")
                fail += 1

        print(f"🎉 还原完成！成功: {success}, 跳过: {skipped}, 失败: {fail}")

    def restore_file(self, md_path: Path) -> bool:
        """还原单个 MD 文件（供外部调用）"""
        mapping_path = md_path.with_suffix('.mapping.json')
        if not mapping_path.exists():
            print(f"   ⚠️ 映射文件不存在: {mapping_path.name}")
            return False
        try:
            with open(mapping_path, 'r', encoding='utf-8') as f:
                mapping = json.load(f)
            if not mapping:
                return True
            with open(md_path, 'r', encoding='utf-8') as f:
                content = f.read()
            converted_mapping = {}
            for placeholder, original in mapping.items():
                if is_html_table(original):
                    md_table = convert_html_table_to_md(original)
                    converted_mapping[placeholder] = md_table
                else:
                    converted_mapping[placeholder] = original
            items = list(converted_mapping.items())
            total = len(items)
            batch_size = 128
            replaced_total = 0
            for i in range(0, total, batch_size):
                batch = items[i:i + batch_size]
                for placeholder, original in batch:
                    if placeholder in content:
                        content = content.replace(placeholder, original)
                        replaced_total += 1
            with open(md_path, 'w', encoding='utf-8') as f:
                f.write(content)
            if replaced_total < total:
                print(f"   ⚠️ {md_path.name}: 仅替换了 {replaced_total}/{total} 个占位符")
            return True
        except Exception as e:
            print(f"   ❌ 还原失败 {md_path.name}: {e}")
            return False
