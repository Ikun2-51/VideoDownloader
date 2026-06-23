#!/usr/bin/env python3
"""
Video Downloader — 桌面视频下载器
基于 yt-dlp + Tkinter 的 Windows 桌面视频下载工具。
支持 YouTube、Bilibili、Twitter/X、TikTok 等 1800+ 网站。

特性：
- 单视频 / 批量排队下载
- iOS 浅色 / iOS 深色 / Obsidian 深色 三套主题
- 自定义调色盘 — 自由编辑全部颜色
- 主题自动持久化
- 一键导出源码压缩包
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, colorchooser
import os
import re
import sys
import json
import queue
import threading
import tempfile
import shutil
import subprocess
import zipfile
from datetime import datetime
from dataclasses import dataclass, field, asdict
from pathlib import Path

# ── 自定义异常 ──────────────────────────────────────────

class DownloadCancelled(Exception):
    """用户取消下载"""
    pass


# ── 主题数据类 ──────────────────────────────────────────

@dataclass
class ColorTheme:
    """完整颜色主题"""
    name: str
    bg_primary: str      # 主背景
    bg_secondary: str    # 卡片/面板
    bg_tertiary: str     # 输入框/悬停
    text_primary: str    # 主文字
    text_secondary: str  # 次要文字
    text_muted: str      # 占位文字
    accent: str          # 强调色
    accent_hover: str    # 悬停强调色
    border: str          # 边框/分隔线
    success: str         # 成功绿
    error: str           # 错误红
    warning: str         # 警告黄

    def as_hex_dict(self) -> dict:
        return asdict(self)

    def clone(self, name: str = None) -> "ColorTheme":
        d = asdict(self)
        if name:
            d["name"] = name
        return ColorTheme(**d)


# ── 预设主题 ────────────────────────────────────────────

IOS_LIGHT = ColorTheme(
    name="iOS 浅色",
    bg_primary="#F2F2F7",
    bg_secondary="#FFFFFF",
    bg_tertiary="#E5E5EA",
    text_primary="#000000",
    text_secondary="#3C3C4399",
    text_muted="#8E8E93",
    accent="#007AFF",
    accent_hover="#0056CC",
    border="#D1D1D6",
    success="#34C759",
    error="#FF3B30",
    warning="#FF9500",
)

IOS_DARK = ColorTheme(
    name="iOS 深色",
    bg_primary="#000000",
    bg_secondary="#1C1C1E",
    bg_tertiary="#2C2C2E",
    text_primary="#FFFFFF",
    text_secondary="#EBEBF599",
    text_muted="#98989D",
    accent="#0A84FF",
    accent_hover="#409CFF",
    border="#38383A",
    success="#30D158",
    error="#FF453A",
    warning="#FF9F0A",
)

OBSIDIAN_DARK = ColorTheme(
    name="Obsidian 深色",
    bg_primary="#0d0d0d",
    bg_secondary="#1a1a1a",
    bg_tertiary="#2a2a2a",
    text_primary="#cfcfcf",
    text_secondary="#808080",
    text_muted="#595959",
    accent="#6930C7",
    accent_hover="#7c3aed",
    border="#222222",
    success="#4ade80",
    error="#f87171",
    warning="#fbbf24",
)

THEME_PRESETS: dict[str, ColorTheme] = {
    "iOS 浅色":       IOS_LIGHT,
    "iOS 深色":       IOS_DARK,
    "Obsidian 深色":  OBSIDIAN_DARK,
}


# ── 下载任务数据类 ──────────────────────────────────────

@dataclass
class DownloadTask:
    """单个下载任务的状态"""
    url: str
    title: str = ""
    duration: str = ""
    uploader: str = ""
    status: str = "pending"   # pending | parsing | queued | downloading | completed | failed | cancelled
    format_id: str = ""
    format_label: str = ""
    info: dict | None = None
    progress: float = 0.0
    speed: str = "--"
    eta: str = "--"
    error_msg: str = ""
    filepath: str = ""
    formats: list = field(default_factory=list)


# ── 平台 URL 模式 ──────────────────────────────────────

PLATFORM_PATTERNS = {
    "youtube":  r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/)",
    "bilibili": r"bilibili\.com/video/",
    "twitter":  r"(?:twitter\.com|x\.com)/\w+/status/",
    "tiktok":   r"tiktok\.com/",
    "instagram": r"instagram\.com/(?:reel|p)/",
    "vimeo":    r"vimeo\.com/",
}

PLATFORM_NAMES = {
    "": "自动检测", "youtube": "YouTube", "bilibili": "Bilibili",
    "twitter": "Twitter / X", "tiktok": "TikTok",
    "instagram": "Instagram", "vimeo": "Vimeo",
}

# ── 应用常量 ────────────────────────────────────────────

FONT_UI   = "Microsoft YaHei"
FONT_MONO = "Consolas"
FONT_TITLE = "Microsoft YaHei"

PAD_TIGHT   = 4
PAD         = 8
PAD_COMFORT = 12
PAD_STD     = 16
PAD_WIDE    = 24
PAD_XL      = 32

APP_VERSION = "1.2.0"
CONFIG_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "VideoDownloader")
CONFIG_FILE = os.path.join(CONFIG_DIR, "theme.json")


# ── 主应用类 ────────────────────────────────────────────

class VideoDownloaderApp:
    """视频下载器主应用"""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Video Downloader")
        self.root.geometry("780x920")
        self.root.minsize(560, 720)
        self.root.configure(bg="#000000")  # 启动默认色，等主题加载后更新

        self._set_app_id()

        # ── 加载主题 ──────────────────────────────
        self.theme: ColorTheme = self._load_theme()

        # ── 全局字体 ─────────────────────────────
        self.font_ui = (FONT_UI, 11)
        self.font_small = (FONT_UI, 9)
        self.font_heading = (FONT_UI, 14, "bold")
        self.font_title = (FONT_TITLE, 26, "bold")

        # ── 状态变量 ──────────────────────────────
        self.platform_var   = tk.StringVar(value="")
        self.save_path_var  = tk.StringVar(value=os.path.expanduser("~\\Downloads"))
        self.format_var     = tk.StringVar()
        self.theme_name_var = tk.StringVar(value=self.theme.name)

        # 视频信息（单视频模式）
        self.video_info     = None
        self.video_formats  = []
        self.thumbnail_img  = None
        self._thumb_path    = None

        # 批量下载
        self.download_queue: list[DownloadTask] = []
        self._current_task: DownloadTask | None = None
        self._batch_mode = False

        # 下载状态
        self.downloading    = False
        self.cancel_requested = False
        self.download_thread = None
        self.progress_queue = queue.Queue()
        self.parse_queue    = queue.Queue()
        self._single_parse_result = None  # 单视频解析结果 {"status": ..., "data": ...}
        self._parse_after_id = None
        self._poll_after_id  = None

        # 历史
        self.download_history = []

        # ffmpeg
        self.has_ffmpeg = self._check_ffmpeg()

        # ── 构建 UI ──────────────────────────────
        self._setup_styles()
        self._build_ui()
        self._apply_theme_colors()  # 应用主题到 tk widget
        self._bind_keys()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ═══════════════════════════════════════════════════════
    # 主题系统
    # ═══════════════════════════════════════════════════════

    def _load_theme(self) -> ColorTheme:
        """从配置文件加载主题，失败则用默认"""
        try:
            if os.path.isfile(CONFIG_FILE):
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                theme = ColorTheme(**data)
                return theme
        except Exception:
            pass
        return OBSIDIAN_DARK.clone()

    def _save_theme(self):
        """持久化当前主题到文件"""
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(asdict(self.theme), f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def _apply_theme(self, theme: ColorTheme):
        """切换主题：重建 ttk 样式 + 更新 tk widget 颜色"""
        self.theme = theme
        self.theme_name_var.set(theme.name)
        self._setup_styles()         # 重建 ttk style
        self._apply_theme_colors()   # 更新 tk widget
        self._refresh_queue_ui()     # 刷新 Treeview
        self._save_theme()

    def _apply_theme_colors(self):
        """更新所有 tk 原生 widget 的颜色"""
        t = self.theme
        self.root.configure(bg=t.bg_primary)
        if hasattr(self, '_canvas'):
            self._canvas.configure(bg=t.bg_primary)

        # 遍历更新所有 tk widget（排除 ttk）
        for widget_name in dir(self):
            obj = getattr(self, widget_name, None)
            if isinstance(obj, tk.Text):
                obj.configure(bg=t.bg_tertiary, fg=t.text_primary,
                              insertbackground=t.text_primary)
            elif isinstance(obj, tk.Listbox):
                obj.configure(bg=t.bg_secondary, fg=t.text_primary,
                              selectbackground=t.accent)
            elif isinstance(obj, tk.Canvas):
                obj.configure(bg=t.bg_primary)
            elif isinstance(obj, tk.Frame):
                obj.configure(bg=t.bg_secondary)

        # 更新特定标签
        for attr in ["pct_label", "speed_label", "eta_label",
                      "status_label", "queue_title_label"]:
            lbl = getattr(self, attr, None)
            if lbl and lbl.winfo_exists():
                try:
                    lbl.configure(background=t.bg_primary)
                except tk.TclError:
                    pass

    @staticmethod
    def _hex_to_rgb(hex_str: str) -> str:
        """#RRGGBB → 'R G B' 用于 tkinter 颜色参数"""
        h = hex_str.lstrip("#")
        if len(h) == 6:
            return f"#{h}"
        return hex_str

    # ═══════════════════════════════════════════════════════
    # 窗口设置
    # ═══════════════════════════════════════════════════════

    def _set_app_id(self):
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "com.tuberose.videodownloader")
        except Exception:
            pass

    def _bind_keys(self):
        self.root.bind("<Control-v>", lambda e: self._on_paste())
        self.root.bind("<Control-V>", lambda e: self._on_paste())
        self.root.bind("<Escape>", lambda e: self._cancel_all_downloads())

    # ═══════════════════════════════════════════════════════
    # 样式 (基于当前主题)
    # ═══════════════════════════════════════════════════════

    def _setup_styles(self):
        """配置 ttk 样式"""
        t = self.theme
        style = ttk.Style()
        style.theme_use("clam")

        # 解析 rgba 的 text_secondary 为纯色（Tkinter 不支持 rgba）
        sec = t.text_secondary
        if len(sec) == 9:  # #RRGGBBAA
            sec = sec[:7]

        style.configure(".",
            background=t.bg_primary, foreground=t.text_primary,
            fieldbackground=t.bg_tertiary, bordercolor=t.border,
            font=self.font_ui)

        style.configure("TFrame", background=t.bg_primary)
        style.configure("Card.TFrame", background=t.bg_secondary, relief="flat")

        style.configure("TLabel", background=t.bg_primary,
                        foreground=t.text_primary, font=self.font_ui)
        style.configure("Title.TLabel", font=self.font_title, foreground=t.accent)
        style.configure("Heading.TLabel", font=self.font_heading,
                        foreground=t.text_primary)
        style.configure("Card.TLabel", background=t.bg_secondary,
                        foreground=t.text_primary, font=self.font_ui)
        style.configure("CardHeading.TLabel", background=t.bg_secondary,
                        foreground=t.text_primary, font=(FONT_UI, 12, "bold"))
        style.configure("Muted.TLabel", foreground=t.text_muted,
                        font=self.font_small)
        style.configure("Success.TLabel", foreground=t.success)
        style.configure("Error.TLabel", foreground=t.error)
        style.configure("Warning.TLabel", foreground=t.warning)

        style.configure("TButton", background=t.bg_tertiary,
                        foreground=t.text_primary, borderwidth=1,
                        relief="flat", padding=(PAD_STD, PAD), font=self.font_ui)
        style.map("TButton",
            background=[("active", t.bg_tertiary), ("pressed", t.bg_tertiary)],
            foreground=[("active", t.text_primary)])

        style.configure("Accent.TButton", background=t.accent,
                        foreground="#ffffff", font=(FONT_UI, 12, "bold"),
                        borderwidth=0, padding=(PAD_WIDE, PAD_COMFORT))
        style.map("Accent.TButton",
            background=[("active", t.accent_hover), ("pressed", t.accent)],
            foreground=[("active", "#ffffff")])

        style.configure("Danger.TButton", background=t.error,
                        foreground="#ffffff", font=(FONT_UI, 12, "bold"),
                        borderwidth=0, padding=(PAD_WIDE, PAD_COMFORT))
        style.map("Danger.TButton",
            background=[("active", "#ef4444"), ("pressed", t.error)])

        style.configure("Small.TButton", font=self.font_small,
                        padding=(PAD, PAD_TIGHT))

        style.configure("TEntry", fieldbackground=t.bg_tertiary,
                        foreground=t.text_primary, borderwidth=1,
                        relief="solid", padding=8)
        style.map("TEntry",
            fieldbackground=[("focus", t.bg_tertiary)],
            bordercolor=[("focus", t.accent)])

        style.configure("TCombobox", fieldbackground=t.bg_tertiary,
                        foreground=t.text_primary, arrowcolor=t.text_primary,
                        background=t.bg_tertiary)
        style.map("TCombobox",
            fieldbackground=[("readonly", t.bg_tertiary), ("focus", t.bg_tertiary)],
            bordercolor=[("focus", t.accent)])

        self.root.option_add("*TCombobox*Listbox.background", t.bg_secondary)
        self.root.option_add("*TCombobox*Listbox.foreground", t.text_primary)
        self.root.option_add("*TCombobox*Listbox.selectBackground", t.accent)
        self.root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")

        style.configure("TProgressbar", background=t.accent,
                        troughcolor=t.bg_secondary, bordercolor=t.border)
        style.configure("TSeparator", background=t.border)

        # Treeview
        style.configure("Queue.Treeview",
            background=t.bg_secondary, foreground=t.text_primary,
            fieldbackground=t.bg_secondary, borderwidth=0,
            font=self.font_ui, rowheight=28)
        style.configure("Queue.Treeview.Heading",
            background=t.bg_tertiary, foreground=t.text_muted,
            font=(FONT_UI, 9, "bold"), borderwidth=0)
        style.map("Queue.Treeview",
            background=[("selected", t.accent)],
            foreground=[("selected", "#ffffff")])

    # ═══════════════════════════════════════════════════════
    # UI 构建
    # ═══════════════════════════════════════════════════════

    def _build_ui(self):
        t = self.theme

        self.main_frame = ttk.Frame(self.root, padding=(PAD_XL, PAD_WIDE))
        self.main_frame.pack(fill=tk.BOTH, expand=True)

        self._canvas = tk.Canvas(self.main_frame, bg=t.bg_primary,
                                  highlightthickness=0, bd=0)
        self._scrollbar = ttk.Scrollbar(self.main_frame, orient=tk.VERTICAL,
                                         command=self._canvas.yview)
        self._scroll_frame = ttk.Frame(self._canvas)

        self._scroll_frame.bind("<Configure>",
            lambda e: self._canvas.configure(scrollregion=self._canvas.bbox("all")))
        self._canvas_window = self._canvas.create_window(
            (0, 0), window=self._scroll_frame, anchor="nw", tags="scroll_frame")
        self._canvas.configure(yscrollcommand=self._scrollbar.set)
        self._canvas.bind("<Configure>", self._on_canvas_configure)
        self._canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._build_title_bar(self._scroll_frame)
        self._build_url_section(self._scroll_frame)
        self._build_queue_section(self._scroll_frame)
        self._build_video_info(self._scroll_frame)
        self._build_format_section(self._scroll_frame)
        self._build_download_button(self._scroll_frame)
        self._build_progress_section(self._scroll_frame)
        self._build_history_section(self._scroll_frame)
        self._build_status_bar(self.main_frame)

    def _on_canvas_configure(self, event):
        self._canvas.itemconfig(self._canvas_window, width=event.width)
        if self._scroll_frame.winfo_reqheight() > event.height:
            self._scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        else:
            self._scrollbar.pack_forget()

    def _build_title_bar(self, parent):
        """顶部栏：标题 + 主题切换 + 导出按钮"""
        t = self.theme

        bar = ttk.Frame(parent)
        bar.pack(fill=tk.X, pady=(0, PAD_WIDE))

        # 左侧标题
        left = ttk.Frame(bar)
        left.pack(side=tk.LEFT)
        ttk.Label(left, text="Video Downloader", style="Title.TLabel").pack(anchor="w")
        ttk.Label(left, text=f"v{APP_VERSION}  ·  支持 1800+ 网站",
                  style="Muted.TLabel").pack(anchor="w", pady=(PAD_TIGHT, 0))

        # 右侧操作按钮
        right = ttk.Frame(bar)
        right.pack(side=tk.RIGHT)

        # 主题切换
        ttk.Label(right, text="主题", style="Muted.TLabel").pack(side=tk.LEFT,
                  padx=(0, PAD_TIGHT))
        self.theme_combo = ttk.Combobox(
            right, textvariable=self.theme_name_var,
            values=list(THEME_PRESETS.keys()) + (["自定义"] if self.theme.name not in THEME_PRESETS else []),
            state="readonly", width=14, font=self.font_small)
        self.theme_combo.pack(side=tk.LEFT, padx=(0, PAD))
        self.theme_combo.bind("<<ComboboxSelected>>", self._on_theme_select)

        # 调色盘编辑按钮
        self.palette_btn = ttk.Button(right, text="🎨 调色盘",
                                       command=self._open_palette_editor,
                                       style="Small.TButton")
        self.palette_btn.pack(side=tk.LEFT, padx=(0, PAD))

        # 导出按钮
        self.export_btn = ttk.Button(right, text="📦 导出",
                                      command=self._export_zip,
                                      style="Small.TButton")
        self.export_btn.pack(side=tk.LEFT)

        # FFmpeg 警告 + 一键下载
        if not self.has_ffmpeg:
            self.ffmpeg_warn_frame = ttk.Frame(bar)
            self.ffmpeg_warn_frame.pack(side=tk.LEFT, padx=(PAD, 0))
            ttk.Label(self.ffmpeg_warn_frame, text="⚠ FFmpeg 未安装",
                      style="Warning.TLabel", font=self.font_small).pack(side=tk.LEFT)
            self.ffmpeg_dl_btn = ttk.Button(self.ffmpeg_warn_frame,
                text="📥 一键安装",
                command=self._install_ffmpeg,
                style="Small.TButton")
            self.ffmpeg_dl_btn.pack(side=tk.LEFT, padx=(PAD_TIGHT, 0))

        ttk.Separator(parent, orient=tk.HORIZONTAL).pack(
            fill=tk.X, pady=(PAD_STD, PAD_STD))

    def _build_url_section(self, parent):
        t = self.theme
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.X, pady=(0, PAD_STD))

        ttk.Label(frame, text="视频链接（每行一个）",
                  style="Heading.TLabel").pack(anchor="w")

        text_frame = tk.Frame(frame, bg=t.bg_tertiary,
                               highlightbackground=t.border,
                               highlightthickness=1)
        text_frame.pack(fill=tk.X, pady=(PAD, 0))

        self.url_text = tk.Text(
            text_frame, height=3, wrap=tk.NONE,
            bg=t.bg_tertiary, fg=t.text_primary,
            insertbackground=t.text_primary,
            font=self.font_ui, borderwidth=0,
            highlightthickness=0, padx=8, pady=6, relief="flat")
        self.url_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # 绑定文本变更 — 防抖自动解析第一个 URL（单视频模式）
        self._url_text_after_id = None
        self.url_text.bind("<<Modified>>", self._on_url_text_modified)

        btn_row = ttk.Frame(frame)
        btn_row.pack(fill=tk.X, pady=(PAD, 0))

        self.paste_btn = ttk.Button(btn_row, text="粘贴", command=self._on_paste, width=6)
        self.paste_btn.pack(side=tk.LEFT, padx=(0, PAD))
        self.add_queue_btn = ttk.Button(btn_row, text="解析并加入队列",
                                         command=self._add_urls_to_queue,
                                         style="Accent.TButton")
        self.add_queue_btn.pack(side=tk.LEFT, padx=(0, PAD))
        self.clear_url_btn = ttk.Button(btn_row, text="清空输入",
                                         command=self._clear_url_text, width=8)
        self.clear_url_btn.pack(side=tk.LEFT)

        ttk.Label(btn_row, text="平台:").pack(side=tk.LEFT,
                  padx=(PAD_STD, PAD_TIGHT))
        self.platform_combo = ttk.Combobox(
            btn_row, textvariable=self.platform_var,
            values=list(PLATFORM_NAMES.values()),
            state="readonly", width=14, font=self.font_ui)
        self.platform_combo.set(PLATFORM_NAMES[""])
        self.platform_combo.pack(side=tk.LEFT)

    def _build_queue_section(self, parent):
        t = self.theme
        self.queue_frame = ttk.Frame(parent)

        q_header = ttk.Frame(self.queue_frame)
        q_header.pack(fill=tk.X)
        self.queue_title_label = ttk.Label(q_header, text="下载队列 (0)",
                                            style="Heading.TLabel")
        self.queue_title_label.pack(side=tk.LEFT)
        self.clear_done_btn = ttk.Button(q_header, text="清空已完成",
                                          command=self._clear_completed,
                                          style="Small.TButton")
        self.clear_done_btn.pack(side=tk.RIGHT)

        tree_frame = tk.Frame(self.queue_frame, bg=t.bg_secondary)
        tree_frame.pack(fill=tk.X, pady=(PAD, 0))

        columns = ("status", "title", "progress")
        self.queue_tree = ttk.Treeview(
            tree_frame, columns=columns, show="headings",
            style="Queue.Treeview", height=5, selectmode="browse")
        self.queue_tree.heading("status", text="状态", anchor="center")
        self.queue_tree.heading("title", text="视频")
        self.queue_tree.heading("progress", text="进度", anchor="center")
        self.queue_tree.column("status", width=50, anchor="center", stretch=False)
        self.queue_tree.column("title", width=420, stretch=True)
        self.queue_tree.column("progress", width=80, anchor="center", stretch=False)
        self.queue_tree.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.queue_tree.bind("<<TreeviewSelect>>", self._on_queue_select)
        self.queue_tree.bind("<Double-1>", self._on_queue_double_click)
        self.queue_tree.bind("<Button-3>", self._on_queue_right_click)

        q_btn_row = ttk.Frame(self.queue_frame)
        q_btn_row.pack(fill=tk.X, pady=(PAD, 0))

        self.batch_download_btn = ttk.Button(
            q_btn_row, text="▶  全部下载", style="Accent.TButton",
            command=self._start_all_downloads)
        self.batch_download_btn.pack(side=tk.LEFT, fill=tk.X, expand=True,
                                      padx=(0, PAD))
        self.cancel_queue_btn = ttk.Button(
            q_btn_row, text="取消全部", style="Danger.TButton",
            command=self._cancel_all_downloads)
        self.cancel_queue_btn.pack(side=tk.RIGHT, fill=tk.X, expand=True)

    def _build_video_info(self, parent):
        t = self.theme
        self.info_frame = ttk.Frame(parent, style="Card.TFrame")

        self.info_inner = ttk.Frame(self.info_frame, style="Card.TFrame")
        self.info_inner.pack(fill=tk.X, padx=PAD_STD, pady=PAD_STD)

        self.thumb_label = ttk.Label(self.info_inner, style="Card.TLabel")
        self.thumb_label.pack(side=tk.LEFT, padx=(0, PAD_STD))

        text_frame = ttk.Frame(self.info_inner, style="Card.TFrame")
        text_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.video_title_label = ttk.Label(
            text_frame, text="", style="CardHeading.TLabel", wraplength=420)
        self.video_title_label.pack(anchor="w")
        self.video_meta_label = ttk.Label(text_frame, text="", style="Muted.TLabel")
        self.video_meta_label.pack(anchor="w", pady=(PAD_TIGHT, 0))
        self.video_uploader_label = ttk.Label(text_frame, text="", style="Muted.TLabel")
        self.video_uploader_label.pack(anchor="w")

    def _build_format_section(self, parent):
        self.format_frame = ttk.Frame(parent)
        self.format_frame.pack(fill=tk.X, pady=(PAD_STD, PAD_STD))
        frame = self.format_frame

        ttk.Label(frame, text="分辨率", style="Heading.TLabel").pack(anchor="w")
        fmt_row = ttk.Frame(frame)
        fmt_row.pack(fill=tk.X, pady=(PAD, 0))
        self.format_combo = ttk.Combobox(
            fmt_row, textvariable=self.format_var,
            state="readonly", font=self.font_ui)
        self.format_combo.pack(fill=tk.X)

        ttk.Label(frame, text="保存到", style="Heading.TLabel").pack(
            anchor="w", pady=(PAD_STD, 0))
        path_row = ttk.Frame(frame)
        path_row.pack(fill=tk.X, pady=(PAD, 0))
        self.save_entry = ttk.Entry(path_row, textvariable=self.save_path_var,
                                     font=self.font_ui)
        self.save_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, PAD))
        self.browse_btn = ttk.Button(path_row, text="浏览...",
                                      command=self._browse_save_path, width=8)
        self.browse_btn.pack(side=tk.RIGHT)

    def _build_download_button(self, parent):
        self.dl_btn_frame = ttk.Frame(parent)
        self.dl_btn_frame.pack(fill=tk.X, pady=(PAD, PAD_STD))
        self.download_btn = ttk.Button(
            self.dl_btn_frame, text="⬇  下载当前视频",
            style="Accent.TButton", command=self._start_single_download)
        self.download_btn.pack(fill=tk.X, ipady=4)

    def _build_progress_section(self, parent):
        t = self.theme
        self.progress_frame = ttk.Frame(parent)

        self.progress_bar = ttk.Progressbar(
            self.progress_frame, mode="determinate", maximum=100)
        self.progress_bar.pack(fill=tk.X)

        self.pct_label = ttk.Label(
            self.progress_frame, text="0%",
            font=(FONT_UI, 28, "bold"), foreground=t.accent,
            background=t.bg_primary, anchor="center")
        self.pct_label.pack(pady=(PAD_STD, PAD))

        info_row = ttk.Frame(self.progress_frame)
        info_row.pack(fill=tk.X)
        self.speed_label = ttk.Label(info_row, text="速度: --", style="Muted.TLabel")
        self.speed_label.pack(side=tk.LEFT)
        self.eta_label = ttk.Label(info_row, text="剩余: --", style="Muted.TLabel")
        self.eta_label.pack(side=tk.RIGHT)

    def _build_history_section(self, parent):
        t = self.theme
        self.history_frame = ttk.Frame(parent)
        ttk.Separator(self.history_frame, orient=tk.HORIZONTAL).pack(
            fill=tk.X, pady=(PAD_STD, PAD_STD))

        hist_header = ttk.Frame(self.history_frame)
        hist_header.pack(fill=tk.X)
        ttk.Label(hist_header, text="下载历史", style="Heading.TLabel").pack(
            side=tk.LEFT)
        self.clear_hist_btn = ttk.Button(hist_header, text="清除",
                                          command=self._clear_history, width=6)
        self.clear_hist_btn.pack(side=tk.RIGHT)

        self.history_listbox = tk.Listbox(
            self.history_frame, bg=t.bg_secondary, fg=t.text_primary,
            selectbackground=t.accent, selectforeground="#ffffff",
            font=self.font_small, height=6, borderwidth=0,
            highlightthickness=0, activestyle="none")
        self.history_listbox.pack(fill=tk.X, pady=(PAD, 0))

    def _build_status_bar(self, parent):
        t = self.theme
        status_frame = ttk.Frame(parent)
        status_frame.pack(fill=tk.X, side=tk.BOTTOM, pady=(PAD_STD, 0))
        ttk.Separator(status_frame, orient=tk.HORIZONTAL).pack(fill=tk.X)

        self.status_label = ttk.Label(
            status_frame, text="✅  就绪", font=self.font_ui,
            foreground=t.text_secondary, background=t.bg_primary)
        self.status_label.pack(anchor="w", pady=(PAD, 0))

    # ═══════════════════════════════════════════════════════
    # 调色盘编辑器
    # ═══════════════════════════════════════════════════════

    def _open_palette_editor(self):
        """打开调色盘编辑窗口"""
        t = self.theme
        win = tk.Toplevel(self.root)
        win.title("🎨 调色盘设置")
        win.geometry("580x680")
        win.minsize(520, 600)
        win.configure(bg=t.bg_primary)
        win.transient(self.root)
        win.grab_set()

        # 复制主题用于编辑
        edit_theme = self.theme.clone()

        main = ttk.Frame(win, padding=(PAD_XL, PAD_WIDE))
        main.pack(fill=tk.BOTH, expand=True)

        # 标题
        ttk.Label(main, text="调色盘设置", style="Title.TLabel").pack(anchor="w")
        ttk.Label(main, text="自定义浅色系与深色系颜色",
                  style="Muted.TLabel").pack(anchor="w", pady=(PAD_TIGHT, PAD_STD))
        ttk.Separator(main, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=(0, PAD_STD))

        # 预设选择
        preset_frame = ttk.Frame(main)
        preset_frame.pack(fill=tk.X, pady=(0, PAD_STD))
        ttk.Label(preset_frame, text="预设主题",
                  style="Heading.TLabel").pack(side=tk.LEFT)
        preset_var = tk.StringVar(value=edit_theme.name)
        preset_combo = ttk.Combobox(
            preset_frame, textvariable=preset_var,
            values=list(THEME_PRESETS.keys()),
            state="readonly", width=16, font=self.font_ui)
        preset_combo.pack(side=tk.LEFT, padx=(PAD, 0))

        # Canvas 滚动区域
        canvas_frame = ttk.Frame(main)
        canvas_frame.pack(fill=tk.BOTH, expand=True, pady=(0, PAD_STD))

        canvas = tk.Canvas(canvas_frame, bg=t.bg_primary,
                            highlightthickness=0, bd=0)
        scrollbar = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL,
                                   command=canvas.yview)
        scroll_frame = ttk.Frame(canvas)

        scroll_frame.bind("<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas_window_id = canvas.create_window(
            (0, 0), window=scroll_frame, anchor="nw")

        canvas.configure(yscrollcommand=scrollbar.set)

        def _on_canvas_cfg(event):
            """Canvas 大小变化时调整内部 frame 宽度 + 显隐滚动条"""
            canvas.itemconfig(canvas_window_id, width=event.width)
            # 内容超出时显示滚动条
            req_h = scroll_frame.winfo_reqheight()
            if req_h > event.height:
                scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
            else:
                scrollbar.pack_forget()

        canvas.bind("<Configure>", _on_canvas_cfg)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        # 鼠标滚轮绑定
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _on_mousewheel))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

        # 颜色字段定义
        color_fields = [
            ("背景色", [
                ("主背景", "bg_primary"),
                ("卡片色", "bg_secondary"),
                ("输入框", "bg_tertiary"),
            ]),
            ("文字色", [
                ("主文字", "text_primary"),
                ("次要文字", "text_secondary"),
                ("占位文字", "text_muted"),
            ]),
            ("强调色", [
                ("强调色", "accent"),
                ("悬停强调", "accent_hover"),
                ("边框/分隔", "border"),
            ]),
            ("状态色", [
                ("成功", "success"),
                ("错误", "error"),
                ("警告", "warning"),
            ]),
        ]

        self._palette_vars: dict[str, tk.StringVar] = {}
        self._palette_labels: dict[str, ttk.Label] = {}
        self._palette_samples: dict[str, tk.Canvas] = {}

        for group_name, fields in color_fields:
            # 分组标题
            group_label = ttk.Label(scroll_frame, text=group_name,
                                     style="Heading.TLabel")
            group_label.pack(anchor="w", pady=(PAD_STD, PAD))

            for label, key in fields:
                row = ttk.Frame(scroll_frame)
                row.pack(fill=tk.X, pady=PAD_TIGHT)

                ttk.Label(row, text=label, width=10).pack(side=tk.LEFT)

                # 颜色色块
                sample = tk.Canvas(row, width=28, height=20,
                                    bg=getattr(edit_theme, key),
                                    highlightthickness=1,
                                    highlightbackground=t.border)
                sample.pack(side=tk.LEFT, padx=(0, PAD))
                self._palette_samples[key] = sample

                # 颜色值
                var = tk.StringVar(value=getattr(edit_theme, key))
                self._palette_vars[key] = var

                entry = ttk.Entry(row, textvariable=var, width=10,
                                   font=(FONT_MONO, 10))
                entry.pack(side=tk.LEFT, padx=(0, PAD))

                # 选择按钮
                def make_pick(k=key, v=var, s=sample):
                    return lambda: self._pick_color(k, v, s, edit_theme)

                pick_btn = ttk.Button(row, text="选择...",
                                       command=make_pick(), width=6)
                pick_btn.pack(side=tk.LEFT)

        # 底部按钮栏
        btn_bar = ttk.Frame(main)
        btn_bar.pack(fill=tk.X, pady=(PAD_STD, 0))

        ttk.Button(btn_bar, text="恢复默认",
                   command=lambda: self._reset_palette_defaults(edit_theme)
                   ).pack(side=tk.LEFT)

        ttk.Button(btn_bar, text="取消",
                   command=win.destroy).pack(side=tk.RIGHT, padx=(PAD, 0))
        ttk.Button(btn_bar, text="✓ 应用",
                   style="Accent.TButton",
                   command=lambda: self._apply_palette(edit_theme, win)
                   ).pack(side=tk.RIGHT)

        def on_preset_select(event):
            name = preset_var.get()
            if name in THEME_PRESETS:
                preset = THEME_PRESETS[name]
                for k, v in self._palette_vars.items():
                    v.set(getattr(preset, k))
                for k, s in self._palette_samples.items():
                    try:
                        s.configure(bg=getattr(preset, k))
                    except Exception:
                        pass
                # 更新 edit_theme
                for k in self._palette_vars:
                    setattr(edit_theme, k, getattr(preset, k))

        preset_combo.bind("<<ComboboxSelected>>", on_preset_select)

        # 存储编辑窗口引用
        self._palette_window = win
        self._palette_edit_theme = edit_theme

        # 触发初始布局计算，确保滚动条状态正确
        win.update_idletasks()

    def _pick_color(self, key: str, var: tk.StringVar,
                     sample: tk.Canvas, edit_theme: ColorTheme):
        """打开系统颜色选择器"""
        current = var.get()
        result = colorchooser.askcolor(
            color=current, title=f"选择颜色 — {key}",
            parent=self._palette_window)
        if result and result[1]:
            var.set(result[1])
            sample.configure(bg=result[1])
            setattr(edit_theme, key, result[1])

    def _reset_palette_defaults(self, edit_theme: ColorTheme):
        """恢复默认（使用当前预设）"""
        name = self.theme.name
        if name in THEME_PRESETS:
            preset = THEME_PRESETS[name]
        else:
            preset = OBSIDIAN_DARK
        for k, v in self._palette_vars.items():
            new_val = getattr(preset, k)
            v.set(new_val)
            setattr(edit_theme, k, new_val)
            if k in self._palette_samples:
                try:
                    self._palette_samples[k].configure(bg=new_val)
                except Exception:
                    pass

    def _apply_palette(self, edit_theme: ColorTheme, window: tk.Toplevel):
        """应用编辑后的调色盘"""
        edit_theme.name = "自定义"
        self._apply_theme(edit_theme)
        window.destroy()

    def _on_theme_select(self, event):
        """顶部主题下拉选择"""
        name = self.theme_name_var.get()
        if name in THEME_PRESETS:
            theme = THEME_PRESETS[name]
            self._apply_theme(theme)

    # ═══════════════════════════════════════════════════════
    # 压缩包导出
    # ═══════════════════════════════════════════════════════

    def _export_zip(self):
        """打包源码为 zip 压缩包"""
        path = filedialog.asksaveasfilename(
            title="导出压缩包",
            defaultextension=".zip",
            filetypes=[("ZIP 压缩包", "*.zip"), ("所有文件", "*.*")],
            initialfile=f"VideoDownloader_v{APP_VERSION.replace('.', '')}.zip",
            initialdir=os.path.expanduser("~\\Desktop"),
        )
        if not path:
            return

        try:
            # 确保 requirements.txt 存在
            req_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "requirements.txt")
            if not os.path.isfile(req_path):
                with open(req_path, "w", encoding="utf-8") as f:
                    f.write("yt-dlp>=2024.0.0\n")
                    f.write("pyinstaller>=6.0.0\n")

            base_dir = os.path.dirname(os.path.abspath(__file__))
            files_to_zip = [
                "video_downloader.py",
                "CLAUDE.md",
                ".gitignore",
                "requirements.txt",
            ]

            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
                for fname in files_to_zip:
                    fpath = os.path.join(base_dir, fname)
                    if os.path.isfile(fpath):
                        zf.write(fpath, fname)

                # 添加 README
                readme_content = self._generate_readme()
                zf.writestr("README.md", readme_content)

            self._update_status(f"✅  压缩包已导出: {os.path.basename(path)}", "success")
        except Exception as e:
            self._update_status(f"❌  导出失败: {e}", "error")

    def _generate_readme(self) -> str:
        """生成 README.md 内容"""
        return f"""# Video Downloader v{APP_VERSION}

基于 yt-dlp + Tkinter 的 Windows 桌面视频下载工具。

## ✨ 功能

- 🎬 支持 YouTube / Bilibili / Twitter / TikTok 等 **1800+** 网站
- 📋 **批量下载**：粘贴多个链接，逐个排队下载
- 🎨 **自定义主题**：iOS 浅色 / iOS 深色 / Obsidian 深色
- ⚙️ **调色盘编辑**：自由定制全部颜色
- 📊 实时进度条 + 速度/ETA 显示
- 📁 自定义保存路径 + 分辨率选择

## ▶️ 运行

```bash
pip install yt-dlp
python video_downloader.py
```

## 📦 打包为 exe

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name "VideoDownloader" --clean --collect-all yt_dlp video_downloader.py
```

## 🖥️ 系统要求

- Windows 10/11
- Python 3.12+
- (可选) FFmpeg — 用于视频音频合并

---

🤖 Generated with [Claude Code](https://claude.com/claude-code)
"""

    # ═══════════════════════════════════════════════════════
    # URL 输入处理
    # ═══════════════════════════════════════════════════════

    def _get_urls_from_text(self) -> list[str]:
        text = self.url_text.get("1.0", "end-1c").strip()
        if not text:
            return []
        return [line.strip() for line in text.splitlines() if line.strip()]

    def _on_url_text_modified(self, event=None):
        """文本变更 — 防抖 800ms 后自动解析第一个 URL（单视频预览）"""
        # 清除 Modified 标志
        self.url_text.edit_modified(False)
        # 取消防抖
        if self._url_text_after_id:
            self.root.after_cancel(self._url_text_after_id)
        # 防抖延迟
        self._url_text_after_id = self.root.after(800, self._parse_first_url)

    def _parse_first_url(self):
        """自动解析 Text 中第一个 URL，填充视频信息卡片"""
        if self.downloading:
            return
        urls = self._get_urls_from_text()
        if not urls:
            return
        # 取第一个有效 URL
        url = urls[0]
        # 如果已经在队列里且有 info，直接显示
        for task in self.download_queue:
            if task.url == url and task.info:
                self._show_task_info(task)
                self._update_status(f"✅  {task.title}", "success")
                return
        # 否则后台解析
        self._update_status("🔍  正在解析...", "info")
        threading.Thread(target=self._extract_single_url, args=(url,), daemon=True).start()
        self.root.after(200, self._check_single_parse)

    def _extract_single_url(self, url):
        """后台解析单个 URL"""
        try:
            import yt_dlp
            ydl_opts = {"quiet": True, "no_warnings": True, "extract_flat": False}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
            if info and info.get("_type") == "playlist" and "entries" in info:
                entries = info.get("entries", [])
                if entries:
                    info = entries[0]
            self._single_parse_result = {"status": "ok", "data": info}
        except Exception as e:
            self._single_parse_result = {"status": "error", "data": str(e)}

    def _check_single_parse(self):
        """轮询单视频解析结果"""
        result = self._single_parse_result
        if result is None:
            # 还在解析中
            if not self.downloading:
                self.root.after(200, self._check_single_parse)
            return
        # 消费结果
        self._single_parse_result = None
        if result["status"] == "ok":
            self._on_single_parsed(result["data"])
        else:
            self._update_status(f"❌  解析失败: {result['data'][:60]}", "error")

    def _on_single_parsed(self, info: dict):
        """单视频解析成功 — 填充 UI"""
        self.video_info = info
        self.video_formats = self._filter_formats(info)

        title = info.get("title", "未知标题")
        duration = info.get("duration", 0)
        uploader = info.get("uploader", "") or info.get("channel", "") or ""

        self.video_title_label.configure(text=title)
        self.video_meta_label.configure(
            text=f"时长: {self._format_duration(duration)}  ·  "
                 f"平台: {info.get('extractor_key', '?')}")
        self.video_uploader_label.configure(
            text=f"上传者: {uploader}" if uploader else "")

        # 填充格式下拉
        if self.video_formats:
            display = []
            for f in self.video_formats:
                h = f["height"]
                e = f.get("ext", "?")
                size = f.get("filesize") or f.get("filesize_approx") or 0
                display.append(f"{h}p ({e})  ~ {self._format_filesize(size)}")
            self.format_combo.configure(values=display)
            self.format_combo.current(0)
            self._set_ui_state("ready_to_download")
            self._update_status(f"✅  {title} — {len(display)} 种分辨率", "success")
        else:
            self._update_status("❌  未找到可下载的格式", "error")

        # 显示信息卡片
        if not self.info_frame.winfo_ismapped():
            self.info_frame.pack(before=self.format_frame, fill=tk.X,
                                 pady=(0, PAD_STD))
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_paste(self):
        try:
            clip = self.root.clipboard_get()
            if clip and clip.strip():
                current = self.url_text.get("1.0", "end-1c").rstrip()
                if current:
                    self.url_text.insert("end", "\n" + clip.strip())
                else:
                    self.url_text.insert("1.0", clip.strip())
                # 立即触发解析
                self._url_text_after_id = self.root.after(100, self._parse_first_url)
        except tk.TclError:
            pass

    def _clear_url_text(self):
        self.url_text.delete("1.0", "end")

    # ═══════════════════════════════════════════════════════
    # 队列管理
    # ═══════════════════════════════════════════════════════

    def _add_urls_to_queue(self):
        urls = self._get_urls_from_text()
        if not urls:
            self._update_status("⚠  请先输入视频链接", "warning")
            return

        existing = {t.url for t in self.download_queue}
        new_urls = [u for u in urls if u not in existing]
        if not new_urls:
            self._update_status("⚠  所有链接已在队列中", "warning")
            return

        for url in new_urls:
            self.download_queue.append(DownloadTask(url=url, status="pending"))

        self._refresh_queue_ui()
        self._update_status(
            f"📋  已添加 {len(new_urls)} 个链接 (共 {len(self.download_queue)} 个)",
            "info")
        self._parse_next_in_queue()

    def _parse_next_in_queue(self):
        for i, task in enumerate(self.download_queue):
            if task.status == "pending":
                task.status = "parsing"
                self._refresh_queue_ui()
                self._parse_task(task, i)
                return

    def _parse_task(self, task: DownloadTask, idx: int):
        def _extract():
            try:
                import yt_dlp
                ydl_opts = {"quiet": True, "no_warnings": True, "extract_flat": False}
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(task.url, download=False)
                if info and info.get("_type") == "playlist" and "entries" in info:
                    entries = info.get("entries", [])
                    if entries:
                        info = entries[0]
                task.info = info
                task.title = info.get("title", "未知标题")
                task.duration = self._format_duration(info.get("duration", 0))
                task.uploader = info.get("uploader", "") or info.get("channel", "") or ""
                task.formats = self._filter_formats(info)
                if task.formats:
                    f0 = task.formats[0]
                    task.format_id = f0.get("format_id", "")
                    task.format_label = f"{f0['height']}p ({f0.get('ext','?')})"
                task.status = "queued"
            except Exception as e:
                task.status = "failed"
                err = str(e)
                if "HTTP Error 404" in err:
                    task.error_msg = "视频未找到 (404)"
                elif "Unsupported URL" in err:
                    task.error_msg = "不支持的链接格式"
                elif "connection" in err.lower():
                    task.error_msg = "网络连接失败"
                else:
                    task.error_msg = err[:60]
            self.parse_queue.put(("task_parsed", idx))

        threading.Thread(target=_extract, daemon=True).start()
        self.root.after(100, self._check_parse_result)

    def _check_parse_result(self):
        try:
            while True:
                status, data = self.parse_queue.get_nowait()
                if status == "task_parsed":
                    idx = data
                    task = self.download_queue[idx]
                    if task.status == "failed":
                        self._update_status(f"❌  解析失败: {task.error_msg}", "error")
                    else:
                        self._update_status(f"✅  解析完成: {task.title}", "success")
                    self._refresh_queue_ui()
                    self._parse_next_in_queue()
        except queue.Empty:
            if any(t.status == "parsing" for t in self.download_queue):
                self.root.after(200, self._check_parse_result)

    def _refresh_queue_ui(self):
        if not hasattr(self, 'queue_tree'):
            return
        for item in self.queue_tree.get_children():
            self.queue_tree.delete(item)

        icons = {
            "pending": "⏳", "parsing": "🔍", "queued": "📋",
            "downloading": "⬇", "completed": "✅",
            "failed": "❌", "cancelled": "⏹",
        }

        for i, task in enumerate(self.download_queue):
            icon = icons.get(task.status, "?")
            title = task.title or task.url[:60] + ("..." if len(task.url) > 60 else "")
            if task.status == "downloading":
                progress = f"{task.progress:.0f}%"
            elif task.status == "completed":
                progress = "100%"
            elif task.status == "failed":
                progress = "失败"
            elif task.status == "parsing":
                progress = "解析中..."
            elif task.status == "pending":
                progress = "待解析"
            else:
                progress = "—"
            self.queue_tree.insert("", "end", iid=str(i),
                                    values=(icon, title, progress))

        count = len(self.download_queue)
        if hasattr(self, 'queue_title_label'):
            self.queue_title_label.configure(text=f"下载队列 ({count})")
        if count > 0 and not self.queue_frame.winfo_ismapped():
            self.queue_frame.pack(fill=tk.X, pady=(0, PAD_STD))
        elif count == 0 and self.queue_frame.winfo_ismapped():
            self.queue_frame.pack_forget()

        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _remove_from_queue(self, idx: int):
        if 0 <= idx < len(self.download_queue):
            task = self.download_queue[idx]
            if task.status == "downloading":
                self._update_status("⚠  无法删除正在下载的任务，请先取消", "warning")
                return
            del self.download_queue[idx]
            self._refresh_queue_ui()

    def _clear_completed(self):
        self.download_queue = [
            t for t in self.download_queue
            if t.status not in ("completed", "failed", "cancelled")]
        self._refresh_queue_ui()

    def _on_queue_select(self, event):
        sel = self.queue_tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        task = self.download_queue[idx]
        if task.info:
            self._show_task_info(task)

    def _on_queue_double_click(self, event):
        self._on_queue_select(event)

    def _on_queue_right_click(self, event):
        t = self.theme
        item = self.queue_tree.identify_row(event.y)
        if not item:
            return
        idx = int(item)
        task = self.download_queue[idx]

        menu = tk.Menu(self.root, tearoff=0, bg=t.bg_secondary, fg=t.text_primary,
                       activebackground=t.accent, activeforeground="#ffffff",
                       font=self.font_small)
        menu.add_command(label="删除", command=lambda: self._remove_from_queue(idx))
        if task.status == "failed":
            menu.add_command(label="重试解析",
                             command=lambda: self._retry_parse(idx))
        menu.add_separator()
        menu.add_command(label="清空已完成", command=self._clear_completed)
        menu.post(event.x_root, event.y_root)

    def _retry_parse(self, idx: int):
        task = self.download_queue[idx]
        task.status = "pending"
        task.error_msg = ""
        self._refresh_queue_ui()
        self._parse_next_in_queue()

    def _show_task_info(self, task: DownloadTask):
        if not task.info:
            return
        self.video_info = task.info
        self.video_formats = task.formats
        self.video_title_label.configure(text=task.title)
        self.video_meta_label.configure(
            text=f"时长: {task.duration}  ·  平台: {task.info.get('extractor_key', '?')}")
        self.video_uploader_label.configure(
            text=f"上传者: {task.uploader}" if task.uploader else "")
        if task.formats:
            display = []
            for f in task.formats:
                h = f["height"]
                e = f.get("ext", "?")
                size = f.get("filesize") or f.get("filesize_approx") or 0
                display.append(f"{h}p ({e})  ~ {self._format_filesize(size)}")
            self.format_combo.configure(values=display)
            self.format_combo.current(0)
            task.format_id = task.formats[0].get("format_id", "")
        if not self.info_frame.winfo_ismapped():
            self.info_frame.pack(before=self.format_frame, fill=tk.X,
                                 pady=(0, PAD_STD))
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    # ═══════════════════════════════════════════════════════
    # 格式处理
    # ═══════════════════════════════════════════════════════

    def _filter_formats(self, info: dict) -> list:
        formats = info.get("formats", [])
        usable = []
        seen = set()
        for f in formats:
            height = f.get("height")
            if not height or height < 144:
                continue
            if f.get("vcodec") == "none":
                continue
            ext = f.get("ext", "?")
            key = (height, ext)
            if key in seen:
                existing = next(x for x in usable if x.get("key") == key)
                es = existing.get("filesize") or existing.get("filesize_approx") or 0
                ns = f.get("filesize") or f.get("filesize_approx") or 0
                if ns > es:
                    usable.remove(existing)
                    f["key"] = key
                    usable.append(f)
                continue
            seen.add(key)
            f_copy = dict(f)
            f_copy["key"] = key
            usable.append(f_copy)
        usable.sort(key=lambda x: x.get("height", 0), reverse=True)
        return usable

    # ═══════════════════════════════════════════════════════
    # 保存路径
    # ═══════════════════════════════════════════════════════

    def _browse_save_path(self):
        current = self.save_path_var.get()
        if not os.path.isdir(current):
            current = os.path.expanduser("~\\Downloads")
        path = filedialog.askdirectory(title="选择保存位置", initialdir=current)
        if path:
            self.save_path_var.set(path)

    # ═══════════════════════════════════════════════════════
    # 下载引擎
    # ═══════════════════════════════════════════════════════

    def _start_single_download(self):
        urls = self._get_urls_from_text()
        url = urls[0] if urls else ""
        save_path = self.save_path_var.get().strip()
        fmt_idx = self.format_combo.current()

        if not url:
            self._update_status("⚠  请输入视频链接", "warning")
            return
        if not self.video_formats or fmt_idx < 0:
            self._update_status("⚠  请先解析视频链接", "warning")
            return
        if not save_path or not os.path.isdir(save_path):
            self._update_status("⚠  请选择保存位置", "warning")
            return

        task = DownloadTask(url=url, status="downloading")
        if self.video_info:
            task.info = self.video_info
            task.title = self.video_info.get("title", "")
            task.formats = self.video_formats
        task.format_id = self.video_formats[fmt_idx].get("format_id", "")
        self._current_task = task
        self._batch_mode = False
        self._start_task_download(task)

    def _start_all_downloads(self):
        ready = [t for t in self.download_queue if t.status == "queued"]
        if not ready:
            self._update_status("⚠  队列中没有待下载的任务", "warning")
            return
        save_path = self.save_path_var.get().strip()
        if not save_path or not os.path.isdir(save_path):
            self._update_status("⚠  请选择保存位置", "warning")
            return

        self._batch_mode = True
        self._update_status(f"⬇  开始批量下载 ({len(ready)} 个)...", "progress")
        self._process_next()

    def _process_next(self):
        for task in self.download_queue:
            if task.status == "queued":
                self._current_task = task
                self._start_task_download(task)
                return
        self._batch_mode = False
        self._current_task = None
        completed = sum(1 for t in self.download_queue if t.status == "completed")
        failed = sum(1 for t in self.download_queue if t.status == "failed")
        self._update_status(
            f"✅  批量下载完成 — 成功 {completed} / 失败 {failed}", "success")
        self._set_ui_state("ready")
        self.download_btn.configure(state="normal")
        self._hide_progress()

    def _start_task_download(self, task: DownloadTask):
        task.status = "downloading"
        task.progress = 0.0
        self.downloading = True
        self.cancel_requested = False

        self._refresh_queue_ui()
        self._set_ui_state("downloading")
        self._show_progress()

        self.progress_bar["value"] = 0
        self.pct_label.configure(text="0%")
        self.speed_label.configure(text="速度: --")
        self.eta_label.configure(text="剩余: --")

        label = task.title or task.url[:50]
        self._update_status(f"⬇  正在下载: {label}", "progress")

        save_path = self.save_path_var.get().strip()
        format_id = task.format_id or "best"

        threading.Thread(
            target=self._download_thread,
            args=(task.url, format_id, save_path), daemon=True).start()
        self._poll_progress()

    def _cancel_all_downloads(self):
        if self.downloading:
            self.cancel_requested = True
            for task in self.download_queue:
                if task.status == "queued":
                    task.status = "cancelled"
            self._update_status("⏹  正在取消...", "warning")
        else:
            self._update_status("⏹  没有正在进行的下载", "info")

    def _download_thread(self, url, format_id, save_path):
        import yt_dlp
        try:
            ydl_opts = {
                "format": format_id,
                "outtmpl": os.path.join(save_path, "%(title)s.%(ext)s"),
                "progress_hooks": [self._progress_hook],
                "quiet": True, "no_warnings": True,
                "merge_output_format": "mp4",
                "concurrent_fragment_downloads": 4,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            self.progress_queue.put({"status": "finished"})
        except DownloadCancelled:
            self.progress_queue.put({"status": "cancelled"})
        except Exception as e:
            self.progress_queue.put({"status": "error", "message": str(e)})

    def _progress_hook(self, d):
        if self.cancel_requested:
            raise DownloadCancelled("用户取消")
        status = d.get("status", "")
        if status in ("downloading", "finished", "error"):
            self.progress_queue.put({
                "status": status,
                "percent_str": d.get("_percent_str", "0%").strip(),
                "speed_str": d.get("_speed_str", "N/A").strip(),
                "eta_str": d.get("_eta_str", "N/A").strip(),
                "filename": d.get("filename", ""),
            })

    def _poll_progress(self):
        if not self.downloading:
            return
        try:
            while True:
                data = self.progress_queue.get_nowait()
                status = data.get("status", "")
                if status == "finished":
                    self._on_task_done(data); return
                elif status == "error":
                    self._on_task_error(data); return
                elif status == "cancelled":
                    self._on_task_cancelled(); return
                else:
                    self._update_progress_ui(data)
        except queue.Empty:
            pass
        self._poll_after_id = self.root.after(100, self._poll_progress)

    def _update_progress_ui(self, data):
        pct_str = data.get("percent_str", "0%")
        try:
            pct = float(pct_str.replace("%", "").strip())
        except (ValueError, AttributeError):
            pct = 0

        self.progress_bar["value"] = pct
        self.pct_label.configure(text=f"{pct:.1f}%")

        speed = data.get("speed_str", "N/A").strip()
        if speed and speed != "N/A":
            self.speed_label.configure(text=f"速度: {speed}")
        eta = data.get("eta_str", "N/A").strip()
        if eta and eta != "N/A":
            self.eta_label.configure(text=f"剩余: {eta}")

        if self._current_task:
            self._current_task.progress = pct
            self._current_task.speed = speed
            self._current_task.eta = eta
            self._refresh_queue_ui()

    def _on_task_done(self, data):
        self.downloading = False
        task = self._current_task
        if task:
            task.status = "completed"
            task.progress = 100.0
            task.filepath = data.get("filename", "")
            basename = os.path.basename(task.filepath) if task.filepath else "未知"
            self._update_status(f"✅  完成: {basename}", "success")
            self._add_to_history(task.title or task.url, task.filepath)
        self._refresh_queue_ui()
        if self._batch_mode:
            self.root.after(300, self._process_next)
        else:
            self._current_task = None
            self._set_ui_state("ready")
            self.download_btn.configure(state="normal")
            self.progress_bar["value"] = 100
            self.pct_label.configure(text="100%")

    def _on_task_error(self, data):
        self.downloading = False
        task = self._current_task
        if task:
            task.status = "failed"
            msg = data.get("message", "未知错误")
            if "Permission denied" in msg:
                msg = "写入权限不足"
            elif "No space" in msg:
                msg = "磁盘空间不足"
            elif "connection" in msg.lower():
                msg = "网络连接中断"
            task.error_msg = msg
            self._update_status(f"❌  失败: {msg}", "error")
        self._refresh_queue_ui()
        if self._batch_mode:
            self.root.after(300, self._process_next)
        else:
            self._current_task = None
            self._set_ui_state("ready")
            self.download_btn.configure(state="normal")

    def _on_task_cancelled(self):
        self.downloading = False
        task = self._current_task
        if task:
            task.status = "cancelled"
        self._refresh_queue_ui()
        if self._batch_mode:
            self.root.after(300, self._process_next)
        else:
            self._current_task = None
            self._set_ui_state("ready")
            self.download_btn.configure(state="normal")
        self._update_status("⏹  下载已取消", "info")

    def _show_progress(self):
        self.progress_frame.pack_forget()
        self.progress_frame.pack(before=self.dl_btn_frame, fill=tk.X,
                                  pady=(0, PAD_STD))
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _hide_progress(self):
        self.progress_frame.pack_forget()
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    # ═══════════════════════════════════════════════════════
    # UI 状态管理
    # ═══════════════════════════════════════════════════════

    def _set_ui_state(self, state):
        states = {
            "ready": {
                "url": "normal", "paste": "normal", "add_queue": "normal",
                "clear_url": "normal", "platform": "readonly",
                "format": "disabled", "save": "normal", "browse": "normal",
                "download": "disabled", "batch_dl": "normal",
            },
            "ready_to_download": {
                "url": "normal", "paste": "normal", "add_queue": "normal",
                "clear_url": "normal", "platform": "readonly",
                "format": "readonly", "save": "normal", "browse": "normal",
                "download": "normal", "batch_dl": "normal",
            },
            "downloading": {
                "url": "disabled", "paste": "disabled", "add_queue": "disabled",
                "clear_url": "disabled", "platform": "disabled",
                "format": "disabled", "save": "disabled", "browse": "disabled",
                "download": "disabled", "batch_dl": "disabled",
            },
        }

        s = states.get(state, states["ready"])
        try:
            self.url_text.configure(state=s["url"])
            self.paste_btn.configure(state=s["paste"])
            self.add_queue_btn.configure(state=s["add_queue"])
            self.clear_url_btn.configure(state=s["clear_url"])
            self.platform_combo.configure(state=s["platform"])
            self.format_combo.configure(state=s["format"])
            self.save_entry.configure(state=s["save"])
            self.browse_btn.configure(state=s["browse"])
            self.download_btn.configure(state=s["download"])
            self.batch_download_btn.configure(state=s["batch_dl"])
            self.cancel_queue_btn.configure(state=s["batch_dl"])
        except tk.TclError:
            pass

    def _update_status(self, text, status_type="info"):
        t = self.theme
        colors = {
            "info": t.text_secondary, "success": t.success,
            "error": t.error, "warning": t.warning, "progress": t.accent,
        }
        color = colors.get(status_type, t.text_secondary)
        try:
            self.status_label.configure(text=text, foreground=color)
        except tk.TclError:
            pass

    # ═══════════════════════════════════════════════════════
    # 历史
    # ═══════════════════════════════════════════════════════

    def _add_to_history(self, title, filepath):
        entry = {"title": title, "path": filepath,
                  "time": datetime.now().strftime("%Y-%m-%d %H:%M")}
        self.download_history.insert(0, entry)
        self.history_listbox.insert(0, f"{entry['time']}  ·  {title}")
        if len(self.download_history) > 50:
            self.download_history.pop()
            self.history_listbox.delete(tk.END)
        if not self.history_frame.winfo_ismapped():
            self.history_frame.pack(fill=tk.X, pady=(0, 0))
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _clear_history(self):
        self.download_history.clear()
        self.history_listbox.delete(0, tk.END)
        self.history_frame.pack_forget()

    # ═══════════════════════════════════════════════════════
    # 工具方法
    # ═══════════════════════════════════════════════════════

    @staticmethod
    def _format_filesize(bytes_val):
        if not bytes_val or bytes_val <= 0:
            return "未知大小"
        if bytes_val < 1024:
            return f"{bytes_val} B"
        elif bytes_val < 1024 * 1024:
            return f"{bytes_val / 1024:.0f} KB"
        elif bytes_val < 1024 * 1024 * 1024:
            return f"{bytes_val / (1024*1024):.1f} MB"
        else:
            return f"{bytes_val / (1024*1024*1024):.2f} GB"

    @staticmethod
    def _format_duration(seconds):
        if not seconds or seconds <= 0:
            return "?"
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        if h:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"

    def _install_ffmpeg(self):
        """一键安装 FFmpeg — 优先使用 winget，失败则打开下载页"""
        import webbrowser

        # 先尝试 winget（Windows 10/11 自带）
        try:
            self._update_status("📥  正在通过 winget 安装 FFmpeg...", "progress")
            self.root.update()
            result = subprocess.run(
                ["winget", "install", "--id", "Gyan.FFmpeg", "--accept-source-agreements", "--accept-package-agreements"],
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode == 0:
                # 刷新检测
                self.has_ffmpeg = self._check_ffmpeg()
                if self.has_ffmpeg:
                    self._update_status("✅  FFmpeg 安装成功！", "success")
                    # 隐藏警告
                    if hasattr(self, 'ffmpeg_warn_frame'):
                        self.ffmpeg_warn_frame.pack_forget()
                    return
        except Exception:
            pass

        # winget 失败 → 打开浏览器下载
        self._update_status("📥  请在浏览器中下载 FFmpeg...", "info")
        webbrowser.open("https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip")
        messagebox.showinfo(
            "安装 FFmpeg",
            "1. 下载后解压 zip\n"
            "2. 将 bin 文件夹路径添加到系统 PATH\n"
            "3. 重启本应用\n\n"
            "或复制 ffmpeg.exe 到:\n"
            f"{os.path.expandvars(r'%LOCALAPPDATA%\\ffmpeg\\bin\\')}"
        )

    @staticmethod
    def _check_ffmpeg():
        if shutil.which("ffmpeg"):
            return True
        for p in [
            os.path.expandvars(r"%LOCALAPPDATA%\ffmpeg\bin\ffmpeg.exe"),
            os.path.expandvars(r"%ProgramFiles%\ffmpeg\bin\ffmpeg.exe"),
            r"C:\ffmpeg\bin\ffmpeg.exe",
            r"C:\tools\ffmpeg\bin\ffmpeg.exe",
        ]:
            if os.path.isfile(p):
                # 临时加到 os.environ PATH 以便 subprocess 能用
                bin_dir = os.path.dirname(p)
                if bin_dir not in os.environ.get("PATH", ""):
                    os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
                return True
        try:
            subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=5)
            return True
        except Exception:
            return False

    # ═══════════════════════════════════════════════════════
    # 生命周期
    # ═══════════════════════════════════════════════════════

    def _on_close(self):
        if self.downloading:
            self.cancel_requested = True
        if self._thumb_path and os.path.isfile(self._thumb_path):
            try:
                os.unlink(self._thumb_path)
            except Exception:
                pass
        self._save_theme()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


# ── 入口 ────────────────────────────────────────────────

def main():
    app = VideoDownloaderApp()
    app.run()


if __name__ == "__main__":
    main()
