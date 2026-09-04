#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
PDF 合并模块（简化版）
功能：将 pdfs 文件夹内的所有图片和 PDF 文件按文件名自然排序合并为一个 PDF
流程：根目录生成 → 清空源文件夹 → 移动到源文件夹
- 图片：保持原始分辨率，仅在必要时缩放到适应页面（不放大）
- PDF：按页面尺寸缩放并居中
动态进度显示（输出到终端）
支持格式：.jpg, .jpeg, .png, .bmp, .gif, .tiff, .pdf
"""

import re
import shutil
import sys
import time
from pathlib import Path
from typing import List, Optional, Tuple

try:
    from PIL import Image
except ImportError:
    print("⚠️ 请安装 Pillow: pip install Pillow")
    sys.exit(1)

try:
    from pypdf import PdfWriter, PdfReader
    from pypdf.generic import RectangleObject
    from pypdf import Transformation
except ImportError:
    print("⚠️ 请安装 pypdf: pip install pypdf")
    sys.exit(1)


def natural_sort_key(filename: str) -> List:
    """自然排序键函数：将文件名中的数字部分转为整数"""
    def convert(text):
        return int(text) if text.isdigit() else text.lower()
    return [convert(c) for c in re.split(r'(\d+)', filename)]


def format_progress(current: int, total: int, bar_width: int = 30) -> str:
    """格式化进度条"""
    if total == 0:
        return "[ 0% ]"
    percent = current / total
    filled = int(bar_width * percent)
    bar = "█" * filled + "░" * (bar_width - filled)
    return f"[{bar}] {percent*100:5.1f}% ({current}/{total})"


class PDFMerger:
    """PDF 合并器：统一页面尺寸，图片保留原始分辨率（仅缩小不放大）"""

    PAGE_SIZES = {
        "A4": (595.28, 841.89),
        "A3": (841.89, 1190.55),
        "A5": (419.53, 595.28),
        "LETTER": (612, 792),
        "LEGAL": (612, 1008),
    }

    IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.bmp', '.gif', '.tiff', '.tif'}

    def __init__(self, input_folder: Path = Path("pdfs"), root_dir: Optional[Path] = None,
                 page_size: str = "A4", margin: int = 5,
                 crop_whitespace: bool = True):
        self.input_folder = Path(input_folder)
        self.root_dir = Path(root_dir) if root_dir else Path.cwd()
        self.margin = margin
        self.crop_whitespace = crop_whitespace

        if page_size in self.PAGE_SIZES:
            self.page_width, self.page_height = self.PAGE_SIZES[page_size]
            self.page_size_name = page_size
        else:
            try:
                w, h = page_size.split('x')
                self.page_width, self.page_height = float(w), float(h)
                self.page_size_name = f"{w}x{h}"
            except:
                print(f"⚠️ 无效的页面尺寸: {page_size}，使用默认 A4")
                self.page_width, self.page_height = self.PAGE_SIZES["A4"]
                self.page_size_name = "A4"

        if not self.input_folder.exists():
            raise FileNotFoundError(f"输入文件夹不存在: {self.input_folder}")

    def _get_supported_files(self) -> List[Path]:
        """获取输入文件夹中所有支持的图片和 PDF 文件，并按自然排序"""
        files = []
        for f in self.input_folder.iterdir():
            if f.is_file():
                suffix = f.suffix.lower()
                if suffix in self.IMAGE_EXTENSIONS or suffix == '.pdf':
                    files.append(f)
        if not files:
            print(f"⚠️ 文件夹中未找到支持的图片或 PDF 文件: {self.input_folder}")
            return []
        files.sort(key=lambda x: natural_sort_key(x.name))
        return files

    def _get_content_area(self) -> Tuple[float, float]:
        """计算内容区域（页面尺寸减去边距）"""
        return (self.page_width - 2 * self.margin,
                self.page_height - 2 * self.margin)

    def _scale_and_center_image(self, image_path: Path) -> Optional[bytes]:
        """处理图片：保留原始分辨率，仅在图片超出内容区域时等比例缩小，居中粘贴到页面"""
        try:
            with Image.open(image_path) as img:
                # 处理透明背景
                if img.mode in ('RGBA', 'LA', 'P'):
                    bg = Image.new('RGB', img.size, (255, 255, 255))
                    if img.mode == 'P':
                        img = img.convert('RGBA')
                    bg.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                    img = bg
                elif img.mode != 'RGB':
                    img = img.convert('RGB')

                target_w, target_h = self._get_content_area()
                orig_w, orig_h = img.size

                # 计算缩放因子：最大为1（不放大），仅当图片超出内容区域时缩小
                scale = min(1.0, target_w / orig_w, target_h / orig_h)
                new_w = int(orig_w * scale)
                new_h = int(orig_h * scale)

                # 缩放图片（仅当需要缩小）
                if scale != 1.0:
                    img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

                # 创建白底背景并居中粘贴
                bg_img = Image.new('RGB', (int(self.page_width), int(self.page_height)), (255, 255, 255))
                x = (int(self.page_width) - new_w) // 2
                y = (int(self.page_height) - new_h) // 2
                bg_img.paste(img, (x, y))

                from io import BytesIO
                pdf_bytes = BytesIO()
                bg_img.save(pdf_bytes, format='PDF', dpi=(96, 96), compression="tiff_deflate")
                return pdf_bytes.getvalue()
        except Exception as e:
            print(f"   ❌ 处理图片失败 {image_path.name}: {e}")
            return None

    def _crop_page_whitespace(self, page) -> Tuple[float, float, float, float]:
        """检测 PDF 页面的裁剪框并计算白边（左、上、右、下）"""
        if not self.crop_whitespace:
            return (0, 0, 0, 0)
        try:
            crop_box = page.get('/CropBox')
            media_box = page.get('/MediaBox')
            if crop_box is not None and media_box is not None:
                left = float(crop_box[0]) - float(media_box[0])
                bottom = float(crop_box[1]) - float(media_box[1])
                right = float(media_box[2]) - float(crop_box[2])
                top = float(media_box[3]) - float(crop_box[3])
                if left > 0.5 or bottom > 0.5 or right > 0.5 or top > 0.5:
                    return (left, top, right, bottom)
            return (0, 0, 0, 0)
        except Exception:
            return (0, 0, 0, 0)

    def _scale_and_center_pdf_page(self, page) -> None:
        """等比例缩放并居中 PDF 页面（直接修改页面对象）"""
        orig_box = page.mediabox
        orig_w = float(orig_box.width)
        orig_h = float(orig_box.height)

        left, top, right, bottom = self._crop_page_whitespace(page)
        content_w = orig_w - left - right
        content_h = orig_h - top - bottom

        if content_w < 10 or content_h < 10:
            content_w, content_h = orig_w, orig_h
            left, top = 0, 0

        target_w, target_h = self._get_content_area()

        # 等比例缩放：统一缩放因子
        scale = min(target_w / content_w, target_h / content_h)
        new_w = content_w * scale
        new_h = content_h * scale

        # 居中偏移（考虑白边偏移）
        offset_x = (self.page_width - new_w) / 2 - left * scale
        offset_y = (self.page_height - new_h) / 2 - bottom * scale

        # 应用变换（先缩放，再平移到居中位置）
        page.add_transformation(
            Transformation().scale(sx=scale, sy=scale).translate(tx=offset_x, ty=offset_y)
        )
        page.mediabox = RectangleObject((0, 0, self.page_width, self.page_height))

    def _clear_folder(self, folder: Path) -> None:
        """清空文件夹内容"""
        if not folder.exists():
            return
        for item in folder.iterdir():
            try:
                if item.is_file():
                    item.unlink()
                elif item.is_dir():
                    shutil.rmtree(item)
            except Exception as e:
                print(f"   ⚠️ 删除失败 {item.name}: {e}")

    def _print_terminal(self, *args, **kwargs):
        """打印到原始终端（不受 GUI 重定向影响）"""
        print(*args, **kwargs, file=sys.__stdout__)

    def merge(self) -> bool:
        """执行合并，返回是否成功"""
        files = self._get_supported_files()
        if not files:
            return False

        # 生成临时输出文件名（基于第一个文件）
        first_name = files[0].stem
        temp_pdf_path = self.root_dir / f"{first_name}.pdf"
        counter = 1
        while temp_pdf_path.exists():
            temp_pdf_path = self.root_dir / f"{first_name}_{counter}.pdf"
            counter += 1
        if counter > 1:
            self._print_terminal(f"   ⚠️ 输出文件已存在，使用: {temp_pdf_path.name}")

        writer = PdfWriter()
        success_count = 0
        fail_count = 0
        total_files = len(files)

        self._print_terminal(f"📄 发现 {total_files} 个文件，第一个: {files[0].name}")
        self._print_terminal(f"📐 页面尺寸: {self.page_size_name} ({self.page_width:.1f} x {self.page_height:.1f} 点)")
        self._print_terminal(f"📐 内容区域: {self._get_content_area()[0]:.1f} x {self._get_content_area()[1]:.1f} 点")
        self._print_terminal(f"📐 图片缩放: 保留原始分辨率（仅缩小不放大）")
        self._print_terminal(f"📐 自动裁剪: {'启用（逐页检测）' if self.crop_whitespace else '禁用'}")
        self._print_terminal(f"📝 临时输出文件: {temp_pdf_path.name}")
        self._print_terminal(f"🔄 开始合并...\n")

        start_time = time.time()

        for idx, file_path in enumerate(files, 1):
            self._print_terminal(f"\r{format_progress(idx, total_files)} 处理: {file_path.name[:40]:<40}", end="")
            sys.__stdout__.flush()

            try:
                suffix = file_path.suffix.lower()
                if suffix == '.pdf':
                    reader = PdfReader(file_path)
                    for page in reader.pages:
                        self._scale_and_center_pdf_page(page)
                        writer.add_page(page)
                    success_count += 1
                elif suffix in self.IMAGE_EXTENSIONS:
                    page_data = self._scale_and_center_image(file_path)
                    if page_data is None:
                        fail_count += 1
                        continue
                    from io import BytesIO
                    reader = PdfReader(BytesIO(page_data))
                    for page in reader.pages:
                        writer.add_page(page)
                    success_count += 1
                else:
                    fail_count += 1
            except Exception as e:
                self._print_terminal(f"\n   ❌ 处理失败 {file_path.name}: {e}")
                fail_count += 1

        elapsed = time.time() - start_time
        self._print_terminal(f"\n\n✅ 合并完成！耗时: {elapsed:.1f} 秒")
        self._print_terminal(f"   总页数: {len(writer.pages)}")
        self._print_terminal(f"   成功: {success_count} 个, 失败: {fail_count} 个")

        if not writer.pages:
            self._print_terminal("⚠️ 没有成功添加任何页面")
            return False

        try:
            with open(temp_pdf_path, 'wb') as f:
                writer.write(f)
            self._print_terminal(f"   📁 临时输出: {temp_pdf_path}")
        except Exception as e:
            self._print_terminal(f"❌ 写入临时 PDF 失败: {e}")
            return False

        # 清空源文件夹并移动最终文件
        self._print_terminal(f"\n🗑️ 清空源文件夹: {self.input_folder}")
        self._clear_folder(self.input_folder)
        final_pdf_path = self.input_folder / temp_pdf_path.name
        try:
            shutil.move(str(temp_pdf_path), str(final_pdf_path))
            self._print_terminal(f"📁 已移动到: {final_pdf_path}")
        except Exception as e:
            self._print_terminal(f"⚠️ 移动文件失败: {e}")
            self._print_terminal(f"   PDF 保留在: {temp_pdf_path}")

        return True
