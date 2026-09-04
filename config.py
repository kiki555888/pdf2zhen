#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
配置模块：使用 dataclass 定义所有全局配置项。
实际运行时会从 settings.json 中加载值并覆盖默认值。
"""

from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class Config:
    """全局配置，包含路径、API参数、翻译参数、开关等"""

    # ==================== 路径 ====================
    input_folder: str = "./pdfs"               # 原始PDF存放目录
    split_output: str = "./split_results"      # 拆分后PDF输出目录
    mineru_output: str = "./mineru_results"    # MinerU/PaddleOCR解析结果目录
    translated_output: str = "./translated_results"  # 翻译中间文件目录
    final_output: str = "./final_output"       # 最终合并输出目录

    # ==================== MinerU API ====================
    mineru_token: str = ""                     # MinerU API Token
    mineru_api_base: str = "https://mineru.net/api/v4"  # API 基础地址
    model_version: str = "vlm"                 # 模型版本
    force_ocr: Optional[bool] = None           # 是否强制OCR（None=自动）
    extra_formats: Optional[List[str]] = None  # 额外导出格式，如 ["html","docx"]
    timeout: int = 600                         # 解析超时（秒）

    # ==================== 解析引擎配置 ====================
    parse_engine: str = "mineru"               # "mineru" 或 "paddleocr" 或 "local"

    # ==================== PaddleOCR API 配置 ====================
    paddleocr_token: str = ""                  # PaddleOCR API Token
    paddleocr_api_base: str = "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs"
    paddleocr_model: str = "PaddleOCR-VL-1.6"  # 模型名称
    paddleocr_use_chart: bool = False          # 是否启用图表识别
    paddleocr_use_unwarp: bool = False         # 是否启用文档展平
    paddleocr_use_orientation: bool = False    # 是否启用方向分类

    # ==================== PDF拆分 ====================
    pages_per_file: int = 20                   # 每个拆分文件包含的页数

    # ==================== 翻译模型 ====================
    model_path: str = "./models/Hy-MT2-1.8B-Q4_K_M.gguf"  # 模型文件路径
    target_lang: str = "中文"                  # 目标语言
    n_gpu_layers: int = -1                     # GPU 层数（-1表示全部）
    n_ctx: int = 4096                          # 上下文长度
    translation_temperature: float = 0.7       # 温度参数
    translation_top_p: float = 0.6             # Top-p 采样
    translation_top_k: int = 20                # Top-k 采样
    translation_repeat_penalty: float = 1.05   # 重复惩罚
    translation_max_tokens: int = 4096         # 最大输出token数

    # ==================== Prompt 配置 ====================
    translation_glossary: str = ""             # 术语对照表（多行，每行一个对照对）
    target_style: str = ""                     # 翻译风格（如：正式专业、简洁明了）
    background_text: str = ""                  # 背景信息

    # ==================== 可选开关 ====================
    skip_mineru: bool = False                  # 是否跳过解析（使用已有结果）
    skip_translation: bool = False             # 是否跳过翻译（使用已有译文）
    # ==================== OpenAI隐藏接口 ====================
    openai_api_enabled: bool = False          # 是否启用 OpenAI 格式 API（隐藏开关）
    openai_api_key: str = ""                 # API Key
    openai_api_base: str = "https://api.deepseek.com"  # API 基础地址
    openai_model: str = "deepseek-v4-pro"      # 模型名称
    openai_timeout: int = 60                 # 超时（秒）
    openai_extra_body: str = ""   # 新增：用户自定义的 JSON 额外参数
