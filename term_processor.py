#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
术语表处理模块
功能：
- 解析各种格式的术语表文件（TXT, CSV, TSV, Markdown 表格等）
- 智能提取中英术语对（支持多种分隔符、列格式、语言块）
- 自动判断序号列，忽略之
- 自动识别英文列和中文列，顺序不限
- 生成 en2zh 和 zh2en 两种方向的 JSON 术语表
- 支持处理单个或多个文件
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Union


# ---------- 辅助函数 ----------
def _is_chinese_char(char: str) -> bool:
    return '\u4e00' <= char <= '\u9fff'


def _extract_chinese_segments(text: str) -> List[str]:
    """提取所有连续的中文片段"""
    return re.findall(r'[\u4e00-\u9fff]+', text)


def _extract_english_segments(text: str) -> List[str]:
    """提取所有连续的英文片段（包含字母、数字、连字符、点、空格），清理多余空格"""
    parts = re.findall(r'[a-zA-Z0-9\-\.\s]+', text)
    parts = [p.strip() for p in parts if p.strip()]
    cleaned = [re.sub(r'\s+', ' ', p) for p in parts]
    return cleaned


def _detect_language(text: str) -> Optional[str]:
    if re.search(r'[\u4e00-\u9fff]', text):
        return 'zh'
    elif re.search(r'[a-zA-Z]', text):
        return 'en'
    else:
        return None


def _is_serial_number(text: str) -> bool:
    """判断文本是否像序号（含数字和分隔符），如 AITD-00000, dd000-dd001, 123 等"""
    if not text:
        return False
    return bool(re.match(r'^[A-Za-z0-9\-_]+$', text)) and any(c.isdigit() for c in text)


def _split_multi_pairs(line: str) -> List[str]:
    """将一行分割成多个候选术语对片段（传统格式）"""
    for sep in [';', '；']:
        if sep in line:
            parts = line.split(sep)
            if all(_detect_language(p) is not None for p in parts):
                return [p.strip() for p in parts if p.strip()]
    for sep in [',', '，']:
        if sep in line:
            parts = line.split(sep)
            if all(_detect_language(p) is not None for p in parts):
                return [p.strip() for p in parts if p.strip()]
    if '|' in line:
        parts = line.split('|')
        if all(_detect_language(p) is not None for p in parts):
            return [p.strip() for p in parts if p.strip()]
    return [line.strip()]


def _parse_pair_from_segment(segment: str) -> Optional[Tuple[str, str]]:
    """从单个片段中提取 (英文, 中文) 对（传统格式）"""
    separators = ['\t', '=', ',', ';', '|', '->']
    for sep in separators:
        if sep in segment:
            parts = segment.split(sep, 1)
            if len(parts) == 2:
                left, right = parts[0].strip(), parts[1].strip()
                left_lang = _detect_language(left)
                right_lang = _detect_language(right)
                if left_lang == 'zh' and right_lang == 'en':
                    return (right, left)
                elif left_lang == 'en' and right_lang == 'zh':
                    return (left, right)

    en_segments = _extract_english_segments(segment)
    zh_segments = _extract_chinese_segments(segment)
    if en_segments and zh_segments:
        if len(en_segments) == len(zh_segments):
            return (en_segments[0], zh_segments[0])
        else:
            en = ' '.join(en_segments)
            zh = ''.join(zh_segments)
            return (en, zh)
    return None


def _parse_by_columns(line: str) -> List[Tuple[str, str]]:
    """按列解析：优先 Markdown 表格（|），支持逗号、制表符、分号。忽略序号列。"""
    # 优先处理 '|' 分隔符（Markdown 表格）
    if '|' in line:
        if re.match(r'^[\s\-:|]+$', line):
            return []  # 忽略分隔行
        cols = [c.strip() for c in line.split('|')]
        cols = [c for c in cols if c]
        if len(cols) >= 2:
            if len(cols) >= 3 and _is_serial_number(cols[0]):
                col1, col2 = cols[1], cols[2]
            else:
                col1, col2 = cols[0], cols[1]
            lang1 = 'zh' if re.search(r'[\u4e00-\u9fff]', col1) else 'en'
            lang2 = 'zh' if re.search(r'[\u4e00-\u9fff]', col2) else 'en'
            if lang1 != lang2:
                return [(col2, col1)] if lang1 == 'zh' else [(col1, col2)]
        return []

    # 其他分隔符
    for sep in ['\t', ',', ';']:
        if sep in line:
            cols = [c.strip() for c in line.split(sep)]
            cols = [c for c in cols if c]
            if len(cols) >= 2:
                if len(cols) >= 3 and _is_serial_number(cols[0]):
                    col1, col2 = cols[1], cols[2]
                else:
                    col1, col2 = cols[0], cols[1]
                lang1 = 'zh' if re.search(r'[\u4e00-\u9fff]', col1) else 'en'
                lang2 = 'zh' if re.search(r'[\u4e00-\u9fff]', col2) else 'en'
                if lang1 != lang2:
                    return [(col2, col1)] if lang1 == 'zh' else [(col1, col2)]
    return []


def _parse_by_language_blocks(line: str) -> List[Tuple[str, str]]:
    """
    基于语言块解析：当行中无常见分隔符，但同时包含连续英文和连续中文时，
    提取并配对。
    """
    # 如果包含分隔符，则不适用此方法
    common_seps = ['=', '->', '\t', ',', ';', '|']
    if any(sep in line for sep in common_seps):
        return []

    en_segments = _extract_english_segments(line)
    zh_segments = _extract_chinese_segments(line)

    if not en_segments or not zh_segments:
        return []

    # 尝试按顺序配对（数量相同）
    if len(en_segments) == len(zh_segments):
        # 按顺序配对
        pairs = []
        for en, zh in zip(en_segments, zh_segments):
            if en and zh:
                pairs.append((en, zh))
        return pairs
    else:
        # 数量不同：合并所有英文和中文
        en = ' '.join(en_segments)
        zh = ''.join(zh_segments)
        if en and zh:
            return [(en, zh)]
    return []


# ---------- 公开解析函数 ----------
def parse_glossary_line(line: str) -> List[Tuple[str, str]]:
    """
    解析一行，返回术语对列表 [(en, zh), ...]
    按优先级：传统语义解析（含 = 或 ->）→ 列解析 → 语言块解析 → 回退语义解析
    """
    line = line.strip()
    if not line or line.startswith('#'):
        return []

    # 1. 如果行中包含 = 或 ->，优先使用传统语义解析（可能多个对）
    if '=' in line or '->' in line:
        candidates = _split_multi_pairs(line)
        results = []
        for cand in candidates:
            pair = _parse_pair_from_segment(cand)
            if pair:
                results.append(pair)
        if results:
            return results

    # 2. 尝试列解析（包括 Markdown 表格）
    col_results = _parse_by_columns(line)
    if col_results:
        return col_results

    # 3. 尝试基于语言块解析（无分隔符的混合中英文）
    block_results = _parse_by_language_blocks(line)
    if block_results:
        return block_results

    # 4. 最后回退到语义解析（以防万一）
    candidates = _split_multi_pairs(line)
    results = []
    for cand in candidates:
        pair = _parse_pair_from_segment(cand)
        if pair:
            results.append(pair)
    return results


def load_glossary(file_path: Union[str, Path]) -> Dict[str, Dict[str, str]]:
    """加载整个术语表文件，返回 {'en2zh': en2zh, 'zh2en': zh2en}"""
    file_path = Path(file_path)
    en2zh = {}
    zh2en = {}
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            pairs = parse_glossary_line(line)
            for en, zh in pairs:
                if en not in en2zh:
                    en2zh[en] = zh
                if zh not in zh2en:
                    zh2en[zh] = en
    return {'en2zh': en2zh, 'zh2en': zh2en}


def format_glossary(glossary: Dict[str, str]) -> str:
    """将 en2zh 字典格式化为 英文=中文 每行"""
    return '\n'.join([f"{en}={zh}" for en, zh in glossary.items()])


# ---------- 文件处理函数 ----------
def process_single_term_file(file_path: Union[str, Path], output_dir: Union[str, Path] = None) -> Dict[str, Dict[str, str]]:
    """处理单个术语表文件，生成同名 JSON 文件"""
    file_path = Path(file_path)
    if output_dir is None:
        output_dir = file_path.parent
    else:
        output_dir = Path(output_dir)
        if not output_dir.exists():
            output_dir.mkdir(parents=True, exist_ok=True)

    result = load_glossary(str(file_path))
    en2zh = result['en2zh']
    zh2en = result['zh2en']

    base = file_path.stem
    en2zh_path = output_dir / f"{base}_en2zh.json"
    zh2en_path = output_dir / f"{base}_zh2en.json"

    with open(en2zh_path, 'w', encoding='utf-8') as f:
        json.dump(en2zh, f, ensure_ascii=False, indent=2)
    with open(zh2en_path, 'w', encoding='utf-8') as f:
        json.dump(zh2en, f, ensure_ascii=False, indent=2)

    return {'en2zh': en2zh, 'zh2en': zh2en}


def process_selected_term_files(file_paths: List[Union[str, Path]], output_dir: Union[str, Path]) -> Tuple[bool, str]:
    """处理选定的多个术语表文件"""
    if not file_paths:
        return False, "未选择任何文件。"

    output_dir = Path(output_dir)
    if not output_dir.exists():
        output_dir.mkdir(parents=True, exist_ok=True)

    success_count = 0
    error_files = []
    for file_path in file_paths:
        try:
            process_single_term_file(file_path, output_dir)
            success_count += 1
        except Exception as e:
            error_files.append(f"{Path(file_path).name} ({str(e)})")

    if success_count == 0:
        return False, f"所有文件处理失败：\n" + "\n".join(error_files)

    msg = f"成功处理 {success_count} 个文件。"
    if error_files:
        msg += f"\n失败文件：{', '.join(error_files)}"
    else:
        msg += "\n所有文件处理成功。"
    msg += f"\n术语表已保存到 {output_dir} 目录。"
    return True, msg

