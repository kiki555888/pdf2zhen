#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
极简环境检测模块（仅支持 --onedir 打包模式）
- 不依赖 llama_cpp，所有导入均在 try 中
- 检测显卡类型，给出安装建议
- 检测 Pillow、pypdf 等新增依赖
- 清理 PATH 无效条目（不主动添加任何路径）
- 仅检测内置 _internal/llama_cpp/lib 中的 llama.dll（用于状态报告）
- 支持通过 REQUIRED_PACKAGES 列表灵活添加依赖包
- 显示已安装包的版本号，并显示 llama_cpp 动态库版本
- 打包环境下提示：如需切换后端（CUDA/Vulkan 等），可替换 _internal 中的 llama_cpp 文件夹
"""

import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, Optional, Tuple
import importlib.metadata


class SimpleEnvChecker:
    # ========== 依赖包配置 ==========
    REQUIRED_PACKAGES = ["pypdf", "requests", "llama_cpp", "tqdm", "Pillow", "pyahocorasick", "openai", "python-docx"]

    # 包名到导入名的映射（当包名与 import 名称不同时）
    IMPORT_NAMES = {
        "Pillow": "PIL",
        "pyahocorasick": "ahocorasick",
        "python-docx": "docx", 
    }

    WHEEL_BASE_URL = "https://abetlen.github.io/llama-cpp-python/whl"

    @staticmethod
    def prepare_path():
        """
        仅清理 PATH 中的无效条目，不主动添加任何路径。
        llama-cpp-python 通过 ctypes 使用绝对路径加载 lib/llama.dll，无需 PATH。
        """
        # 清理无效的 HIP_PATH（AMD GPU 环境变量）
        hip_path = os.environ.get("HIP_PATH", "")
        if hip_path and not os.path.exists(hip_path):
            print(f"⚠️ 已移除无效的 HIP_PATH 条目: {hip_path}")
            os.environ.pop("HIP_PATH", None)

        # 获取当前 PATH 并移除不存在的目录
        path_entries = os.environ.get("PATH", "").split(os.pathsep)
        valid_entries = [entry for entry in path_entries if os.path.exists(entry)]

        # 设置新的 PATH
        os.environ["PATH"] = os.pathsep.join(valid_entries)

    @staticmethod
    def get_package_version(pkg_name: str, import_name: str = None) -> str:
        """获取已安装包的版本号"""
        if import_name is None:
            import_name = pkg_name.replace('-', '_')
        try:
            return importlib.metadata.version(pkg_name)
        except Exception:
            try:
                module = __import__(import_name)
                if hasattr(module, '__version__'):
                    return module.__version__
                elif hasattr(module, 'version'):
                    return str(module.version)
                else:
                    return "版本未知"
            except Exception:
                return "未安装"

    @staticmethod
    def check_packages() -> Dict[str, bool]:
        """检测 REQUIRED_PACKAGES 中所有包是否安装"""
        status = {}
        for pkg in SimpleEnvChecker.REQUIRED_PACKAGES:
            import_name = SimpleEnvChecker.IMPORT_NAMES.get(pkg, pkg.replace('-', '_'))
            try:
                __import__(import_name)
                status[pkg] = True
            except ImportError:
                status[pkg] = False
        return status

    @staticmethod
    def get_cuda_version() -> Optional[str]:
        """通过 nvidia-smi 获取 CUDA 版本"""
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=cuda_version", "--format=csv,noheader"],
                capture_output=True, text=True, check=False
            )
            if result.returncode == 0:
                ver = result.stdout.strip()
                if ver:
                    return ver
            result = subprocess.run(["nvidia-smi"], capture_output=True, text=True, check=False)
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    if "CUDA Version" in line:
                        parts = line.split("CUDA Version:")
                        if len(parts) > 1:
                            ver = parts[1].strip().split()[0]
                            if ver:
                                return ver
            return None
        except Exception:
            return None

    @staticmethod
    def detect_gpu() -> Tuple[str, Optional[str]]:
        """返回 (gpu_type, version)，gpu_type 为 'nvidia', 'amd', 'none'"""
        cuda_ver = SimpleEnvChecker.get_cuda_version()
        if cuda_ver:
            return 'nvidia', cuda_ver

        try:
            result = subprocess.run(
                ["rocm-smi", "--showproductname"],
                capture_output=True, text=True, check=False
            )
            if result.returncode == 0 and "AMD" in result.stdout:
                return 'amd', None
        except:
            pass

        try:
            if sys.platform == "win32":
                result = subprocess.run(
                    ["wmic", "path", "win32_VideoController", "get", "name"],
                    capture_output=True, text=True, check=False
                )
                if "AMD" in result.stdout or "Radeon" in result.stdout:
                    return 'amd', None
        except:
            pass

        try:
            result = subprocess.run(
                ["lspci", "|", "grep", "-i", "amd"],
                shell=True, capture_output=True, text=True, check=False
            )
            if result.stdout and ("AMD" in result.stdout or "Radeon" in result.stdout):
                return 'amd', None
        except:
            pass

        return 'none', None

    @staticmethod
    def _format_cuda_tag(cuda_version: str) -> Optional[str]:
        try:
            ver_float = float(cuda_version.strip())
            ver_int = int(ver_float * 10)
            return f"cu{ver_int}"
        except Exception:
            return None

    @staticmethod
    def get_llama_cpp_info(gpu_type: str, cuda_version: Optional[str] = None) -> Dict[str, str]:
        """根据显卡类型返回 llama-cpp-python 安装建议"""
        base = SimpleEnvChecker.WHEEL_BASE_URL
        if gpu_type == 'nvidia' and cuda_version:
            cu_tag = SimpleEnvChecker._format_cuda_tag(cuda_version)
            if cu_tag:
                return {
                    "type": "nvidia",
                    "recommendation": f"CUDA {cuda_version} (下载 {cu_tag})",
                    "download_url": f"{base}/{cu_tag}",
                    "install_cmd": f"pip install llama-cpp-python --extra-index-url {base}/{cu_tag}"
                }
            return {
                "type": "nvidia",
                "recommendation": f"CUDA {cuda_version} (建议 cu121)",
                "download_url": f"{base}/cu121",
                "install_cmd": f"pip install llama-cpp-python --extra-index-url {base}/cu121"
            }
        if gpu_type == 'amd':
            return {
                "type": "amd",
                "recommendation": "AMD 显卡 (Vulkan 后端)",
                "download_url": f"{base}/vulkan",
                "install_cmd": f"pip install llama-cpp-python --extra-index-url {base}/vulkan"
            }
        return {
            "type": "cpu",
            "recommendation": "CPU 版本（无独显）",
            "download_url": f"{base}/cpu",
            "install_cmd": f"pip install llama-cpp-python --extra-index-url {base}/cpu"
        }

    @staticmethod
    def is_frozen() -> bool:
        return getattr(sys, 'frozen', False)

    @staticmethod
    def print_summary():
        """打印详细的环境检测报告（仅适用于 --onedir 打包）"""
        print("=" * 50)
        print("  环境检测摘要")
        print("=" * 50)
        print(f"Python: {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")

        gpu_type, cuda_ver = SimpleEnvChecker.detect_gpu()
        if gpu_type == 'nvidia':
            print(f"显卡:   NVIDIA (CUDA {cuda_ver})")
        elif gpu_type == 'amd':
            print("显卡:   AMD (ROCm/Vulkan)")
        else:
            print("显卡:   未检测到独立显卡（将使用 CPU）")

        print("\n依赖包状态:")
        pkgs = SimpleEnvChecker.check_packages()
        for pkg, installed in pkgs.items():
            display_name = "PIL" if pkg == "Pillow" else pkg
            status = "✅ 已安装" if installed else "❌ 未安装"
            version = ""
            if installed:
                import_name = SimpleEnvChecker.IMPORT_NAMES.get(pkg, pkg.replace('-', '_'))
                ver = SimpleEnvChecker.get_package_version(pkg, import_name)
                if ver and ver != "未安装":
                    version = f" (v{ver})"
            print(f"  {display_name:12} {status}{version}")

        # 显示 llama_cpp 动态库版本（如果已安装）
        if pkgs.get("llama_cpp", False):
            try:
                import llama_cpp
                lib_ver = None
                if hasattr(llama_cpp, 'llama_cpp_version'):
                    lib_ver = llama_cpp.llama_cpp_version
                elif hasattr(llama_cpp, 'get_llama_version'):
                    lib_ver = llama_cpp.get_llama_version()
                if lib_ver:
                    print(f"  llama_cpp 动态库版本: {lib_ver}")
            except Exception:
                pass

        # PDF 合并依赖检查
        pdf_merge_needed = ["Pillow", "pypdf"]
        missing_pdf = [p for p in pdf_merge_needed if not pkgs.get(p, False)]
        if missing_pdf:
            print("\n📌 PDF合并功能额外依赖:")
            for pkg in missing_pdf:
                print(f"  ❌ {pkg} 未安装 (PDF合并需要)")
                install_name = "Pillow" if pkg == "Pillow" else pkg
                print(f"     安装命令: pip install {install_name}")
            print("     或一次性安装: pip install " + " ".join(missing_pdf))

        info = SimpleEnvChecker.get_llama_cpp_info(gpu_type, cuda_ver)

        print("\nllama-cpp-python 推荐版本:")
        print(f"  推荐: {info['recommendation']}")
        print(f"  下载: {info['download_url']}")
        print(f"  命令: {info['install_cmd']}")

        if not pkgs.get("llama_cpp", False):
            print("\n📌 当前未安装 llama-cpp-python，请按上述推荐命令安装。")
        else:
            print("\n📌 已安装 llama-cpp-python。")
            print("   如果您当前安装的版本与上述推荐不一致，请使用上述命令重新安装。")
            if SimpleEnvChecker.is_frozen():
                base_dir = Path(sys.executable).parent
                internal_dll = base_dir / "_internal" / "llama_cpp" / "lib" / "llama.dll"
                if internal_dll.exists():
                    print(f"   ✅ llama.dll 存在 (内置): {internal_dll}")
                else:
                    print(f"   ⚠️ llama.dll 未找到，请确保打包时正确包含了 llama_cpp 文件夹。")

        print("\n📌 完整依赖安装命令:")
        other_pkgs = [p for p in SimpleEnvChecker.REQUIRED_PACKAGES if p != "llama_cpp"]
        if other_pkgs:
            print(f"   pip install " + " ".join(other_pkgs))
        if info.get('install_cmd'):
            print(f"   {info['install_cmd']}")

        print("\n📌 安装步骤:")
        if SimpleEnvChecker.is_frozen():
            print("  【打包环境 (--onedir)】")
            print("  程序运行所需文件已内置在 _internal 目录中，无需额外操作。")
            print("  若需要切换到其他后端（例如 CUDA、Vulkan 版本）：")
            print("  1. 获取对应版本的完整 llama_cpp 文件夹（包含 .py 和 lib 子目录）。")
            print(f"  2. 替换 {Path(sys.executable).parent / '_internal' / 'llama_cpp'} 目录。")
            print("  3. 重启程序即可生效。")
        else:
            print("  【开发环境 (pip)】")
            print(f"  1. 运行命令: {info['install_cmd']}")
            print("  2. 或手动下载 .whl 文件并使用 pip install 本地安装")
            print("  3. 验证安装: python -c 'import llama_cpp; print(llama_cpp.__version__)'")

        print("\n" + "=" * 50)


if __name__ == "__main__":
    SimpleEnvChecker.print_summary()
