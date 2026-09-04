#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
悬浮框截图模块（标题栏位置自适应，无多余按钮）
- 鼠标拖拽划定初始区域（十字光标，拖拽有效，点击/右键/ESC取消）
- 红框内部区域与鼠标选定区域完全一致（无论标题栏在顶部或底部）
- 标题栏根据屏幕边缘自适应：窗口底部超出屏幕时移至顶部，否则在底部
- 窗口宽度<300时自动隐藏"截图工具"标签，保留截图、重选、结束按钮
- 支持拖动标题栏移动窗口（无边缘缩放）
- 点击"截图"保存当前红框区域（截图前自动隐藏红框，使截图中不含红框）
- 点击"重选"重新划定区域，点击"结束"退出
- 圈选区域最小宽度150px，最小高度20px，标题栏高度30px
- 使用 grid 布局，Canvas 居中，标题栏在第一或第三行
- 拖拽时显示选定框尺寸（宽×高），选框内为红色，标题栏为白色
- 支持高DPI缩放，截图捕获物理像素，提升清晰度
"""

import tkinter as tk
from tkinter import ttk
from PIL import ImageGrab
from pathlib import Path
import time
import ctypes
import sys

# ---------- 高DPI支持 ----------
def get_screen_scaling():
    """
    获取Windows DPI缩放比例
    返回: 缩放系数（例如1.5表示150%缩放）
    """
    try:
        user32 = ctypes.windll.user32
        # 物理分辨率（实际像素）
        physical_width = user32.GetSystemMetrics(0)
        physical_height = user32.GetSystemMetrics(1)
        # 逻辑分辨率（系统缩放后的像素）
        root = tk.Tk()
        logical_width = root.winfo_screenwidth()
        logical_height = root.winfo_screenheight()
        root.destroy()
        scale_x = physical_width / logical_width
        scale_y = physical_height / logical_height
        return max(scale_x, scale_y)
    except:
        return 1.0


class FloatingScreenshot:
    TITLE_H = 30
    BORDER_W = 2
    MIN_WIDTH = 150
    MIN_HEIGHT = 20
    MIN_WIN_HEIGHT = 60

    def __init__(self, master, callback):
        self.master = master
        self.callback = callback
        self.saved_files = []
        self.window = None
        self.canvas = None
        self.selector = None
        self.canvas_sel = None
        self.title_bar = None
        self.title_row = None          # 0: 顶部, 1: 底部
        self._is_closed = False
        self._was_minimized = False
        self._minimized_geometry = None
        self.rect_sel = None
        self.start_x_sel = None
        self.start_y_sel = None
        self._dragged = False
        self.size_text_id = None       # 画布上的尺寸文本ID
        self.size_label = None         # 标题栏上的尺寸标签
        self._start_region_selector()

    # ---------- 第一步：鼠标划定初始区域 ----------
    def _start_region_selector(self):
        self.selector = tk.Toplevel(self.master)
        self.selector.attributes('-fullscreen', True, '-alpha', 0.3, '-topmost', True)
        self.selector.configure(bg='gray')
        self.selector.grab_set()

        self.canvas_sel = tk.Canvas(self.selector, bg='gray', highlightthickness=0, cursor="crosshair")
        self.canvas_sel.pack(fill=tk.BOTH, expand=True)

        self.canvas_sel.bind('<ButtonPress-1>', self._on_press_sel)
        self.canvas_sel.bind('<B1-Motion>', self._on_drag_sel)
        self.canvas_sel.bind('<ButtonRelease-1>', self._on_release_sel)
        self.canvas_sel.bind('<Button-3>', lambda e: self._cancel_selector())
        self.canvas_sel.bind('<Key-Escape>', lambda e: self._cancel_selector())
        self.canvas_sel.focus_set()

    def _on_press_sel(self, event):
        self.start_x_sel = event.x
        self.start_y_sel = event.y
        self._dragged = False
        # 清除旧的尺寸文本
        if self.size_text_id:
            self.canvas_sel.delete(self.size_text_id)
            self.size_text_id = None
        if self.rect_sel:
            self.canvas_sel.delete(self.rect_sel)
            self.rect_sel = None

    def _on_drag_sel(self, event):
        if self.start_x_sel is None:
            return
        self._dragged = True
        # 更新矩形
        if self.rect_sel:
            self.canvas_sel.delete(self.rect_sel)
        self.rect_sel = self.canvas_sel.create_rectangle(
            self.start_x_sel, self.start_y_sel, event.x, event.y,
            outline='red', width=2
        )
        # 计算宽高
        x1, y1 = self.start_x_sel, self.start_y_sel
        x2, y2 = event.x, event.y
        w = abs(x2 - x1)
        h = abs(y2 - y1)
        # 显示尺寸文本（红色）
        text = f"{w}×{h}"
        if self.size_text_id:
            self.canvas_sel.coords(self.size_text_id, (x1+x2)//2, (y1+y2)//2 - 10)
            self.canvas_sel.itemconfig(self.size_text_id, text=text)
        else:
            self.size_text_id = self.canvas_sel.create_text(
                (x1+x2)//2, (y1+y2)//2 - 10,
                text=text,
                fill='red', font=('Arial', 12, 'bold'),
                tags='size_text'
            )

    def _on_release_sel(self, event):
        if not self._dragged:
            self._cancel_selector()
            return
        x1 = min(self.start_x_sel, event.x)
        y1 = min(self.start_y_sel, event.y)
        x2 = max(self.start_x_sel, event.x)
        y2 = max(self.start_y_sel, event.y)
        if x2 - x1 < self.MIN_WIDTH:
            x2 = x1 + self.MIN_WIDTH
        if y2 - y1 < self.MIN_HEIGHT:
            y2 = y1 + self.MIN_HEIGHT
        self.selector.destroy()
        self.master.after(10, lambda: self._create_window(x1, y1, x2, y2))

    def _cancel_selector(self):
        self.selector.destroy()
        self._finish(False, "用户取消")

    # ---------- 第二步：创建悬浮窗 ----------
    def _create_window(self, x1, y1, x2, y2):
        b = self.BORDER_W
        th = self.TITLE_H
        sel_w = x2 - x1
        sel_h = y2 - y1
        if sel_h + 2 * b + th < self.MIN_WIN_HEIGHT:
            sel_h = self.MIN_WIN_HEIGHT - 2 * b - th
            y2 = y1 + sel_h
        win_w = sel_w + 2 * b

        self.window = tk.Toplevel(self.master)
        self.window.overrideredirect(True)
        self.window.attributes('-topmost', True)
        self.transparent_color = '#abcdef'
        self.window.configure(bg=self.transparent_color)
        self.window.attributes('-transparentcolor', self.transparent_color)

        # 判断标题栏位置（基于屏幕底部溢出）
        screen_height = self.window.winfo_screenheight()
        win_y_base = y1 - b
        win_h_base = sel_h + 2 * b + th
        if win_y_base + win_h_base > screen_height:
            self.title_row = 0      # 标题栏在顶部
            win_y = y1 - b - th     # 向上扩展出标题栏空间
        else:
            self.title_row = 1      # 标题栏在底部
            win_y = y1 - b
        win_h = sel_h + 2 * b + th

        win_x = x1 - b

        self.window.geometry(f"{win_w}x{win_h}+{win_x}+{win_y}")
        self.window.resizable(False, False)
        self.window.wm_minsize(win_w, win_h)
        self.window.update_idletasks()

        self.window.bind('<Map>', self._on_window_restore)

        # grid 布局
        canvas_row = 0 if self.title_row == 1 else 1   # 标题栏在底部则canvas在0，否则在1
        title_row = 1 if self.title_row == 1 else 0

        self.window.grid_rowconfigure(canvas_row, weight=1)
        self.window.grid_rowconfigure(title_row, weight=0)
        self.window.grid_columnconfigure(0, weight=1)

        self.canvas = tk.Canvas(self.window, bg=self.transparent_color, highlightthickness=0)
        self.canvas.grid(row=canvas_row, column=0, sticky="nsew")

        self.title_bar = tk.Frame(self.window, bg='#2b2b2b', height=th)
        self.title_bar.grid(row=title_row, column=0, sticky="ew")
        self.title_bar.grid_propagate(False)

        # 构建标题栏内容
        self.title_label = tk.Label(self.title_bar, text="截图工具", bg='#2b2b2b', fg='white',
                                    font=('Microsoft YaHei', 10))
        # 新增：尺寸显示标签（白色）
        self.size_label = tk.Label(self.title_bar, text=f"{sel_w}×{sel_h}", bg='#2b2b2b', fg='white',
                                   font=('Microsoft YaHei', 10, 'bold'))
        self.btn_frame = tk.Frame(self.title_bar, bg='#2b2b2b')

        self.capture_btn = tk.Button(self.btn_frame, text="截图", command=self._take_screenshot,
                                     bg='#3c3c3c', fg='white', relief=tk.FLAT,
                                     font=('Microsoft YaHei', 9))
        self.capture_btn.pack(side=tk.LEFT, padx=2)

        self.reset_btn = tk.Button(self.btn_frame, text="重选", command=self._reset_selection,
                                   bg='#3c3c3c', fg='white', relief=tk.FLAT,
                                   font=('Microsoft YaHei', 9))
        self.reset_btn.pack(side=tk.LEFT, padx=2)

        self.end_btn = tk.Button(self.btn_frame, text="结束", command=self._on_close,
                                 bg='#3c3c3c', fg='white', relief=tk.FLAT,
                                 font=('Microsoft YaHei', 9))
        self.end_btn.pack(side=tk.LEFT, padx=2)

        # 布局：标题标签 → 尺寸标签 → 按钮框架
        self.title_label.pack(side=tk.LEFT, padx=(10, 5))
        self.size_label.pack(side=tk.LEFT, padx=(0, 5))
        self.btn_frame.pack(side=tk.RIGHT, padx=5)

        # 标题栏拖动
        self.title_bar.bind('<ButtonPress-1>', self._start_move)
        self.title_bar.bind('<B1-Motion>', self._on_move)
        self.title_bar.bind('<ButtonRelease-1>', self._stop_move)

        self._draw_border()
        self._update_title_bar()
        self.window.update_idletasks()

    def _ensure_title_bar_visible(self):
        if self.title_bar:
            self.title_bar.config(height=self.TITLE_H)
            self.title_bar.grid_propagate(False)
            self.window.update_idletasks()

    def _update_title_bar(self):
        if not self.window:
            return
        width = self.window.winfo_width()
        # 当宽度小于300时隐藏 "截图工具" 和尺寸标签
        if width < 300:
            self.title_label.pack_forget()
            self.size_label.pack_forget()
        else:
            if not self.title_label.winfo_ismapped():
                self.title_label.pack(side=tk.LEFT, padx=(10, 5))
            if not self.size_label.winfo_ismapped():
                self.size_label.pack(side=tk.LEFT, padx=(0, 5))
        self.title_bar.update_idletasks()

    # ---------- 窗口移动 ----------
    def _start_move(self, event):
        self.drag_data = {'x': event.x_root - self.window.winfo_x(),
                          'y': event.y_root - self.window.winfo_y()}

    def _on_move(self, event):
        x = event.x_root - self.drag_data['x']
        y = event.y_root - self.drag_data['y']
        self.window.geometry(f"+{x}+{y}")

    def _stop_move(self, event):
        pass

    # ---------- 窗口控制 ----------
    def _on_window_restore(self, event):
        if self._was_minimized:
            self._was_minimized = False
            if self._minimized_geometry:
                self.window.after_idle(lambda: self.window.geometry(self._minimized_geometry))
            self.window.update_idletasks()
            self._ensure_title_bar_visible()
            self._draw_border()
            self._update_title_bar()

    def _on_close(self):
        self._finish(True, f"截图完成，共 {len(self.saved_files)} 张")

    # ---------- 重选 ----------
    def _reset_selection(self):
        if self.window:
            self.window.destroy()
        self.window = None
        self.canvas = None
        self._is_closed = False
        self.saved_files = []
        self._was_minimized = False
        self._minimized_geometry = None
        self._start_region_selector()

    # ---------- 红框绘制 ----------
    def _draw_border(self):
        self.window.update_idletasks()
        canvas_w = self.canvas.winfo_width()
        canvas_h = self.canvas.winfo_height()
        if canvas_w <= 10 or canvas_h <= 10:
            return
        b = self.BORDER_W
        self.canvas.delete('all')
        # 红框边缘与 Canvas 边缘保持 b 像素距离
        self.canvas.create_rectangle(b, b,
                                     canvas_w - b, canvas_h - b,
                                     outline='red', width=2, tags='border')
        self.canvas.update_idletasks()

    # ---------- 截图（隐藏红框后截图，支持高DPI） ----------
    def _take_screenshot(self):
        border_items = self.canvas.find_withtag('border')
        try:
            # 获取屏幕缩放比例
            scale = get_screen_scaling()

            # 隐藏红框
            if border_items:
                self.canvas.itemconfig(border_items[0], state='hidden')
            self.window.update()  # 刷新界面，使隐藏生效

            win_x = self.window.winfo_x()
            win_y = self.window.winfo_y()
            canvas_x = win_x
            canvas_y = win_y + (self.TITLE_H if self.title_row == 0 else 0)
            canvas_w = self.canvas.winfo_width()
            canvas_h = self.canvas.winfo_height()
            b = self.BORDER_W

            # 计算逻辑坐标（未缩放）
            left_log = canvas_x + b
            top_log = canvas_y + b
            right_log = canvas_x + canvas_w - b
            bottom_log = canvas_y + canvas_h - b

            # 转换为物理坐标（乘以缩放比例）
            left = int(left_log * scale)
            top = int(top_log * scale)
            right = int(right_log * scale)
            bottom = int(bottom_log * scale)

            bbox = (left, top, right, bottom)
            img = ImageGrab.grab(bbox=bbox)

            pdfs_dir = Path("pdfs")
            pdfs_dir.mkdir(parents=True, exist_ok=True)
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            idx = len(self.saved_files)
            filename = f"float_{timestamp}_{idx:02d}.png"
            filepath = pdfs_dir / filename
            img.save(filepath, "PNG")
            self.saved_files.append(str(filepath))
            print(f"✅ 截图已保存: {filepath}")
        except Exception as e:
            print(f"❌ 截图失败: {e}")
        finally:
            # 恢复红框
            if border_items:
                self.canvas.itemconfig(border_items[0], state='normal')
            self.window.update()

    def _finish(self, success, message):
        if self._is_closed:
            return
        self._is_closed = True
        if self.window:
            self.window.destroy()
        if self.callback:
            self.callback(success, message, self.saved_files)


def start_floating_screenshot(parent, on_finish):
    return FloatingScreenshot(parent, on_finish)
