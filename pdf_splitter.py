#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
PDF拆分模块：将大 PDF 按页数拆分成多个小文件
"""

from pathlib import Path
from typing import List, Dict
from pypdf import PdfReader, PdfWriter


class PDFSplitter:
    def __init__(self, pages_per_file: int = 20):
        self.pages_per_file = pages_per_file

    def split_single(self, input_pdf: Path, output_dir: Path) -> bool:
        """拆分单个 PDF，输出到指定目录"""
        try:
            reader = PdfReader(input_pdf)
            total_pages = len(reader.pages)
            if total_pages == 0:
                print(f"   ⚠️ 跳过空PDF: {input_pdf.name}")
                return False

            output_dir.mkdir(parents=True, exist_ok=True)
            base_name = input_pdf.stem

            for start in range(0, total_pages, self.pages_per_file):
                end = min(start + self.pages_per_file, total_pages)
                writer = PdfWriter()
                for page_num in range(start, end):
                    writer.add_page(reader.pages[page_num])

                part_num = start // self.pages_per_file + 1
                output_filename = f"{base_name}_part_{part_num:03d}.pdf"
                output_path = output_dir / output_filename

                with open(output_path, "wb") as f:
                    writer.write(f)

                print(f"      ✅ 生成: {output_filename} (页 {start+1}-{end})")

            total_parts = (total_pages + self.pages_per_file - 1) // self.pages_per_file
            print(f"   ✅ 拆分完成: {input_pdf.name} (共 {total_parts} 个文件)")
            return True
        except Exception as e:
            print(f"   ❌ 拆分失败 {input_pdf.name}: {e}")
            return False

    def process_folder(self, input_folder: Path, output_folder: Path, recursive: bool = False) -> Dict[str, List[Path]]:
        """批量拆分文件夹内所有PDF，返回拆分文件映射"""
        if not input_folder.is_dir():
            print(f"❌ 输入文件夹不存在: {input_folder}")
            return {}

        pdf_files = list(input_folder.rglob("*.pdf")) if recursive else list(input_folder.glob("*.pdf"))
        if not pdf_files:
            print("⚠️ 未找到任何PDF文件。")
            return {}

        print(f"📂 共发现 {len(pdf_files)} 个PDF文件，开始拆分...\n")
        split_files_map = {}

        for idx, pdf_file in enumerate(pdf_files, 1):
            print(f"[{idx}/{len(pdf_files)}] 正在处理: {pdf_file.name}")
            output_subdir = output_folder / pdf_file.stem
            success = self.split_single(pdf_file, output_subdir)
            if success:
                split_files = sorted(output_subdir.glob("*.pdf"))
                split_files_map[pdf_file.stem] = split_files
            print()

        print(f"🎉 所有PDF拆分完成！共处理 {len(pdf_files)} 个文件")
        return split_files_map
