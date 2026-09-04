#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
MinerU API 解析模块（仅支持本地文件批量上传解析）
API 文档：https://mineru.net/apiManage/docs
"""

import time
import zipfile
import requests
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from pypdf import PdfReader


class MinerUParser:
    """
    MinerU API 解析器（仅本地文件批量上传）
    使用流程：
        1. 调用 /api/v4/file-urls/batch 申请上传链接
        2. 使用 PUT 请求上传本地文件
        3. 系统自动提交解析任务
        4. 通过 /api/v4/extract-results/batch/{batch_id} 轮询结果
        5. 下载并解压结果压缩包
    """
    def __init__(self, token: str, api_base: str = "https://mineru.net/api/v4",
                 model_version: str = "vlm", force_ocr: Optional[bool] = None,
                 timeout: int = 600,
                 extra_formats: Optional[List[str]] = None):
        self.token = token
        self.api_base = api_base
        self.model_version = model_version
        self.force_ocr = force_ocr
        self.timeout = timeout
        self.extra_formats = extra_formats or []

        self.upload_url = f"{api_base}/file-urls/batch"
        self.result_url = f"{api_base}/extract-results/batch"
        self.headers = {"Authorization": f"Bearer {token}"}

    @staticmethod
    def _pdf_has_text_layer(pdf_path: Path) -> bool:
        """检测 PDF 是否包含文本层（用于自动判断是否需要 OCR）"""
        try:
            reader = PdfReader(pdf_path)
            if len(reader.pages) == 0:
                return False
            sample_text = ""
            for i in range(min(3, len(reader.pages))):
                page = reader.pages[i]
                text = page.extract_text()
                if text:
                    sample_text += text
            return len(sample_text.strip()) > 20
        except Exception:
            return False

    def _batch_check_text_layer(self, pdf_paths: List[Path]) -> Dict[Path, bool]:
        """批量检测 PDF 文本层"""
        return {p: self._pdf_has_text_layer(p) for p in pdf_paths}

    def _upload_batch(self, pdf_paths: List[Path]) -> Tuple[Optional[str], Dict[Path, bool]]:
        """批量申请上传链接并上传文件，返回 (batch_id, 文本层状态字典)"""
        if not pdf_paths:
            return None, {}

        # 检测文本层，自动判断是否需要 OCR
        print(f"   🔍 正在检测 {len(pdf_paths)} 个PDF的文本层...")
        text_layer_status = self._batch_check_text_layer(pdf_paths)
        need_ocr_count = sum(1 for v in text_layer_status.values() if not v)
        print(f"   📊 检测结果: {need_ocr_count}/{len(pdf_paths)} 个文件需要OCR")

        if self.force_ocr is not None:
            use_ocr = self.force_ocr
            print(f"   🔧 使用强制设置: OCR = {use_ocr}")
        else:
            use_ocr = need_ocr_count > 0
            print(f"   {'⚠️ 部分文件不含文本层，开启OCR' if use_ocr else '✅ 所有文件均含文本层，关闭OCR'}")

        # 构建请求体
        files_info = [{"name": p.name, "data_id": p.stem} for p in pdf_paths]
        data = {
            "files": files_info,
            "model_version": self.model_version,
            "is_ocr": use_ocr,
            "language": "ch",
            "enable_formula": True,
            "enable_table": True,
        }
        if self.extra_formats:
            data["extra_formats"] = self.extra_formats
            print(f"   📄 额外导出格式: {', '.join(self.extra_formats)}")

        headers = {"Content-Type": "application/json", **self.headers}

        try:
            # 1. 申请上传链接
            resp = requests.post(self.upload_url, headers=headers, json=data)
            if resp.status_code != 200:
                print(f"   ❌ 申请上传链接失败: {resp.status_code}")
                return None, text_layer_status

            result = resp.json()
            if result.get("code") != 0:
                print(f"   ❌ 申请上传链接业务失败: {result.get('msg')}")
                return None, text_layer_status

            batch_id = result["data"]["batch_id"]
            urls = result["data"]["file_urls"]

            # 2. 上传文件（使用 PUT）
            for i, url in enumerate(urls):
                pdf_path = pdf_paths[i]
                try:
                    with open(pdf_path, "rb") as f:
                        put_resp = requests.put(url, data=f)
                        if put_resp.status_code == 200:
                            print(f"      ✅ 上传成功: {pdf_path.name}")
                        else:
                            print(f"      ❌ 上传失败 {pdf_path.name}: {put_resp.status_code}")
                except Exception as e:
                    print(f"      ❌ 上传异常 {pdf_path.name}: {e}")

            print(f"   📦 批次上传完成，batch_id: {batch_id}, OCR: {use_ocr}")
            return batch_id, text_layer_status
        except Exception as e:
            print(f"   ❌ 批量请求异常: {e}")
            return None, text_layer_status

    def _wait_for_results(self, batch_id: str) -> Dict[str, Dict]:
        """轮询解析结果，返回 data_id -> 结果字典的映射"""
        url = f"{self.result_url}/{batch_id}"
        start_time = time.time()
        completed = {}

        while (time.time() - start_time) < self.timeout:
            try:
                resp = requests.get(url, headers=self.headers)
                if resp.status_code != 200:
                    print(f"   ⚠️ 查询结果失败: {resp.status_code}")
                    time.sleep(5)
                    continue

                result = resp.json()
                if result.get("code") != 0:
                    print(f"   ⚠️ 查询结果业务失败: {result.get('msg')}")
                    time.sleep(5)
                    continue

                extract_results = result.get("data", {}).get("extract_result", [])
                if not extract_results:
                    print(f"   ⏳ 暂无解析结果，继续等待...")
                    time.sleep(5)
                    continue

                all_done = True
                for item in extract_results:
                    data_id = item.get("data_id")
                    state = item.get("state")
                    if state in ("done", "failed"):
                        if data_id not in completed:
                            completed[data_id] = item
                            if state == "done":
                                print(f"      ✅ 解析完成: {data_id}")
                            else:
                                print(f"      ❌ 解析失败: {data_id}, 原因: {item.get('err_msg')}")
                    else:
                        all_done = False
                        if state == "running":
                            progress = item.get("extract_progress", {})
                            extracted = progress.get("extracted_pages", 0)
                            total = progress.get("total_pages", 0)
                            print(f"      ⏳ 解析中: {data_id} ({extracted}/{total} 页)")

                if all_done and len(completed) == len(extract_results):
                    print(f"   ✅ 批次 {batch_id} 全部处理完成")
                    return completed

                time.sleep(5)
            except Exception as e:
                print(f"   ⚠️ 查询结果异常: {e}")
                time.sleep(5)

        print(f"   ⚠️ 超时，batch_id: {batch_id} 未完成")
        return completed

    def _download_and_extract(self, data_id: str, zip_url: str, output_dir: Path) -> bool:
        """下载并解压结果压缩包"""
        try:
            resp = requests.get(zip_url, stream=True)
            if resp.status_code != 200:
                print(f"      ❌ 下载失败 {data_id}: {resp.status_code}")
                return False

            zip_path = output_dir / f"{data_id}.zip"
            with open(zip_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)

            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(output_dir)
            zip_path.unlink()

            print(f"      📁 解压结果到: {output_dir}")
            return True
        except Exception as e:
            print(f"      ❌ 下载/解压异常 {data_id}: {e}")
            return False

    def process_folder(self, split_root: Path, output_root: Path) -> None:
        """批量处理拆分后的 PDF 文件夹"""
        if not split_root.is_dir():
            print(f"❌ 拆分文件夹不存在: {split_root}")
            return

        # 收集所有 PDF 文件，按原始 PDF 名分组
        pdf_files_by_folder = {}
        for sub_dir in split_root.iterdir():
            if sub_dir.is_dir():
                pdf_files = sorted(sub_dir.glob("*.pdf"))
                if pdf_files:
                    pdf_files_by_folder[sub_dir.name] = pdf_files

        if not pdf_files_by_folder:
            print("⚠️ 未找到任何PDF拆分文件。")
            return

        print(f"\n📂 共发现 {len(pdf_files_by_folder)} 个原始PDF的拆分文件夹")
        print(f"🧠 模型版本: {self.model_version}, OCR设置: {'自动' if self.force_ocr is None else ('强制开启' if self.force_ocr else '强制关闭')}")
        if self.extra_formats:
            print(f"📄 额外导出格式: {', '.join(self.extra_formats)}")
        else:
            print("📄 默认导出格式: Markdown + JSON")
        print()

        total_success = 0
        total_failed = 0

        for original_name, pdf_paths in pdf_files_by_folder.items():
            print(f"📁 处理原始PDF: {original_name} (含 {len(pdf_paths)} 个拆分文件)")
            # 单次申请链接不能超过 50 个
            batch_size = 50
            for i in range(0, len(pdf_paths), batch_size):
                batch_paths = pdf_paths[i:i+batch_size]
                print(f"   📤 上传第 {i//batch_size + 1} 批 ({len(batch_paths)} 个文件)")

                batch_id, _ = self._upload_batch(batch_paths)
                if not batch_id:
                    total_failed += len(batch_paths)
                    continue

                print(f"   ⏳ 等待解析完成...")
                completed = self._wait_for_results(batch_id)

                for pdf_path in batch_paths:
                    data_id = pdf_path.stem
                    if data_id not in completed:
                        total_failed += 1
                        continue
                    item = completed[data_id]
                    if item.get("state") != "done":
                        total_failed += 1
                        continue
                    zip_url = item.get("full_zip_url")
                    if not zip_url:
                        total_failed += 1
                        continue

                    part_output_dir = output_root / original_name / pdf_path.stem
                    part_output_dir.mkdir(parents=True, exist_ok=True)
                    if self._download_and_extract(data_id, zip_url, part_output_dir):
                        total_success += 1
                    else:
                        total_failed += 1

            print(f"   ✅ 文件夹 {original_name} 处理完成\n")

        print(f"🎉 全部处理完成！成功: {total_success}, 失败: {total_failed}")
