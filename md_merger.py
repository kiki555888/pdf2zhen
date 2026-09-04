#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
md_merger.py：合并同一论文下多个 part 文件夹的 MD 和图片
- 输入：translated_results/论文名/论文名_part_XXX/  内含 .md、images/ 和 imgs/
- 输出：final_output/论文名/论文名.md 和 final_output/论文名/images/ imgs/
- 特性：
  1. 每个 part 内的 .md 按文件名**自然排序**合并（确保 doc_2.md 在 doc_10.md 前）
  2. 所有 part 按自然顺序拼接
  3. images/ 检查引用，只复制被引用的图片
  4. imgs/ 直接全部复制
"""

import re
import shutil
from pathlib import Path
from typing import Dict, Set


def natural_sort_key(s: str):
    """将字符串中的数字部分转为整数，用于自然排序"""
    return [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', s)]


class MdMerger:
    def merge_folder(self, input_root: Path, output_root: Path) -> None:
        """处理输入根目录下的所有论文子目录"""
        if not input_root.is_dir():
            print(f"❌ 输入目录不存在: {input_root}")
            return

        output_root.mkdir(parents=True, exist_ok=True)
        print(f"📂 开始处理目录: {input_root}")

        paper_dirs = [d for d in input_root.iterdir() if d.is_dir()]
        if not paper_dirs:
            print("⚠️ 未找到任何子目录")
            return

        for paper_dir in sorted(paper_dirs, key=lambda d: natural_sort_key(d.name)):
            paper_name = paper_dir.name
            print(f"\n📁 处理论文: {paper_name}")

            out_paper_dir = output_root / paper_name
            out_paper_dir.mkdir(parents=True, exist_ok=True)

            # 收集所有 part 目录（按自然排序）
            part_dirs = sorted([d for d in paper_dir.iterdir() if d.is_dir()],
                               key=lambda d: natural_sort_key(d.name))
            if not part_dirs:
                print(f"   ⚠️ 无 part 文件夹，跳过")
                continue

            # 存储每个 part 的合并 MD 内容和源目录路径
            part_md_contents = []
            part_src_dirs = []

            # ----- 第一步：合并 MD 内容 -----
            for part_dir in part_dirs:
                print(f"   📂 处理 part: {part_dir.name}")

                # 合并该 part 下的所有 .md 文件（自然排序）
                md_files = sorted(part_dir.glob("*.md"), key=lambda p: natural_sort_key(p.name))
                if not md_files:
                    print(f"      ⚠️ 无 .md 文件，跳过")
                    continue

                md_contents = []
                for md_file in md_files:
                    with open(md_file, 'r', encoding='utf-8') as f:
                        md_contents.append(f.read())

                part_md = '\n\n'.join(md_contents)
                part_md_contents.append(part_md)
                part_src_dirs.append(part_dir)

            if not part_md_contents:
                print(f"   ⚠️ 未收集到任何 MD 内容，跳过")
                continue

            # 合并所有 part 的内容
            final_md = '\n\n'.join(part_md_contents)

            # 写入最终 MD（先写，后续图片复制后引用路径保持不变）
            out_md = out_paper_dir / f"{paper_name}.md"
            with open(out_md, 'w', encoding='utf-8') as f:
                f.write(final_md)
            print(f"   ✅ 合并 MD: {out_md}")

            # ----- 第二步：复制图片 -----
            # 1. 从 final_md 中提取所有图片引用
            img_refs = re.findall(r'!\[.*?\]\((.*?)\)', final_md)
            images_refs = set()
            imgs_refs = set()
            for ref in img_refs:
                if ref.startswith('images/'):
                    images_refs.add(ref)
                elif ref.startswith('imgs/'):
                    imgs_refs.add(ref)

            # 2. 复制 images/ 被引用的图片
            if images_refs:
                for part_dir in part_src_dirs:
                    src_images = part_dir / "images"
                    if not src_images.exists():
                        continue
                    dst_images = out_paper_dir / "images"
                    dst_images.mkdir(parents=True, exist_ok=True)

                    for ref in images_refs:
                        src_file = part_dir / ref
                        if src_file.exists():
                            dst_file = out_paper_dir / ref
                            dst_file.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(src_file, dst_file)
                            print(f"      📄 复制图片 (引用): {ref}")
            else:
                print("      ℹ️ 无 images/ 引用，不复制图片")

            # 3. 复制 imgs/ 全部图片（不检查引用）
            dst_imgs = out_paper_dir / "imgs"
            dst_imgs.mkdir(parents=True, exist_ok=True)
            imgs_copied = False
            for part_dir in part_src_dirs:
                src_imgs = part_dir / "imgs"
                if src_imgs.exists() and src_imgs.is_dir():
                    for item in src_imgs.rglob("*"):
                        if item.is_file():
                            rel_path = item.relative_to(src_imgs)
                            dst_file = dst_imgs / rel_path
                            dst_file.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(item, dst_file)
                            imgs_copied = True
                    if imgs_copied:
                        print(f"      📁 复制全部 imgs/: {src_imgs} -> {dst_imgs}")

        print(f"\n🎉 合并完成！输出目录: {output_root}")
