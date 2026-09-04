#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
PaddleOCR API 解析模块
使用 PaddleOCR 云端 API 解析 PDF，输出 Markdown 格式
API 文档：https://aistudio.baidu.com/application/detail/12688
"""

import json
import time
import requests
from pathlib import Path
from typing import Dict, Optional


class PaddleOCRParser:
    """
    PaddleOCR API 解析器
    使用流程：
        1. 提交 PDF 文件到 PaddleOCR API
        2. 轮询任务状态
        3. 下载解析结果（Markdown + 图片）
    """
    def __init__(
        self,
        token: str,
        api_base: str = "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs",
        model: str = "PaddleOCR-VL-1.6",
        use_chart_recognition: bool = False,
        use_doc_unwarping: bool = False,
        use_doc_orientation_classify: bool = False,
        timeout: int = 600
    ):
        self.token = token
        self.api_base = api_base
        self.model = model
        self.timeout = timeout
        self.headers = {"Authorization": f"bearer {token}"}
        self.optional_payload = {
            "useDocOrientationClassify": use_doc_orientation_classify,
            "useDocUnwarping": use_doc_unwarping,
            "useChartRecognition": use_chart_recognition,
        }
        if not self.token:
            print("⚠️ PaddleOCR Token 未设置，请获取 Token")
            print("   获取地址: https://aistudio.baidu.com/application/detail/12688")

    def _submit_task(self, pdf_path: Path) -> Optional[str]:
        """提交解析任务，返回 job_id"""
        if not pdf_path.exists():
            print(f"   ❌ 文件不存在: {pdf_path}")
            return None

        print(f"   📤 提交解析任务: {pdf_path.name}")
        try:
            data = {
                "model": self.model,
                "optionalPayload": json.dumps(self.optional_payload)
            }
            with open(pdf_path, "rb") as f:
                files = {"file": f}
                response = requests.post(
                    self.api_base,
                    headers=self.headers,
                    data=data,
                    files=files,
                    timeout=30
                )
            if response.status_code != 200:
                print(f"   ❌ 提交失败: {response.status_code}")
                print(f"      {response.text}")
                return None
            result = response.json()
            job_id = result.get("data", {}).get("jobId")
            if not job_id:
                print(f"   ❌ 响应中无 job_id: {result}")
                return None
            print(f"      ✅ 任务已提交: {job_id}")
            return job_id
        except Exception as e:
            print(f"   ❌ 提交异常: {e}")
            return None

    def _wait_for_task(self, job_id: str) -> Optional[Dict]:
        """轮询任务状态，直到完成或超时"""
        url = f"{self.api_base}/{job_id}"
        start_time = time.time()
        print(f"   ⏳ 等待解析完成...")
        while (time.time() - start_time) < self.timeout:
            try:
                response = requests.get(url, headers=self.headers, timeout=10)
                if response.status_code != 200:
                    print(f"   ⚠️ 查询状态失败: {response.status_code}")
                    time.sleep(3)
                    continue
                result = response.json()
                state = result.get("data", {}).get("state")
                if state == "done":
                    print(f"      ✅ 任务完成")
                    return result.get("data", {})
                elif state == "failed":
                    error_msg = result.get("data", {}).get("errorMsg", "未知错误")
                    print(f"      ❌ 任务失败: {error_msg}")
                    return None
                elif state == "pending":
                    print(f"      ⏳ 任务排队中...")
                elif state == "running":
                    progress = result.get("data", {}).get("extractProgress", {})
                    total = progress.get("totalPages", 0)
                    extracted = progress.get("extractedPages", 0)
                    if total > 0:
                        print(f"      ⏳ 解析中: {extracted}/{total} 页")
                    else:
                        print(f"      ⏳ 解析中...")
                else:
                    print(f"      ⏳ 状态: {state}")
                time.sleep(3)
            except Exception as e:
                print(f"   ⚠️ 轮询异常: {e}")
                time.sleep(3)
        print(f"   ⚠️ 任务超时: {job_id}")
        return None

    def _download_results(self, task_data: Dict, output_dir: Path) -> bool:
        """下载解析结果（Markdown + 图片）"""
        try:
            result_url = task_data.get("resultUrl", {})
            jsonl_url = result_url.get("jsonUrl")
            if not jsonl_url:
                print(f"   ❌ 未找到结果 URL")
                return False

            jsonl_response = requests.get(jsonl_url, timeout=60)
            jsonl_response.raise_for_status()
            lines = jsonl_response.text.strip().split('\n')
            page_num = 0
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    result = data.get("result", {})
                    layout_results = result.get("layoutParsingResults", [])
                    for res in layout_results:
                        markdown_data = res.get("markdown", {})
                        md_text = markdown_data.get("text", "")
                        # 保存 Markdown
                        md_path = output_dir / f"doc_{page_num}.md"
                        with open(md_path, 'w', encoding='utf-8') as f:
                            f.write(md_text)
                        print(f"      📄 生成 MD: {md_path}")
                        # 保存图片
                        images = markdown_data.get("images", {})
                        for img_path, img_url in images.items():
                            if img_url:
                                full_img_path = output_dir / img_path
                                full_img_path.parent.mkdir(parents=True, exist_ok=True)
                                try:
                                    img_response = requests.get(img_url, timeout=30)
                                    img_response.raise_for_status()
                                    with open(full_img_path, "wb") as f:
                                        f.write(img_response.content)
                                    print(f"      📁 保存图片: {full_img_path}")
                                except Exception as e:
                                    print(f"      ⚠️ 保存图片失败 {img_path}: {e}")
                        # 保存额外输出图片
                        output_images = res.get("outputImages", {})
                        for img_name, img_url in output_images.items():
                            if img_url:
                                try:
                                    img_response = requests.get(img_url, timeout=30)
                                    img_response.raise_for_status()
                                    img_path = output_dir / f"{img_name}_{page_num}.jpg"
                                    with open(img_path, "wb") as f:
                                        f.write(img_response.content)
                                    print(f"      📁 保存图片: {img_path}")
                                except Exception as e:
                                    print(f"      ⚠️ 保存图片失败 {img_name}: {e}")
                        page_num += 1
                except Exception as e:
                    print(f"   ⚠️ 处理结果失败: {e}")
                    continue
            print(f"      📁 结果已保存到: {output_dir}")
            return True
        except Exception as e:
            print(f"   ❌ 下载结果失败: {e}")
            return False

    def parse_pdf(self, pdf_path: Path, output_dir: Path) -> bool:
        """解析单个 PDF 文件"""
        job_id = self._submit_task(pdf_path)
        if not job_id:
            return False
        task_data = self._wait_for_task(job_id)
        if not task_data:
            return False
        output_dir.mkdir(parents=True, exist_ok=True)
        return self._download_results(task_data, output_dir)

    def process_folder(self, split_root: Path, output_root: Path) -> None:
        """批量处理拆分后的 PDF 文件夹"""
        if not split_root.is_dir():
            print(f"❌ 拆分文件夹不存在: {split_root}")
            return
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
        print(f"🧠 使用 PaddleOCR API (模型: {self.model})")
        print(f"📊 图表识别: {'启用' if self.optional_payload.get('useChartRecognition') else '禁用'}")
        print(f"📄 文档展平: {'启用' if self.optional_payload.get('useDocUnwarping') else '禁用'}")
        print(f"🔄 方向分类: {'启用' if self.optional_payload.get('useDocOrientationClassify') else '禁用'}")
        print()

        total_success = 0
        total_failed = 0

        for original_name, pdf_paths in pdf_files_by_folder.items():
            print(f"📁 处理原始PDF: {original_name} (含 {len(pdf_paths)} 个拆分文件)")
            for idx, pdf_path in enumerate(pdf_paths, 1):
                print(f"   [{idx}/{len(pdf_paths)}] 处理: {pdf_path.name}")
                part_output_dir = output_root / original_name / pdf_path.stem
                part_output_dir.mkdir(parents=True, exist_ok=True)
                if self.parse_pdf(pdf_path, part_output_dir):
                    total_success += 1
                else:
                    total_failed += 1
            print(f"   ✅ 文件夹 {original_name} 处理完成\n")

        print(f"🎉 全部处理完成！成功: {total_success}, 失败: {total_failed}")
