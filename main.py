#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
PDF沉浸式翻译全流程串联脚本
功能：按顺序执行拆分 → 解析 → 预处理 → 翻译 → 后处理 → 合并
"""
import sys
import json
import time
from pathlib import Path
from config import Config
from pdf_splitter import PDFSplitter
from mineru_parser import MinerUParser
from preprocess_md import PreprocessMD
from markdown_translator import HyMT2Translator, MarkdownTranslator
from postprocess_md import PostprocessMD
from md_merger import MdMerger


def run_pipeline(cfg: Config) -> None:
    """
    执行完整的翻译流水线
    Args:
        cfg: 全局配置对象，包含所有路径、参数、开关
    """
    print("=" * 60)
    print("开始执行 PDF 沉浸式翻译全流程")
    print("=" * 60)
    total_start = time.time()

    # ---------- 步骤1：PDF拆分（仅非本地引擎） ----------
    if cfg.parse_engine != "local":
        step_start = time.time()
        print("\n[步骤1] PDF拆分")
        print("-" * 40)
        splitter = PDFSplitter(pages_per_file=cfg.pages_per_file)
        splitter.process_folder(
            input_folder=Path(cfg.input_folder),
            output_folder=Path(cfg.split_output),
            recursive=False
        )
        print(f"✅ 步骤1 完成，耗时: {time.time() - step_start:.2f} 秒")
    else:
        print("\n[步骤1] 本地引擎：跳过PDF拆分（由步骤2处理输入文件）")
        print(f"⏭️ 步骤1 跳过，耗时: 0.00 秒")

    # ---------- 步骤2：PDF解析 ----------
    step_start = time.time()
    if not cfg.skip_mineru:
        print("\n[步骤2] PDF解析")
        print("-" * 40)
        if cfg.parse_engine == "mineru":
            from mineru_parser import MinerUParser
            parser = MinerUParser(
                token=cfg.mineru_token,
                api_base=cfg.mineru_api_base,
                model_version=cfg.model_version,
                force_ocr=cfg.force_ocr,
                timeout=cfg.timeout,
                extra_formats=cfg.extra_formats
            )
            parser.process_folder(
                split_root=Path(cfg.split_output),
                output_root=Path(cfg.mineru_output)
            )
        elif cfg.parse_engine == "paddleocr":
            from paddle_ocr_parser import PaddleOCRParser
            parser = PaddleOCRParser(
                token=cfg.paddleocr_token,
                api_base=cfg.paddleocr_api_base,
                model=cfg.paddleocr_model,
                use_chart_recognition=cfg.paddleocr_use_chart,
                use_doc_unwarping=cfg.paddleocr_use_unwarp,
                use_doc_orientation_classify=cfg.paddleocr_use_orientation,
                timeout=cfg.timeout
            )
            parser.process_folder(
                split_root=Path(cfg.split_output),
                output_root=Path(cfg.mineru_output)
            )
        else:  # local 引擎
            from local_parser import LocalParser
            parser = LocalParser(
                pages_per_file=cfg.pages_per_file,
                avg_chars_per_page=500,
            )
            parser.process_folder(
                input_folder=Path(cfg.input_folder), # 直接跳过split文件夹，从input开始处理到mineru
                output_root=Path(cfg.mineru_output)
            )
        print(f"✅ 步骤2 完成，耗时: {time.time() - step_start:.2f} 秒")
    else:
        print("\n[步骤2] 跳过解析（使用已有结果）")
        print(f"⏭️ 步骤2 跳过，耗时: 0.00 秒")

    # ---------- 步骤3：预处理MD文件 ----------
    step_start = time.time()
    print("\n[步骤3] 预处理MD文件")
    print("-" * 40)
    pre = PreprocessMD()
    pre.process_folder(
        input_root=Path(cfg.mineru_output),
        output_root=Path(cfg.translated_output)
    )
    print(f"✅ 步骤3 完成，耗时: {time.time() - step_start:.2f} 秒")

    # ---------- 步骤4：沉浸式翻译 ----------
    step_start = time.time()
    if not cfg.skip_translation:
        print("\n[步骤4] 沉浸式翻译")
        print("-" * 40)
        if cfg.openai_api_enabled:
            model_info = cfg.openai_model
        else:
            model_info = cfg.model_path
        print(f"🔧 翻译配置: API模式={cfg.openai_api_enabled}, 模型={model_info}")

        # 加载术语表（从根目录 glossary.json）
        glossary_path = Path.cwd() / "glossary.json"
        glossary_dict = {}
        if glossary_path.exists():
            try:
                with open(glossary_path, 'r', encoding='utf-8') as f:
                    glossary_dict = json.load(f)
                    if not isinstance(glossary_dict, dict):
                        glossary_dict = {}
                print(f"✅ 已加载术语表，共 {len(glossary_dict)} 条术语")
            except Exception as e:
                print(f"⚠️ 加载术语表失败: {e}")
        else:
            print("ℹ️ glossary.json 不存在，将不使用术语表")

        translator = HyMT2Translator(
            model_path=cfg.model_path,
            n_gpu_layers=cfg.n_gpu_layers,
            n_ctx=cfg.n_ctx,
            temperature=cfg.translation_temperature,
            top_p=cfg.translation_top_p,
            top_k=cfg.translation_top_k,
            repeat_penalty=cfg.translation_repeat_penalty,
            max_tokens=cfg.translation_max_tokens,
            glossary_dict=glossary_dict,
            target_style=cfg.target_style,
            background_text=cfg.background_text,
            use_api=cfg.openai_api_enabled,
            api_key=cfg.openai_api_key,
            api_base=cfg.openai_api_base,
            api_model=cfg.openai_model,
            api_timeout=cfg.openai_timeout,
            extra_body_str=cfg.openai_extra_body            
        )
        md_trans = MarkdownTranslator(translator, max_tokens=cfg.translation_max_tokens)
        md_trans.process_folder(
            input_root=Path(cfg.translated_output),
            output_root=Path(cfg.translated_output),
            target_lang=cfg.target_lang
        )
        del translator
        import gc
        gc.collect()
        print("🧹 已清理翻译模型")
        print(f"✅ 步骤4 完成，耗时: {time.time() - step_start:.2f} 秒")
    else:
        print("\n[步骤4] 跳过翻译（使用已有翻译结果）")
        print(f"⏭️ 步骤4 跳过，耗时: 0.00 秒")

    # ---------- 步骤5：还原占位符 ----------
    step_start = time.time()
    print("\n[步骤5] 还原占位符")
    print("-" * 40)
    post = PostprocessMD()
    post.process_folder(Path(cfg.translated_output))
    print(f"✅ 步骤5 完成，耗时: {time.time() - step_start:.2f} 秒")

    # ---------- 步骤6：合并MD ----------
    step_start = time.time()
    print("\n[步骤6] 合并MD文件")
    print("-" * 40)
    merger = MdMerger()
    merger.merge_folder(
        input_root=Path(cfg.translated_output),
        output_root=Path(cfg.final_output)
    )
    print(f"✅ 步骤6 完成，耗时: {time.time() - step_start:.2f} 秒")

    total_elapsed = time.time() - total_start
    print("\n" + "=" * 60)
    print("🎉 全流程执行完毕！")
    print(f"   最终输出目录: {cfg.final_output}")
    print(f"   总耗时: {total_elapsed:.2f} 秒")
    print("=" * 60)


if __name__ == "__main__":
    cfg = Config()
    # 检查 MinerU / PaddleOCR Token（与模型无关）
    if not cfg.mineru_token and cfg.parse_engine == "mineru":
        print("⚠️ 请先在 config.py 或 settings.json 中设置 mineru_token")
        sys.exit(1)
    if not cfg.paddleocr_token and cfg.parse_engine == "paddleocr":
        print("⚠️ 请先在 config.py 或 settings.json 中设置 paddleocr_token")
        sys.exit(1)

    # 始终检查本地模型文件是否存在（不启用 API清空下检查）
    if not cfg.openai_api_enabled and not Path(cfg.model_path).exists():
        print(f"⚠️ 模型文件不存在: {cfg.model_path}")
        print("   请下载 Hy-MT2 模型并放置在指定路径")
        sys.exit(1)

    run_pipeline(cfg)
