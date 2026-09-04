#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
清理模块：提供两种清理方式
1. 删除整个目录（目录本身被移除）
2. 清空目录内容（保留目录）
用于清理中间文件，释放磁盘空间。
"""

import shutil
from pathlib import Path
from typing import List, Tuple


def clean_directories(
    dirs: List[str],
    base_path: Path = None,
    confirm: bool = True
) -> Tuple[List[str], List[Tuple[str, str]]]:
    """
    删除指定的目录列表（目录本身也被删除）。
    Args:
        dirs: 目录名称列表（相对 base_path）
        base_path: 基础路径，默认为当前工作目录
        confirm: 是否交互确认（当前未使用，保留接口）
    Returns:
        (成功删除的目录路径列表, 失败项列表[(路径, 错误信息)])
    """
    if base_path is None:
        base_path = Path.cwd()
    base_path = Path(base_path)

    success = []
    failed = []

    for d in dirs:
        target = base_path / d
        # 如果目录不存在，视为成功（不报错）
        if not target.exists():
            success.append(str(target))
            continue

        try:
            # 递归删除整个目录树
            shutil.rmtree(target)
            success.append(str(target))
        except Exception as e:
            failed.append((str(target), str(e)))

    return success, failed


def clear_directories_contents(
    dirs: List[str],
    base_path: Path = None
) -> Tuple[List[str], List[Tuple[str, str]]]:
    """
    清空指定目录的内容（删除所有文件和子文件夹），但保留目录本身。
    如果目录不存在，则不做任何事（视为成功）。
    Args:
        dirs: 目录名称列表（相对 base_path）
        base_path: 基础路径，默认为当前工作目录
    Returns:
        (成功清空的目录路径列表, 失败项列表[(路径, 错误信息)])
    """
    if base_path is None:
        base_path = Path.cwd()
    base_path = Path(base_path)

    success = []
    failed = []

    for d in dirs:
        target = base_path / d
        if not target.exists():
            # 目录不存在，视为成功
            success.append(str(target))
            continue

        try:
            # 遍历目录下所有内容并删除
            for item in target.iterdir():
                if item.is_file():
                    item.unlink()          # 删除文件
                else:
                    shutil.rmtree(item)    # 删除子目录
            success.append(str(target))
        except Exception as e:
            failed.append((str(target), str(e)))

    return success, failed
