#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
PDF 沉浸式翻译工具 - 图形界面
功能：
- 环境检查、清理中间文件
- 使用 multiprocessing 实现后台任务，支持强制停止
- 修复 spawn 错误：将子进程函数移至模块顶层
- 支持首次运行自动创建文件夹和 settings.json 配置文件
- 支持高级翻译参数调节（温度、top_p 等）
- 支持自定义弹窗（自适应大小，相对于主窗口居中）
- 支持解析引擎切换（MinerU API / PaddleOCR API）
- 配置热加载：修改参数后自动保存到 settings.json（点击“开始处理”或“高级设置确定”时）
- 支持 OpenAI 兼容 API 配置（DeepSeek, 智谱, 阿里云等）
- PDF合并支持自定义页面尺寸（宽度x高度，单位点）
"""

import os
import sys
import multiprocessing
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk, simpledialog
from pathlib import Path
import json
import re
import traceback
from term_processor import process_selected_term_files

# 导入后端模块（仅 config 和 env_check，不导入 main）
from config import Config
from env_check import SimpleEnvChecker

# 初始化 PATH（确保依赖库可被找到）
SimpleEnvChecker.prepare_path()

class RedirectText:
    """重定向 stdout 到 GUI 文本控件，具备异常保护"""
    def __init__(self, text_widget):
        self.text_widget = text_widget
        self.ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

    def write(self, string):
        try:
            if self.text_widget is not None:
                cleaned = self.ansi_escape.sub('', string)
                if cleaned:
                    self.text_widget.insert(tk.END, cleaned)
                    self.text_widget.see(tk.END)
                    self.text_widget.update_idletasks()
        except Exception:
            sys.__stdout__.write(string)
            sys.__stdout__.flush()

    def flush(self):
        pass


# ============================================================
# 子进程入口函数（必须在模块顶层定义，供 multiprocessing 使用）
# ============================================================
def run_pipeline_in_process(cfg_dict):
    """在独立进程中执行完整流水线"""
    try:
        # 延迟导入 main，避免模块加载时因缺少依赖而崩溃
        from main import run_pipeline
        from config import Config
        cfg = Config()
        for key, value in cfg_dict.items():
            setattr(cfg, key, value)
        run_pipeline(cfg)
    except Exception as e:
        print(f"❌ 子进程错误: {e}")
        import traceback
        traceback.print_exc()
        with open("error.log", "w", encoding="utf-8") as f:
            f.write(f"子进程错误:\n{traceback.format_exc()}")


class App:
    """主应用程序类"""
    def __init__(self, root):
        self.root = root
        self.root.title("PDF2zhen v1.10   开个人公司，找企优优创，qiyoyo.com.cn")
        self.root.geometry("800x750")
        
       # ----- 设置窗口图标 -----
        self._set_window_icon()

        # 确定基础目录（打包环境或开发环境）
        if getattr(sys, 'frozen', False):
            self.base_dir = Path(sys.executable).parent
        else:
            self.base_dir = Path.cwd()

        self._init_environment()  # 首次运行创建必要文件夹和配置文件
        self.glossary_status_var = tk.StringVar(value="未加载")
        # ===== 默认配置 =====
        default_settings = {
            "input_folder": "./pdfs",
            "output_root": "./final_output",
            "model_path": "./models/Hy-MT2-1.8B-Q4_K_M.gguf",
            "pages_per_file": 20,
            "target_lang": "中文",
            "parse_engine": "mineru",
            "mineru_token": "",
            "paddleocr_token": "",
            "paddleocr_model": "PaddleOCR-VL-1.6",
            "paddleocr_use_chart": False,
            "paddleocr_use_unwarp": False,
            "paddleocr_use_orientation": False,            
            "extra_formats": {"html": False, "docx": False, "latex": False},
            "skip_mineru": False,
            "skip_translation": False,
            "n_ctx": 4096,
            "pdf_merger_page_size": "A4",
            "pdf_merger_margin": 5,
            "pdf_custom_width": "595",      # 新增
            "pdf_custom_height": "842",     # 新增
            "translation_temperature": 0.7,
            "translation_top_p": 0.6,
            "translation_top_k": 20,
            "translation_repeat_penalty": 1.05,
            "translation_max_tokens": 4096,
            "target_style": "风趣幽默",
            "background_text": "我是一名电子工程师。",
            "translation_glossary": "",
            "openai_api_enabled": False,
            "openai_api_key": "your-api-key",
            "openai_api_base": "https://api.deepseek.com",
            "openai_model": "deepseek-v4-pro",
            "openai_timeout": 60,
            "openai_extra_body": "",
        }

        settings = self._load_settings(default_settings)  # 加载用户配置

        # 初始化 GUI 变量（与配置项绑定）
        self.input_folder = tk.StringVar(value=settings["input_folder"])
        self.output_root = tk.StringVar(value=settings["output_root"])
        self.mineru_token = tk.StringVar(value=settings["mineru_token"])
        self.model_path = tk.StringVar(value=settings["model_path"])
        self.pages_per_file = tk.IntVar(value=settings["pages_per_file"])
        self.target_lang = tk.StringVar(value=settings["target_lang"])
        self.extra_formats = {
            "html": tk.BooleanVar(value=settings["extra_formats"]["html"]),
            "docx": tk.BooleanVar(value=settings["extra_formats"]["docx"]),
            "latex": tk.BooleanVar(value=settings["extra_formats"]["latex"])
        }
        self.pdf_merger_page_size = tk.StringVar(value=settings.get("pdf_merger_page_size", "A4"))
        self.pdf_merger_margin = tk.IntVar(value=settings.get("pdf_merger_margin", 5))
        # 新增自定义尺寸变量
        self.pdf_custom_width = tk.StringVar(value=settings.get("pdf_custom_width", "595"))
        self.pdf_custom_height = tk.StringVar(value=settings.get("pdf_custom_height", "842"))
        self.skip_mineru = tk.BooleanVar(value=settings["skip_mineru"])
        self.skip_translation = tk.BooleanVar(value=settings["skip_translation"])
        self.n_ctx = tk.IntVar(value=settings["n_ctx"])

        # 翻译参数
        self.translation_temperature = tk.DoubleVar(value=settings["translation_temperature"])
        self.translation_top_p = tk.DoubleVar(value=settings["translation_top_p"])
        self.translation_top_k = tk.IntVar(value=settings["translation_top_k"])
        self.translation_repeat_penalty = tk.DoubleVar(value=settings["translation_repeat_penalty"])
        self.translation_max_tokens = tk.IntVar(value=settings["translation_max_tokens"])

        # Prompt 配置
        self.target_style = tk.StringVar(value=settings.get("target_style", ""))
        self.background_text = tk.StringVar(value=settings.get("background_text", ""))
        self.translation_glossary = tk.StringVar(value=settings.get("translation_glossary", ""))

        # 解析引擎配置
        self.parse_engine = tk.StringVar(value=settings.get("parse_engine", "mineru"))
        self.paddleocr_token = tk.StringVar(value=settings.get("paddleocr_token", ""))
        self.paddleocr_use_chart = tk.BooleanVar(value=settings.get("paddleocr_use_chart", False))
        self.paddleocr_use_unwarp = tk.BooleanVar(value=settings.get("paddleocr_use_unwarp", False))
        self.paddleocr_use_orientation = tk.BooleanVar(value=settings.get("paddleocr_use_orientation", False))
        self.paddleocr_model = tk.StringVar(value=settings.get("paddleocr_model", "PaddleOCR-VL-1.6"))
        # openai配置
        self.openai_api_enabled = tk.BooleanVar(value=settings.get("openai_api_enabled", False))
        self.openai_api_key = tk.StringVar(value=settings.get("openai_api_key", ""))
        self.openai_api_base = tk.StringVar(value=settings.get("openai_api_base", "https://api.deepseek.com"))
        self.openai_model = tk.StringVar(value=settings.get("openai_model", "deepseek-v4-pro"))
        self.openai_timeout = tk.IntVar(value=settings.get("openai_timeout", 60))
        self.openai_extra_body = tk.StringVar(value=settings.get("openai_extra_body", ""))
        # 进程控制状态
        self.running = False
        self.process = None
        self.current_cfg = None

        self._build_ui()  # 构建界面

        # 重定向 stdout 到日志文本框
        sys.stdout = RedirectText(self.log_text)
        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)
        
    def _set_window_icon(self):
        try:
            if getattr(sys, 'frozen', False):
                if hasattr(sys, '_MEIPASS'):
                    base_path = Path(sys._MEIPASS)
                else:
                    base_path = Path(sys.executable).parent
            else:
                base_path = Path.cwd()
            ico_path = base_path / 'app.ico'
            if ico_path.exists():
                self.root.iconbitmap(default=str(ico_path))
        except Exception:
            pass
        
    def _init_environment(self):
        """首次运行创建必要的文件夹和 settings.json 配置文件"""
        folders = ["pdfs", "split_results", "mineru_results", "translated_results", "final_output", "models", "term"]
        for f in folders:
            folder_path = self.base_dir / f
            if not folder_path.exists():
                folder_path.mkdir(parents=True, exist_ok=True)
                print(f"📁 创建文件夹: {folder_path}")
        # 创建默认术语表 glossary.json（如果不存在）
        glossary_path = self.base_dir / "glossary.json"
        if not glossary_path.exists():
            default_glossary = {
                "CPU": "中央处理器",
                "GPU": "图形处理器",
                "RAM": "随机存取存储器",
                "AI": "人工智能",
                "API": "应用程序接口",
                "PDF": "便携式文档格式",
                "OCR": "光学字符识别",
                "MT": "机器翻译"
            }
            try:
                with open(glossary_path, 'w', encoding='utf-8') as f:
                    json.dump(default_glossary, f, ensure_ascii=False, indent=2)
                print(f"📄 创建默认术语表: {glossary_path}")
            except Exception as e:
                print(f"⚠️ 创建默认术语表失败: {e}")

        settings_path = self.base_dir / "settings.json"
        if not settings_path.exists():
            default_settings = {
                "input_folder": "./pdfs",
                "output_root": "./final_output",
                "model_path": "./models/Hy-MT2-1.8B-Q4_K_M.gguf",
                "pages_per_file": 20,
                "target_lang": "中文",
                "parse_engine": "mineru",
                "mineru_token": "",
                "paddleocr_token": "",
                "paddleocr_model": "PaddleOCR-VL-1.6",
                "paddleocr_use_chart": False,
                "paddleocr_use_unwarp": False,
                "paddleocr_use_orientation": False,            
                "extra_formats": {"html": False, "docx": False, "latex": False},
                "skip_mineru": False,
                "skip_translation": False,
                "n_ctx": 4096,
                "pdf_merger_page_size": "A4",
                "pdf_merger_margin": 5,
                "pdf_custom_width": "595",
                "pdf_custom_height": "842",
                "translation_temperature": 0.7,
                "translation_top_p": 0.6,
                "translation_top_k": 20,
                "translation_repeat_penalty": 1.05,
                "translation_max_tokens": 4096,
                "target_style": "风趣幽默",
                "background_text": "我是一名电子工程师。",
                "translation_glossary": "",
                "openai_api_enabled": False,
                "openai_api_key": "your-api-key",
                "openai_api_base": "https://api.deepseek.com",
                "openai_model": "deepseek-v4-pro",
                "openai_timeout": 60,
                "openai_extra_body": "",
            }
            try:
                with open(settings_path, 'w', encoding='utf-8') as f:
                    json.dump(default_settings, f, ensure_ascii=False, indent=2)
                print(f"📄 创建配置文件: {settings_path}")
            except Exception as e:
                print(f"⚠️ 创建配置文件失败: {e}")

    def _load_settings(self, defaults):
        """从 settings.json 加载用户配置，合并默认值，并补充缺失字段"""
        config_file = self.base_dir / "settings.json"
        if not config_file.exists():
            return defaults
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                user_settings = json.load(f)
            merged = defaults.copy()
            for key, value in user_settings.items():
                if key == "extra_formats" and isinstance(value, dict):
                    merged["extra_formats"].update(value)
                elif key in merged:
                    merged[key] = value
            # 补充缺失字段并写回文件
            missing_keys = set(defaults.keys()) - set(user_settings.keys())
            if missing_keys:
                for key in missing_keys:
                    user_settings[key] = defaults[key]
                with open(config_file, 'w', encoding='utf-8') as f:
                    json.dump(user_settings, f, ensure_ascii=False, indent=2)
                print(f"📄 配置文件已补充缺失字段: {', '.join(missing_keys)}")
            return merged
        except Exception as e:
            print(f"⚠️ 加载配置文件失败: {e}，使用默认值")
            return defaults

    # ==================== 配置热加载（新增） ====================
    def _save_settings(self):
        """将当前 GUI 所有配置项保存到 settings.json（热加载）"""
        settings = {
            "input_folder": self.input_folder.get(),
            "output_root": self.output_root.get(),
            "model_path": self.model_path.get(),
            "pages_per_file": self.pages_per_file.get(),
            "target_lang": self.target_lang.get(),
            "parse_engine": self.parse_engine.get(),
            "mineru_token": self.mineru_token.get(),
            "paddleocr_token": self.paddleocr_token.get(),
            "paddleocr_model": self.paddleocr_model.get(),
            "paddleocr_use_chart": self.paddleocr_use_chart.get(),
            "paddleocr_use_unwarp": self.paddleocr_use_unwarp.get(),
            "paddleocr_use_orientation": self.paddleocr_use_orientation.get(),
            "extra_formats": {k: v.get() for k, v in self.extra_formats.items()},
            "skip_mineru": self.skip_mineru.get(),
            "skip_translation": self.skip_translation.get(),
            "n_ctx": self.n_ctx.get(),
            "pdf_merger_page_size": self.pdf_merger_page_size.get(),
            "pdf_merger_margin": self.pdf_merger_margin.get(),
            "pdf_custom_width": self.pdf_custom_width.get(),
            "pdf_custom_height": self.pdf_custom_height.get(),
            "translation_temperature": self.translation_temperature.get(),
            "translation_top_p": self.translation_top_p.get(),
            "translation_top_k": self.translation_top_k.get(),
            "translation_repeat_penalty": self.translation_repeat_penalty.get(),
            "translation_max_tokens": self.translation_max_tokens.get(),
            "target_style": self.target_style.get(),
            "background_text": self.background_text.get(),
            "translation_glossary": self.translation_glossary.get(),
            "openai_api_enabled": self.openai_api_enabled.get(),
            "openai_api_key": self.openai_api_key.get(),
            "openai_api_base": self.openai_api_base.get(),
            "openai_model": self.openai_model.get(),
            "openai_timeout": self.openai_timeout.get(),
            "openai_extra_body": self.openai_extra_body.get(),
        }
        try:
            with open(self.base_dir / "settings.json", 'w', encoding='utf-8') as f:
                json.dump(settings, f, ensure_ascii=False, indent=2)
            print("✅ 配置已保存到 settings.json")
        except Exception as e:
            print(f"⚠️ 保存配置失败: {e}")

    def _on_closing(self):
        """窗口关闭时停止后台进程"""
        if self.running:
            self._stop_process()
        sys.stdout = sys.__stdout__
        self.root.destroy()

    def _center_window(self, win, master):
        """使窗口相对于父窗口居中（无闪烁）"""
        # 先确保 win 有正确的请求尺寸
        win.update_idletasks()
        master.update_idletasks()

        master_x = master.winfo_x()
        master_y = master.winfo_y()
        master_width = master.winfo_width()
        master_height = master.winfo_height()

        # 获取子窗口尺寸（优先使用实际尺寸，否则使用请求尺寸）
        width = win.winfo_width()
        if width <= 1:
            width = win.winfo_reqwidth()
        height = win.winfo_height()
        if height <= 1:
            height = win.winfo_reqheight()

        x = master_x + (master_width - width) // 2
        y = master_y + (master_height - height) // 2

        # 如果窗口尚未映射，设置完整几何；否则只移动
        if not win.winfo_ismapped():
            win.geometry(f"{width}x{height}+{x}+{y}")
        else:
            win.geometry(f"+{x}+{y}")
    # ==================== 自定义弹窗 ====================
    def _custom_askyesno(self, title: str, message: str) -> bool:
        """自定义确认对话框"""
        top = tk.Toplevel(self.root)
        top.title(title)
        top.transient(self.root)
        top.grab_set()
        msg_label = ttk.Label(top, text=message, wraplength=500, justify=tk.LEFT)
        msg_label.pack(pady=15, padx=20)
        btn_frame = ttk.Frame(top)
        btn_frame.pack(pady=10)
        result = False
        def on_yes():
            nonlocal result
            result = True
            top.destroy()
        def on_no():
            top.destroy()
        ttk.Button(btn_frame, text="确定", command=on_yes, width=10).pack(side=tk.LEFT, padx=10)
        ttk.Button(btn_frame, text="取消", command=on_no, width=10).pack(side=tk.LEFT, padx=10)
        top.update_idletasks()
        width = top.winfo_reqwidth() + 20
        height = top.winfo_reqheight() + 20
        top.geometry(f"{width}x{height}")
        self._center_window(top, self.root)
        self.root.wait_window(top)
        return result

    def _show_custom_messagebox(self, title: str, message: str, msg_type: str = "info", parent=None):
        """自定义消息框，直接居中显示，无闪烁"""
        if parent is None:
            parent = self.root
        top = tk.Toplevel(parent)
        top.title(title)
        top.withdraw()  # 先隐藏
        top.transient(parent)
        top.grab_set()

        icon = "❌" if msg_type == "error" else "⚠️" if msg_type == "warning" else "ℹ️"
        msg_label = ttk.Label(top, text=f"{icon} {message}", wraplength=500, justify=tk.LEFT)
        msg_label.pack(pady=20, padx=20)
        ttk.Button(top, text="确定", command=top.destroy, width=10).pack(pady=10)

        top.update_idletasks()  # 强制刷新尺寸
        # 计算居中位置
        parent_x = parent.winfo_x()
        parent_y = parent.winfo_y()
        parent_w = parent.winfo_width()
        parent_h = parent.winfo_height()
        width = top.winfo_reqwidth()
        height = top.winfo_reqheight()
        x = parent_x + (parent_w - width) // 2
        y = parent_y + (parent_h - height) // 2
        top.geometry(f"{width}x{height}+{x}+{y}")
        top.deiconify()  # 显示在最终位置
        top.wait_window(top)

    def _open_folder(self, path: Path):
        """跨平台打开文件夹"""
        if not path.exists():
            return
        import subprocess
        import platform
        system = platform.system()
        try:
            if system == "Windows":
                subprocess.Popen(["explorer", str(path)])
            elif system == "Darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as e:
            print(f"⚠️ 无法打开输出文件夹: {e}")
            
    def _process_terminology_folder(self):
        term_dir = self.base_dir / "term"
        if not term_dir.exists():
            self._show_custom_messagebox("提示", "term 文件夹不存在，请先创建。")
            return

        file_paths = filedialog.askopenfilenames(
            parent=self.root,
            title="选择术语表文件",
            initialdir=str(term_dir),
            filetypes=[("所有文件", "*.*")]
        )
        if not file_paths:
            return

        from term_processor import process_selected_term_files
        success, msg = process_selected_term_files(list(file_paths), term_dir)
        if success:
            self._show_custom_messagebox("完成", msg)
        else:
            self._show_custom_messagebox("错误", msg)          

    def _build_ui(self):
        """构建主界面布局"""
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        main_frame.columnconfigure(0, weight=0)
        main_frame.columnconfigure(1, weight=1)
        main_frame.columnconfigure(2, weight=0)

        # row 0: 输入文件夹
        ttk.Label(main_frame, text="输入文件夹:").grid(row=0, column=0, sticky=tk.W, pady=5)
        ttk.Entry(main_frame, textvariable=self.input_folder).grid(row=0, column=1, sticky="ew", padx=5, pady=5)
        ttk.Button(main_frame, text="浏览...", command=self._browse_input).grid(row=0, column=2, padx=5, pady=5)

        # row 1: 输出根目录
        ttk.Label(main_frame, text="输出文件夹:").grid(row=1, column=0, sticky=tk.W, pady=5)
        ttk.Entry(main_frame, textvariable=self.output_root).grid(row=1, column=1, sticky="ew", padx=5, pady=5)
        ttk.Button(main_frame, text="浏览...", command=self._browse_output).grid(row=1, column=2, padx=5, pady=5)

        # row 2: API Token（根据引擎切换）
        ttk.Label(main_frame, text="API Token:").grid(row=2, column=0, sticky=tk.W, pady=5)
        self.token_entry = ttk.Entry(main_frame, textvariable=self.mineru_token, width=70, show="*")
        self.token_entry.grid(row=2, column=1, columnspan=2, sticky="ew", padx=5, pady=5)

        # row 3: 解析引擎
        ttk.Label(main_frame, text="解析引擎:").grid(row=3, column=0, sticky=tk.W, pady=5)
        engine_frame = ttk.Frame(main_frame)
        engine_frame.grid(row=3, column=1, columnspan=2, sticky=tk.W, padx=5, pady=5)
        mineru_radio = ttk.Radiobutton(engine_frame, text="MinerU API", variable=self.parse_engine, value="mineru")
        mineru_radio.pack(side=tk.LEFT, padx=5)
        paddle_radio = ttk.Radiobutton(engine_frame, text="PaddleOCR API", variable=self.parse_engine, value="paddleocr")
        paddle_radio.pack(side=tk.LEFT, padx=5)
        local_radio = ttk.Radiobutton(engine_frame, text="本地引擎 (纯文本)", variable=self.parse_engine, value="local")
        local_radio.pack(side=tk.LEFT, padx=5)

        def update_token_var(*args):
            engine = self.parse_engine.get()
            if engine == "mineru":
                self.token_entry.config(textvariable=self.mineru_token, state="normal")
                self.token_entry.config(show="*")
            elif engine == "paddleocr":
                self.token_entry.config(textvariable=self.paddleocr_token, state="normal")
                self.token_entry.config(show="*")
            else:
                self.token_entry.config(textvariable=self.mineru_token, state="disabled")
                self.token_entry.delete(0, tk.END)
                self.token_entry.insert(0, "无需 Token")
                self.token_entry.config(show="*")
        self.parse_engine.trace_add("write", update_token_var)
        update_token_var()

        # row 4: 模型文件
        ttk.Label(main_frame, text="腾讯混元翻译模型:").grid(row=4, column=0, sticky=tk.W, pady=5)
        ttk.Entry(main_frame, textvariable=self.model_path).grid(row=4, column=1, sticky="ew", padx=5, pady=5)
        ttk.Button(main_frame, text="浏览...", command=self._browse_model).grid(row=4, column=2, padx=5, pady=5)

        # row 5: 页数
        ttk.Label(main_frame, text="拆分PDF每份页数:").grid(row=5, column=0, sticky=tk.W, pady=5)
        ttk.Spinbox(main_frame, from_=1, to=50, textvariable=self.pages_per_file, width=10).grid(row=5, column=1, sticky=tk.W, padx=5, pady=5)

        # row 6: 目标语言
        ttk.Label(main_frame, text="要翻译成的语言:").grid(row=6, column=0, sticky=tk.W, pady=5)
        lang_combo = ttk.Combobox(main_frame, textvariable=self.target_lang, values=["中文", "英语"], state="readonly", width=9)
        lang_combo.grid(row=6, column=1, sticky=tk.W, padx=5, pady=5)
        lang_combo.current(0)

        # row 7: n_ctx
        ttk.Label(main_frame, text="上下文长度 (n_ctx):").grid(row=7, column=0, sticky=tk.W, pady=5)
        n_ctx_spin = ttk.Spinbox(main_frame, from_=512, to=32768, increment=512, textvariable=self.n_ctx, width=10)
        n_ctx_spin.grid(row=7, column=1, sticky=tk.W, padx=5, pady=5)

        # row 8: 额外导出格式
        ttk.Label(main_frame, text="额外格式(mineu中间件):").grid(row=8, column=0, sticky=tk.W, pady=5)
        formats_frame = ttk.Frame(main_frame)
        formats_frame.grid(row=8, column=1, columnspan=2, sticky=tk.W, padx=5, pady=5)
        ttk.Checkbutton(formats_frame, text="HTML", variable=self.extra_formats["html"]).pack(side=tk.LEFT, padx=5)
        ttk.Checkbutton(formats_frame, text="DOCX", variable=self.extra_formats["docx"]).pack(side=tk.LEFT, padx=5)
        ttk.Checkbutton(formats_frame, text="LaTeX", variable=self.extra_formats["latex"]).pack(side=tk.LEFT, padx=5)

        # row 9: PDF合并参数（包含自定义尺寸）
        ttk.Label(main_frame, text="PDF合并参数:").grid(row=9, column=0, sticky=tk.W, pady=5)
        param_frame = ttk.Frame(main_frame)
        param_frame.grid(row=9, column=1, columnspan=2, sticky=tk.W, padx=5, pady=5)

        # 第一行：页面尺寸 + 边距
        top_row = ttk.Frame(param_frame)
        top_row.pack(side=tk.TOP, fill=tk.X, pady=2)

        ttk.Label(top_row, text="页面尺寸:").pack(side=tk.LEFT, padx=2)
        self.page_size_combo = ttk.Combobox(
            top_row,
            textvariable=self.pdf_merger_page_size,
            values=["A4", "A3", "A5", "LETTER", "LEGAL", "自定义"],
            state="readonly",
            width=8
        )
        self.page_size_combo.pack(side=tk.LEFT, padx=2)
        self.page_size_combo.current(0)

        ttk.Label(top_row, text="边距:").pack(side=tk.LEFT, padx=(10, 2))
        margin_spin = ttk.Spinbox(
            top_row,
            from_=0,
            to=50,
            increment=1,
            textvariable=self.pdf_merger_margin,
            width=6
        )
        margin_spin.pack(side=tk.LEFT, padx=2)
        ttk.Label(top_row, text="点").pack(side=tk.LEFT, padx=2)

        # 第二行：自定义尺寸输入（默认隐藏）
        self.custom_frame = ttk.Frame(param_frame)
        self.custom_frame.pack(side=tk.TOP, fill=tk.X, pady=2)
        ttk.Label(self.custom_frame, text="宽度:").pack(side=tk.LEFT, padx=2)
        width_entry = ttk.Entry(self.custom_frame, textvariable=self.pdf_custom_width, width=6)
        width_entry.pack(side=tk.LEFT, padx=2)
        ttk.Label(self.custom_frame, text="×").pack(side=tk.LEFT, padx=2)
        ttk.Label(self.custom_frame, text="高度:").pack(side=tk.LEFT, padx=2)
        height_entry = ttk.Entry(self.custom_frame, textvariable=self.pdf_custom_height, width=6)
        height_entry.pack(side=tk.LEFT, padx=2)
        ttk.Label(self.custom_frame, text="点").pack(side=tk.LEFT, padx=2)

        # 初始隐藏自定义输入框
        self.custom_frame.pack_forget()

        # 绑定事件，切换自定义输入框显示
        def on_page_size_changed(*args):
            if self.pdf_merger_page_size.get() == "自定义":
                self.custom_frame.pack(side=tk.TOP, fill=tk.X, pady=2)
            else:
                self.custom_frame.pack_forget()
        self.pdf_merger_page_size.trace_add("write", on_page_size_changed)

        # row 10: 跳过选项
        skip_frame = ttk.Frame(main_frame)
        skip_frame.grid(row=10, column=0, columnspan=3, sticky=tk.W, pady=5)
        ttk.Checkbutton(skip_frame, text="跳过解析 (使用已有结果)", variable=self.skip_mineru).pack(side=tk.LEFT, padx=5)
        ttk.Checkbutton(skip_frame, text="跳过翻译 (使用已有译文)", variable=self.skip_translation).pack(side=tk.LEFT, padx=5)

        # row 11: 按钮
        btn_frame = ttk.Frame(main_frame)
        btn_frame.grid(row=11, column=0, columnspan=3, pady=10)
        self.screenshot_btn = ttk.Button(btn_frame, text="区域截图", command=self._take_screenshot, width=10)
        self.screenshot_btn.pack(side=tk.LEFT, padx=5)
        self.merge_btn = ttk.Button(btn_frame, text="合成PDF", command=self._merge_pdfs, width=10)
        self.merge_btn.pack(side=tk.LEFT, padx=5)
        self.start_btn = ttk.Button(btn_frame, text="开始处理", command=self._start_process, width=10)
        self.start_btn.pack(side=tk.LEFT, padx=5)
        self.stop_btn = ttk.Button(btn_frame, text="停止", command=self._stop_process, state=tk.DISABLED, width=10)
        self.stop_btn.pack(side=tk.LEFT, padx=5)
        self.env_btn = ttk.Button(btn_frame, text="环境检查", command=self._check_env, width=10)
        self.env_btn.pack(side=tk.LEFT, padx=5)
        self.clean_btn = ttk.Button(btn_frame, text="清理过程文件", command=self._cleanup, width=10)
        self.clean_btn.pack(side=tk.LEFT, padx=5)
        self.adv_btn = ttk.Button(btn_frame, text="高级设置", command=self._show_advanced_settings, width=10)
        self.adv_btn.pack(side=tk.LEFT, padx=5)

        # row 12: 日志标签
        ttk.Label(main_frame, text="运行日志:").grid(row=12, column=0, sticky=tk.W, pady=5)

        # row 13: 日志文本框
        self.log_text = scrolledtext.ScrolledText(main_frame, height=20, wrap=tk.WORD)
        self.log_text.grid(row=13, column=0, columnspan=3, sticky="nsew", pady=5)

        main_frame.rowconfigure(13, weight=1)

    # ==================== 文件浏览 ====================
    def _browse_input(self):
        folder = filedialog.askdirectory(parent=self.root, title="选择输入文件夹")
        if folder:
            self.input_folder.set(folder)

    def _browse_output(self):
        folder = filedialog.askdirectory(parent=self.root, title="选择输出文件夹")
        if folder:
            self.output_root.set(folder)

    def _browse_model(self):
        file = filedialog.askopenfilename(parent=self.root, title="选择翻译模型文件",
                                          filetypes=[("GGUF files", "*.gguf"), ("All files", "*.*")])
        if file:
            self.model_path.set(file)
    # ==================== 鼠标截屏 ====================
    def _show_screenshot_done(self, message, file_list):
        """显示截图完成对话框，带‘打开截图’和‘确定’按钮"""
        top = tk.Toplevel(self.root)
        top.title("截图完成")
        top.transient(self.root)
        top.grab_set()

        icon = "✅"
        msg_label = ttk.Label(top, text=f"{icon} {message}", wraplength=400, justify=tk.LEFT)
        msg_label.pack(pady=15, padx=20)

        btn_frame = ttk.Frame(top)
        btn_frame.pack(pady=10)

        def open_folder():
            pdfs_dir = Path(self.base_dir / "pdfs")
            self._open_folder(pdfs_dir)
            top.destroy()  # 关闭对话框

        ttk.Button(btn_frame, text="打开截图", command=open_folder, width=12).pack(side=tk.LEFT, padx=10)
        ttk.Button(btn_frame, text="确定", command=top.destroy, width=10).pack(side=tk.LEFT, padx=10)

        top.update_idletasks()
        self._center_window(top, self.root)
        top.wait_window(top)

    def _take_screenshot(self):
        """启动悬浮截图（先拖拽划定区域，然后悬浮框可调整）"""
        try:
            from screenshot import start_floating_screenshot
        except ImportError as e:
            self._show_custom_messagebox("导入错误", f"无法加载截图模块: {e}", "error")
            return

        sys.__stdout__.write("\n📸 启动悬浮截图，请拖拽选择初始区域...\n")
        sys.__stdout__.flush()

        def on_finish(success, message, file_list):
            if success:
                self.root.after(0, lambda: self._show_screenshot_done(message, file_list))
            else:
                if message != "用户取消":
                    self.root.after(0, lambda: self._show_custom_messagebox("截图失败", f"错误: {message}", "error"))

        try:
            start_floating_screenshot(self.root, on_finish)
        except Exception as e:
            self._show_custom_messagebox("截图错误", str(e), "error")
    # ==================== PDF 合并 ====================
    def _merge_pdfs(self):
        """调用 PDF 合并模块"""
        try:
            from pdf_merger import PDFMerger
        except ImportError as e:
            self._show_custom_messagebox("导入错误", f"无法加载 PDF 合并模块: {e}", "error")
            return
        # 获取页面尺寸字符串
        if self.pdf_merger_page_size.get() == "自定义":
            page_size_str = f"{self.pdf_custom_width.get().strip()}x{self.pdf_custom_height.get().strip()}"
        else:
            page_size_str = self.pdf_merger_page_size.get()
        margin = self.pdf_merger_margin.get()
        msg = (f"将合并 pdfs 文件夹中的所有图片和 PDF 文件为一个 PDF。\n\n"
               f"参数：\n• 页面尺寸: {page_size_str}\n• 边距: {margin} 点\n\n"
               "操作流程：\n1. 按文件名自然排序\n2. 统一缩放（拉伸填满）\n"
               "3. 自动裁剪 PDF 页面留白\n4. 合并完成后清空源文件夹\n"
               "5. 将合并后的 PDF 移动到 pdfs 文件夹\n\n确定继续？")
        if not self._custom_askyesno("确认合并", msg):
            return
        try:
            sys.__stdout__.write(f"\n🔄 开始合并 PDF (页面尺寸: {page_size_str}, 边距: {margin} 点)...\n")
            sys.__stdout__.flush()
            merger = PDFMerger(input_folder=Path("./pdfs"), page_size=page_size_str, margin=margin, crop_whitespace=True)
            success = merger.merge()
            if success:
                self._show_custom_messagebox("合并完成", "PDF 合并完成！\n\n合并后的文件位于 pdfs 文件夹中。", "info")
            else:
                self._show_custom_messagebox("合并失败", "PDF 合并失败，请查看日志了解详情。", "warning")
        except Exception as e:
            self._show_custom_messagebox("合并错误", f"合并过程中发生错误: {e}", "error")

    # ==================== 环境检查 ====================
    def _check_env(self):
        self.log_text.delete(1.0, tk.END)
        print("正在检查环境...\n")
        SimpleEnvChecker.print_summary()
        print("\n环境检查完成。")

    # ==================== 加载术语表文件 ====================
    def _load_json_glossary(self, parent, text_widget):
        """加载术语表文件（不限格式），显示在文本框中"""
        term_dir = self.base_dir / "term"
        if not term_dir.exists():
            term_dir.mkdir(parents=True, exist_ok=True)
        file_path = filedialog.askopenfilename(
            parent=parent,
            title="选择术语表文件",
            initialdir=str(term_dir),
            filetypes=[("所有文件", "*.*")]  # 不限定格式
        )
        if not file_path:
            return
        try:
            from pathlib import Path
            import json
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 尝试解析为 JSON，如果是则格式化为缩进
            try:
                data = json.loads(content)
                if isinstance(data, dict):
                    content = json.dumps(data, ensure_ascii=False, indent=2)
                    self.glossary_status_var.set(f"已加载 JSON 术语表 ({len(data)} 条)")
                else:
                    self.glossary_status_var.set(f"已加载文件: {Path(file_path).name} (非 JSON 格式)")
            except json.JSONDecodeError:
                # 不是 JSON，直接显示原始内容
                self.glossary_status_var.set(f"已加载文件: {Path(file_path).name} (传统格式)")
            
            text_widget.delete('1.0', tk.END)
            text_widget.insert('1.0', content)
        except Exception as e:
            self._show_custom_messagebox("加载失败", str(e), parent=parent)
    # ==================== 保存术语到glossay ====================     
    def _save_glossary_from_text(self, parent, text_widget, show_message=True):
        """将文本框内容保存到根目录 glossary.json（支持 JSON 或传统格式）"""
        content = text_widget.get('1.0', tk.END).strip()
        if not content:
            data = {}  # 空内容保存为空字典
        else:
            # 尝试解析为 JSON
            try:
                data = json.loads(content)
                if not isinstance(data, dict):
                    # 如果不是字典，尝试按传统格式解析
                    data = self._parse_legacy_glossary(content)
            except:
                # JSON 解析失败，尝试传统格式
                data = self._parse_legacy_glossary(content)

            if data is None:
                if show_message:
                    self._show_custom_messagebox("错误", "无法解析术语表内容，请确保格式正确（JSON 或 源词=目标词 每行）", parent=parent)
                return

        # 保存到 glossary.json
        glossary_path = self.base_dir / "glossary.json"
        try:
            with open(glossary_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self.glossary_status_var.set(f"已保存 {len(data)} 条术语到 glossary.json")
            if show_message:
                self._show_custom_messagebox("成功", f"已保存 {len(data)} 条术语到 glossary.json", parent=parent)
        except Exception as e:
            if show_message:
                self._show_custom_messagebox("保存失败", str(e), parent=parent)

    def _parse_legacy_glossary(self, content: str) -> dict:
        """
        解析传统格式的术语表（每行 src=tgt, src->tgt, src,tgt, src\t tgt, 或两个以上空格分隔）
        返回字典，如果无法解析则返回 None
        """
        lines = content.strip().splitlines()
        glossary = {}
        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            # 尝试不同分隔符（按优先级）
            if '=' in line:
                parts = line.split('=', 1)
            elif '->' in line:
                parts = line.split('->', 1)
            elif ',' in line:
                parts = line.split(',', 1)
            elif '\t' in line:
                parts = line.split('\t', 1)
            else:
                # 尝试两个或更多空格
                parts = re.split(r'\s{2,}', line)
                if len(parts) != 2:
                    continue
            if len(parts) == 2:
                src, tgt = parts[0].strip(), parts[1].strip()
                if src and tgt:
                    glossary[src] = tgt
        return glossary if glossary else None
    # ==================== 高级设置 ====================
    def _show_advanced_settings(self):
        """显示高级翻译参数设置窗口（扩大尺寸，增加边距）"""
        top = tk.Toplevel(self.root)
        top.title("高级翻译参数")
        top.withdraw()
        top.geometry("750x700")
        self._center_window(top, self.root)
        top.deiconify()
        top.transient(self.root)
        top.grab_set()

        row = 0
        top.grid_columnconfigure(0, weight=0)
        top.grid_columnconfigure(1, weight=1)
        top.grid_columnconfigure(2, weight=0)

        # 温度
        ttk.Label(top, text="温度 (temperature):").grid(row=row, column=0, padx=(15,5), pady=5, sticky=tk.W)
        ttk.Entry(top, textvariable=self.translation_temperature, width=25).grid(row=row, column=1, padx=(5,5), pady=5, sticky=tk.W)
        ttk.Label(top, text="0.3严谨，0.7流畅，2.0飘逸", foreground="gray").grid(row=row, column=2, padx=(5,15), pady=5, sticky=tk.W)
        row += 1

        # Top-p
        ttk.Label(top, text="Top-p (top_p):").grid(row=row, column=0, padx=(15,5), pady=5, sticky=tk.W)
        ttk.Entry(top, textvariable=self.translation_top_p, width=25).grid(row=row, column=1, padx=(5,5), pady=5, sticky=tk.W)
        ttk.Label(top, text="0~1，核采样阈值", foreground="gray").grid(row=row, column=2, padx=(5,15), pady=5, sticky=tk.W)
        row += 1

        # Top-k
        ttk.Label(top, text="Top-k (top_k):").grid(row=row, column=0, padx=(15,5), pady=5, sticky=tk.W)
        ttk.Entry(top, textvariable=self.translation_top_k, width=25).grid(row=row, column=1, padx=(5,5), pady=5, sticky=tk.W)
        ttk.Label(top, text="正整数，候选词数量", foreground="gray").grid(row=row, column=2, padx=(5,15), pady=5, sticky=tk.W)
        row += 1

        # Repeat penalty
        ttk.Label(top, text="重复惩罚 (repeat_penalty):").grid(row=row, column=0, padx=(15,5), pady=5, sticky=tk.W)
        ttk.Entry(top, textvariable=self.translation_repeat_penalty, width=25).grid(row=row, column=1, padx=(5,5), pady=5, sticky=tk.W)
        ttk.Label(top, text=">1 减少重复", foreground="gray").grid(row=row, column=2, padx=(5,15), pady=5, sticky=tk.W)
        row += 1

        # Max tokens
        ttk.Label(top, text="最大输出长度 (max_tokens):").grid(row=row, column=0, padx=(15,5), pady=5, sticky=tk.W)
        ttk.Entry(top, textvariable=self.translation_max_tokens, width=25).grid(row=row, column=1, padx=(5,5), pady=5, sticky=tk.W)
        ttk.Label(top, text="正整数，输出上限", foreground="gray").grid(row=row, column=2, padx=(5,15), pady=5, sticky=tk.W)
        row += 1

        # 翻译风格
        ttk.Label(top, text="翻译风格 (target_style):").grid(row=row, column=0, padx=(15,5), pady=5, sticky=tk.W)
        ttk.Entry(top, textvariable=self.target_style, width=25).grid(row=row, column=1, padx=(5,5), pady=5, sticky=tk.W)
        ttk.Label(top, text="示例: 正式专业, 简洁明了", foreground="gray").grid(row=row, column=2, padx=(5,15), pady=5, sticky=tk.W)
        row += 1

        # 背景信息
        ttk.Label(top, text="背景信息 (background_text):").grid(row=row, column=0, padx=(15,5), pady=5, sticky=tk.W)
        ttk.Entry(top, textvariable=self.background_text, width=25).grid(row=row, column=1, padx=(5,5), pady=5, sticky=tk.W)
        ttk.Label(top, text="提供翻译的上下文背景", foreground="gray").grid(row=row, column=2, padx=(5,15), pady=5, sticky=tk.W)
        row += 1

        # ---------- OpenAI API 配置区域 ----------
        ttk.Separator(top, orient='horizontal').grid(row=row, column=0, columnspan=3, sticky="ew", pady=10)
        row += 1

        ttk.Checkbutton(top, text="启用 OpenAI 兼容 API", variable=self.openai_api_enabled).grid(
            row=row, column=0, columnspan=3, padx=15, pady=5, sticky=tk.W)
        row += 1

        # API 配置框架 - 保存为实例变量，并添加存在性检查
        self.api_config_frame = ttk.Frame(top)
        self.api_config_frame.grid(row=row, column=0, columnspan=3, sticky="ew", padx=15, pady=5)

        def toggle_api_config(*args):
            # 检查框架是否仍然存在，避免窗口关闭后操作已销毁部件
            if hasattr(self, 'api_config_frame') and self.api_config_frame.winfo_exists():
                if self.openai_api_enabled.get():
                    self.api_config_frame.grid()
                else:
                    self.api_config_frame.grid_remove()

        self.openai_api_enabled.trace_add('write', toggle_api_config)
        toggle_api_config()  # 初始化显示状态

        # API Key
        ttk.Label(self.api_config_frame, text="API Key:").grid(row=0, column=0, padx=(0,5), pady=2, sticky=tk.W)
        ttk.Entry(self.api_config_frame, textvariable=self.openai_api_key, width=50, show="*").grid(row=0, column=1, padx=5, pady=2, sticky=tk.W)
        # API Base
        ttk.Label(self.api_config_frame, text="API Base:").grid(row=1, column=0, padx=(0,5), pady=2, sticky=tk.W)
        ttk.Entry(self.api_config_frame, textvariable=self.openai_api_base, width=50).grid(row=1, column=1, padx=5, pady=2, sticky=tk.W)
        # Model
        ttk.Label(self.api_config_frame, text="Model:").grid(row=2, column=0, padx=(0,5), pady=2, sticky=tk.W)
        ttk.Entry(self.api_config_frame, textvariable=self.openai_model, width=50).grid(row=2, column=1, padx=5, pady=2, sticky=tk.W)
        # Timeout
        ttk.Label(self.api_config_frame, text="Timeout (秒):").grid(row=3, column=0, padx=(0,5), pady=2, sticky=tk.W)
        ttk.Entry(self.api_config_frame, textvariable=self.openai_timeout, width=10).grid(row=3, column=1, padx=5, pady=2, sticky=tk.W)
        # 额外参数
        ttk.Label(self.api_config_frame, text="额外参数 (JSON):").grid(row=4, column=0, padx=(0,5), pady=2, sticky=tk.W)
        extra_body_entry = ttk.Entry(self.api_config_frame, textvariable=self.openai_extra_body, width=50)
        extra_body_entry.grid(row=4, column=1, padx=5, pady=2, sticky=tk.W)

        row += 1

        # ---------- 术语表区域 ----------
        ttk.Label(top, text="术语表:支持json格式和，= -> tab 多空格 分隔符，其他格式先转换").grid(row=row, column=0, padx=15, pady=5, sticky=tk.W)
        glossary_frame = ttk.Frame(top)
        glossary_frame.grid(row=row+1, column=0, columnspan=3, padx=15, pady=5, sticky="nsew")
        glossary_text = tk.Text(glossary_frame, height=8, width=50, font=('Consolas', 10))
        glossary_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(glossary_frame, orient=tk.VERTICAL, command=glossary_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        glossary_text.config(yscrollcommand=scrollbar.set)

        glossary_path = self.base_dir / "glossary.json"
        if glossary_path.exists():
            try:
                with open(glossary_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if data:
                        content = json.dumps(data, ensure_ascii=False, indent=2)
                        glossary_text.insert('1.0', content)
                        self.glossary_status_var.set(f"已加载 {len(data)} 条术语")
                    else:
                        self.glossary_status_var.set("术语表为空")
            except Exception as e:
                print(f"加载术语表失败: {e}")
                self.glossary_status_var.set("加载失败")

        row += 2

        btn_row = row
        btn_frame = ttk.Frame(top)
        btn_frame.grid(row=btn_row, column=0, padx=15, pady=5, sticky=tk.W)
        ttk.Button(btn_frame, text="术语表转JSON", command=self._process_terminology_folder).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="加载术语表",
                   command=lambda: self._load_json_glossary(top, glossary_text)).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="保存术语表",
                   command=lambda: self._save_glossary_from_text(top, glossary_text)).pack(side=tk.LEFT, padx=2)
        ttk.Label(
            top,
            text="JSON 格式，键为源词，值为目标词",
            foreground="gray"
        ).grid(row=btn_row, column=1, columnspan=2, padx=5, pady=5, sticky=tk.W)
        row += 1

        # 定义关闭/确定时的统一保存操作
        def on_save_and_close():
            self._save_glossary_from_text(top, glossary_text, show_message=False)
            self._save_settings()
            top.destroy()

        # 绑定窗口关闭事件
        top.protocol("WM_DELETE_WINDOW", on_save_and_close)

        # 确定按钮
        ttk.Button(top, text="确定", command=on_save_and_close).grid(row=row, column=0, columnspan=3, pady=15)

        top.grid_rowconfigure(row, weight=1)
        top.grid_columnconfigure(1, weight=1)
        top.grid_columnconfigure(2, weight=1)

    # ==================== 清理中间文件 ====================
    def _cleanup(self):
        """弹出清理目录选择窗口（紧凑布局，含 final_output）"""
        top = tk.Toplevel(self.root)
        top.title("选择要清空的目录")
        top.withdraw()
        top.geometry("360x270")
        self._center_window(top, self.root)
        top.deiconify()
        top.transient(self.root)
        top.grab_set()
        top.update_idletasks()
        self._center_window(top, self.root)

        var_pdfs = tk.BooleanVar(value=False)
        var_split = tk.BooleanVar(value=False)
        var_mineru = tk.BooleanVar(value=False)
        var_translated = tk.BooleanVar(value=False)
        var_final = tk.BooleanVar(value=False)

        ttk.Label(top, text="请勾选要清空的目录（可多选）：").pack(pady=8)
        chk_frame = ttk.Frame(top)
        chk_frame.pack(pady=4, padx=20, anchor=tk.W)
        ttk.Checkbutton(chk_frame, text="pdfs (原始PDF)", variable=var_pdfs).pack(anchor=tk.W)
        ttk.Checkbutton(chk_frame, text="split_results (拆分后PDF)", variable=var_split).pack(anchor=tk.W)
        ttk.Checkbutton(chk_frame, text="mineru_results (解析后文件)", variable=var_mineru).pack(anchor=tk.W)
        ttk.Checkbutton(chk_frame, text="translated_results (翻译后文件)", variable=var_translated).pack(anchor=tk.W)
        ttk.Checkbutton(chk_frame, text="final_output (最终输出)", variable=var_final).pack(anchor=tk.W)  # 新增

        btn_frame = ttk.Frame(top)
        btn_frame.pack(pady=10)

        def do_clean():
            selected = []
            if var_pdfs.get():
                selected.append("pdfs")
            if var_split.get():
                selected.append("split_results")
            if var_mineru.get():
                selected.append("mineru_results")
            if var_translated.get():
                selected.append("translated_results")
            if var_final.get():
                selected.append("final_output") 
            if not selected:
                self._show_custom_messagebox("提示", "未选择任何目录，取消清理。", "info")
                top.destroy()
                return
            msg = "将清空以下目录的内容（目录本身保留）：\n" + "\n".join([f"- {d}" for d in selected]) + "\n\n确定继续？"
            if not self._custom_askyesno("确认清空", msg):
                return
            from cleanup import clear_directories_contents
            base_path = Path.cwd()
            success, failed = clear_directories_contents(selected, base_path)
            if failed:
                error_msg = "部分目录清空失败：\n" + "\n".join([f"{f[0]}: {f[1]}" for f in failed])
                self._show_custom_messagebox("清理错误", error_msg, "error")
            else:
                self._show_custom_messagebox("清理完成", f"已成功清空 {len(success)} 个目录。", "info")
            top.destroy()

        ttk.Button(btn_frame, text="确定清空", command=do_clean).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="取消", command=top.destroy).pack(side=tk.LEFT, padx=5)

    # ==================== 启动处理 ====================
    def _start_process(self):
        """启动后台翻译进程（热加载：先保存配置）"""
        # 热加载：保存当前所有配置到 settings.json
        self._save_settings()

        try:
            from main import run_pipeline
        except ImportError as e:
            print(f"❌ 导入翻译模块失败: {e}")
            print("   请确保 llama-cpp-python 已正确安装。")
            print("   点击「环境检查」查看安装建议。")
            with open("error.log", "w", encoding="utf-8") as f:
                f.write(f"导入错误: {traceback.format_exc()}")
            return

        # 参数校验
        if not self.mineru_token.get().strip() and self.parse_engine.get() == "mineru":
            self._show_custom_messagebox("错误", "请输入 MinerU Token", "error")
            return
        if not self.paddleocr_token.get().strip() and self.parse_engine.get() == "paddleocr":
            self._show_custom_messagebox("错误", "请输入 PaddleOCR Token", "error")
            return
        if not self.openai_api_enabled.get() and not Path(self.model_path.get()).exists():
            self._show_custom_messagebox("错误", f"模型文件不存在: {self.model_path.get()}", "error")
            return
        if not Path(self.input_folder.get()).is_dir():
            self._show_custom_messagebox("错误", f"输入文件夹不存在: {self.input_folder.get()}", "error")
            return

        # 构建配置对象
        extra = [k for k, v in self.extra_formats.items() if v.get()]
        cfg = Config()
        cfg.input_folder = self.input_folder.get()
        cfg.split_output = "./split_results"
        cfg.mineru_output = "./mineru_results"
        cfg.translated_output = "./translated_results"
        cfg.final_output = self.output_root.get()
        cfg.mineru_token = self.mineru_token.get()
        cfg.model_path = self.model_path.get()
        cfg.pages_per_file = self.pages_per_file.get()
        cfg.target_lang = self.target_lang.get()
        cfg.extra_formats = extra if extra else None
        cfg.skip_mineru = self.skip_mineru.get()
        cfg.skip_translation = self.skip_translation.get()
        cfg.n_ctx = self.n_ctx.get()
        # 获取合并页面尺寸
        if self.pdf_merger_page_size.get() == "自定义":
            page_size_str = f"{self.pdf_custom_width.get().strip()}x{self.pdf_custom_height.get().strip()}"
        else:
            page_size_str = self.pdf_merger_page_size.get()
        cfg.pdf_merger_page_size = page_size_str
        cfg.pdf_merger_margin = self.pdf_merger_margin.get()
        cfg.translation_temperature = self.translation_temperature.get()
        cfg.translation_top_p = self.translation_top_p.get()
        cfg.translation_top_k = self.translation_top_k.get()
        cfg.translation_repeat_penalty = self.translation_repeat_penalty.get()
        cfg.translation_max_tokens = self.translation_max_tokens.get()
        cfg.target_style = self.target_style.get()
        cfg.background_text = self.background_text.get()
        cfg.translation_glossary = self.translation_glossary.get()
        cfg.parse_engine = self.parse_engine.get()
        cfg.paddleocr_token = self.paddleocr_token.get()
        cfg.paddleocr_use_chart = self.paddleocr_use_chart.get()
        cfg.paddleocr_use_unwarp = self.paddleocr_use_unwarp.get()
        cfg.paddleocr_use_orientation = self.paddleocr_use_orientation.get()
        cfg.paddleocr_model = self.paddleocr_model.get()
        cfg.openai_api_enabled = self.openai_api_enabled.get()
        cfg.openai_api_key = self.openai_api_key.get()
        cfg.openai_api_base = self.openai_api_base.get()
        cfg.openai_model = self.openai_model.get()
        cfg.openai_timeout = self.openai_timeout.get()
        cfg.openai_extra_body = self.openai_extra_body.get().strip()
        self.current_cfg = cfg

        # 禁用按钮
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.env_btn.config(state=tk.DISABLED)
        self.clean_btn.config(state=tk.DISABLED)
        self.adv_btn.config(state=tk.DISABLED)
        self.merge_btn.config(state=tk.DISABLED)
        self.screenshot_btn.config(state=tk.DISABLED)
        self.running = True
        self.log_text.delete(1.0, tk.END)
        print("🚀 正在启动处理流程...\n")

        # 启动子进程
        cfg_dict = {k: v for k, v in cfg.__dict__.items() if not k.startswith('_')}
        self.process = multiprocessing.Process(
            target=run_pipeline_in_process,
            args=(cfg_dict,),
            daemon=True
        )
        self.process.start()
        self._check_process_status()

    def _check_process_status(self):
        """周期性检查子进程是否结束"""
        if self.running and self.process is not None:
            if not self.process.is_alive():
                self._process_finished()
            else:
                self.root.after(500, self._check_process_status)

    def _process_finished(self):
        """子进程结束后的清理"""
        self.running = False
        self.process = None
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self.env_btn.config(state=tk.NORMAL)
        self.clean_btn.config(state=tk.NORMAL)
        self.adv_btn.config(state=tk.NORMAL)
        self.merge_btn.config(state=tk.NORMAL)
        self.screenshot_btn.config(state=tk.NORMAL)
        print("\n✅ 处理完成")
        # 自动打开输出文件夹
        if self.current_cfg:
            output_dir = Path(self.current_cfg.final_output)
            if output_dir.exists():
                self._open_folder(output_dir)
            else:
                print(f"⚠️ 输出目录不存在: {output_dir}")

    def _stop_process(self):
        """强制停止子进程"""
        if self.process is not None and self.process.is_alive():
            self.process.terminate()
            self.process.join(timeout=2)
            if self.process.is_alive():
                self.process.kill()
                self.process.join()
            print("\n⛔ 已强制停止后台任务")
        self.running = False
        self.process = None
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self.env_btn.config(state=tk.NORMAL)
        self.clean_btn.config(state=tk.NORMAL)
        self.adv_btn.config(state=tk.NORMAL)
        self.merge_btn.config(state=tk.NORMAL)
        self.screenshot_btn.config(state=tk.NORMAL)


if __name__ == "__main__":
    multiprocessing.freeze_support()  # 支持打包后的多进程
    root = tk.Tk()
    app = App(root)
    root.mainloop()
