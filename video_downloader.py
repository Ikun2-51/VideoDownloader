#!/usr/bin/env python3
"""
Video Downloader — 桌面视频下载器
基于 yt-dlp + Tkinter 的 Windows 桌面视频下载工具。
支持 YouTube、Bilibili、Twitter/X、TikTok 等 1800+ 网站。
审美参考 Obsidian：深色主题、紫色 accent、4px 网格系统。

功能：
- 单视频下载：输入链接 → 解析 → 选分辨率 → 下载
- 批量下载：粘贴多个链接（每行一个）→ 加入队列 → 逐个排队下载
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import os
import re
import sys
import json
import queue
import threading
import tempfile
import shutil
import subprocess
from datetime import datetime
from dataclasses import dataclass, field

# ── Obsidian 色板 ──────────────────────────────────────

BG_PRIMARY    = "#0d0d0d"
BG_SECONDARY  = "#1a1a1a"
BG_TERTIARY   = "#2a2a2a"
TEXT_PRIMARY  = "#cfcfcf"
TEXT_SECONDARY= "#808080"
TEXT_MUTED    = "#595959"
ACCENT        = "#6930C7"
ACCENT_HOVER  = "#7c3aed"
BORDER        = "#222222"
SUCCESS_COLOR = "#4ade80"
ERROR_COLOR   = "#f87171"
WARNING_COLOR = "#fbbf24"

FONT_UI   = "Microsoft YaHei"
FONT_MONO = "Consolas"

# ── 间距 (4px 网格) ────────────────────────────────────

PAD_TIGHT   = 4
PAD         = 8
PAD_COMFORT = 12
PAD_STD     = 16
PAD_WIDE    = 24
PAD_XL      = 32

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
    "":           "自动检测",
    "youtube":    "YouTube",
    "bilibili":   "Bilibili",
    "twitter":    "Twitter / X",
    "tiktok":     "TikTok",
    "instagram":  "Instagram",
    "vimeo":      "Vimeo",
}

# ── 自定义异常 ──────────────────────────────────────────

class DownloadCancelled(Exception):
    """用户取消下载"""
    pass


# ── 下载任务数据类 ──────────────────────────────────────

@dataclass
class DownloadTask:
    """单个下载任务的状态"""
    url: str
    title: str = ""
    duration: str = ""
    uploader: str = ""
    status: str = "pending"  # pending | parsing | queued | downloading | completed | failed | cancelled
    format_id: str = ""
    format_label: str = ""
    info: dict | None = None
    progress: float = 0.0
    speed: str = "--"
    eta: str = "--"
    error_msg: str = ""
    filepath: str = ""
    formats: list = field(default_factory=list)


# ── 主应用类 ────────────────────────────────────────────

class VideoDownloaderApp:
    """视频下载器主应用"""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Video Downloader")
        self.root.geometry("750x880")
        self.root.minsize(550, 720)
        self.root.configure(bg=BG_PRIMARY)

        self._set_app_id()

        # ── 状态变量 ──────────────────────────────
        self.platform_var   = tk.StringVar(value="")
        self.save_path_var  = tk.StringVar(value=os.path.expanduser("~\\Downloads"))
        self.format_var     = tk.StringVar()

        # 单视频模式（保留兼容）
        self.video_info     = None
        self.video_formats  = []
        self.thumbnail_img  = None
        self._thumb_path    = None

        # 批量下载队列
        self.download_queue: list[DownloadTask] = []
        self._current_task: DownloadTask | None = None
        self._batch_mode = False       # True = 队列批量模式

        # 下载状态
        self.downloading    = False
        self.cancel_requested = False
        self.download_thread = None
        self.progress_queue = queue.Queue()
        self.parse_queue    = queue.Queue()
        self._parse_after_id = None
        self._poll_after_id  = None
        self._parse_batch_idx = 0    # 当前批量解析的序号

        # 下载历史
        self.download_history = []

        # ffmpeg
        self.has_ffmpeg = self._check_ffmpeg()

        # ── 构建 UI ──────────────────────────────
        self._setup_styles()
        self._build_ui()
        self._bind_keys()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ═══════════════════════════════════════════════════════
    # 窗口设置
    # ═══════════════════════════════════════════════════════

    def _set_app_id(self):
        """设置 Windows 任务栏 AppUserModelID"""
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "com.tuberose.videodownloader"
            )
        except Exception:
            pass

    def _bind_keys(self):
        """绑定快捷键"""
        self.root.bind("<Control-v>", lambda e: self._on_paste())
        self.root.bind("<Control-V>", lambda e: self._on_paste())
        self.root.bind("<Escape>", lambda e: self._cancel_all_downloads())

    # ═══════════════════════════════════════════════════════
    # 样式
    # ═══════════════════════════════════════════════════════

    def _setup_styles(self):
        """配置 ttk 样式 — Obsidian 深色主题"""
        style = ttk.Style()
        style.theme_use("clam")

        style.configure(".",
            background=BG_PRIMARY, foreground=TEXT_PRIMARY,
            fieldbackground=BG_TERTIARY, bordercolor=BORDER,
            font=(FONT_UI, 10),
        )

        style.configure("TFrame", background=BG_PRIMARY)
        style.configure("Card.TFrame", background=BG_SECONDARY, relief="flat")

        style.configure("TLabel", background=BG_PRIMARY,
                        foreground=TEXT_PRIMARY, font=(FONT_UI, 10))
        style.configure("Title.TLabel", font=(FONT_UI, 22, "bold"),
                        foreground=ACCENT)
        style.configure("Heading.TLabel", font=(FONT_UI, 13, "bold"),
                        foreground=TEXT_PRIMARY)
        style.configure("Card.TLabel", background=BG_SECONDARY,
                        foreground=TEXT_PRIMARY, font=(FONT_UI, 10))
        style.configure("CardHeading.TLabel", background=BG_SECONDARY,
                        foreground=TEXT_PRIMARY, font=(FONT_UI, 12, "bold"))
        style.configure("Muted.TLabel", foreground=TEXT_MUTED, font=(FONT_UI, 9))
        style.configure("Success.TLabel", foreground=SUCCESS_COLOR)
        style.configure("Error.TLabel", foreground=ERROR_COLOR)
        style.configure("Warning.TLabel", foreground=WARNING_COLOR)

        style.configure("TButton", background=BG_TERTIARY,
                        foreground=TEXT_PRIMARY, borderwidth=1, relief="flat",
                        padding=(PAD_STD, PAD), font=(FONT_UI, 10))
        style.map("TButton",
            background=[("active", "#3a3a3a"), ("pressed", BG_TERTIARY)],
            foreground=[("active", "#ffffff")],
        )

        style.configure("Accent.TButton", background=ACCENT,
                        foreground="#ffffff", font=(FONT_UI, 12, "bold"),
                        borderwidth=0, padding=(PAD_WIDE, PAD_COMFORT))
        style.map("Accent.TButton",
            background=[("active", ACCENT_HOVER), ("pressed", ACCENT)],
            foreground=[("active", "#ffffff")],
        )

        style.configure("Danger.TButton", background=ERROR_COLOR,
                        foreground="#ffffff", font=(FONT_UI, 12, "bold"),
                        borderwidth=0, padding=(PAD_WIDE, PAD_COMFORT))
        style.map("Danger.TButton",
            background=[("active", "#ef4444"), ("pressed", ERROR_COLOR)],
            foreground=[("active", "#ffffff")],
        )

        style.configure("Small.TButton", font=(FONT_UI, 9),
                        padding=(PAD, PAD_TIGHT))

        style.configure("TEntry", fieldbackground=BG_TERTIARY,
                        foreground=TEXT_PRIMARY, borderwidth=1,
                        relief="solid", padding=6)
        style.map("TEntry",
            fieldbackground=[("focus", BG_TERTIARY)],
            bordercolor=[("focus", ACCENT)],
        )

        style.configure("TCombobox", fieldbackground=BG_TERTIARY,
                        foreground=TEXT_PRIMARY, arrowcolor=TEXT_PRIMARY,
                        background=BG_TERTIARY)
        style.map("TCombobox",
            fieldbackground=[("readonly", BG_TERTIARY), ("focus", BG_TERTIARY)],
            bordercolor=[("focus", ACCENT)],
        )
        self.root.option_add("*TCombobox*Listbox.background", BG_SECONDARY)
        self.root.option_add("*TCombobox*Listbox.foreground", TEXT_PRIMARY)
        self.root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        self.root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")

        style.configure("TProgressbar", background=ACCENT,
                        troughcolor=BG_SECONDARY, bordercolor=BORDER)
        style.configure("TSeparator", background=BORDER)

        # Treeview 暗色主题
        style.configure("Queue.Treeview",
            background=BG_SECONDARY, foreground=TEXT_PRIMARY,
            fieldbackground=BG_SECONDARY, borderwidth=0,
            font=(FONT_UI, 10),
        )
        style.configure("Queue.Treeview.Heading",
            background=BG_TERTIARY, foreground=TEXT_MUTED,
            font=(FONT_UI, 9, "bold"), borderwidth=0,
        )
        style.map("Queue.Treeview",
            background=[("selected", ACCENT)],
            foreground=[("selected", "#ffffff")],
        )

    # ═══════════════════════════════════════════════════════
    # UI 构建
    # ═══════════════════════════════════════════════════════

    def _build_ui(self):
        """构建全部界面"""
        self.main_frame = ttk.Frame(self.root, padding=(PAD_XL, PAD_WIDE))
        self.main_frame.pack(fill=tk.BOTH, expand=True)

        self._canvas = tk.Canvas(self.main_frame, bg=BG_PRIMARY,
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

        # ── 各区域 ────────────────────────────────
        self._build_title(self._scroll_frame)
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

    def _build_title(self, parent):
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.X, pady=(0, PAD_WIDE))
        ttk.Label(frame, text="Video Downloader",
                  style="Title.TLabel").pack(anchor="w")
        ttk.Label(frame, text="下载 YouTube · Bilibili · Twitter · TikTok 等 1800+ 网站的视频",
                  style="Muted.TLabel").pack(anchor="w", pady=(PAD_TIGHT, 0))
        if not self.has_ffmpeg:
            ttk.Label(frame, text="⚠ FFmpeg 未安装 — 部分格式合并不可用",
                      style="Warning.TLabel").pack(anchor="w", pady=(PAD, 0))
        ttk.Separator(parent, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=(PAD_STD, PAD_STD))

    def _build_url_section(self, parent):
        """URL 输入区域 — 多行文本 + 操作按钮"""
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.X, pady=(0, PAD_STD))

        # 标题行
        ttk.Label(frame, text="视频链接（每行一个）",
                  style="Heading.TLabel").pack(anchor="w")

        # 多行文本输入
        text_frame = tk.Frame(frame, bg=BG_TERTIARY, highlightbackground=BORDER,
                               highlightthickness=1)
        text_frame.pack(fill=tk.X, pady=(PAD, 0))

        self.url_text = tk.Text(
            text_frame, height=3, wrap=tk.NONE,
            bg=BG_TERTIARY, fg=TEXT_PRIMARY,
            insertbackground=TEXT_PRIMARY,
            font=(FONT_UI, 10),
            borderwidth=0, highlightthickness=0,
            padx=6, pady=4,
            relief="flat",
        )
        self.url_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # 文本滚动条
        text_scroll = ttk.Scrollbar(text_frame, orient=tk.VERTICAL,
                                     command=self.url_text.yview)
        self.url_text.configure(yscrollcommand=text_scroll.set)

        # 按钮行
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

        # 平台选择
        ttk.Label(btn_row, text="平台:").pack(side=tk.LEFT, padx=(PAD_STD, PAD_TIGHT))
        self.platform_combo = ttk.Combobox(
            btn_row, textvariable=self.platform_var,
            values=list(PLATFORM_NAMES.values()),
            state="readonly", width=14, font=(FONT_UI, 10),
        )
        self.platform_combo.set(PLATFORM_NAMES[""])
        self.platform_combo.pack(side=tk.LEFT)

    def _build_queue_section(self, parent):
        """下载队列列表 — Treeview"""
        self.queue_frame = ttk.Frame(parent)
        # 默认隐藏，有任务时显示

        # 标题栏
        q_header = ttk.Frame(self.queue_frame)
        q_header.pack(fill=tk.X)

        self.queue_title_label = ttk.Label(q_header, text="下载队列 (0)",
                                            style="Heading.TLabel")
        self.queue_title_label.pack(side=tk.LEFT)

        self.clear_done_btn = ttk.Button(q_header, text="清空已完成",
                                          command=self._clear_completed,
                                          style="Small.TButton")
        self.clear_done_btn.pack(side=tk.RIGHT)

        # Treeview
        tree_frame = tk.Frame(self.queue_frame, bg=BG_SECONDARY)
        tree_frame.pack(fill=tk.X, pady=(PAD, 0))

        columns = ("status", "title", "progress")
        self.queue_tree = ttk.Treeview(
            tree_frame, columns=columns, show="headings",
            style="Queue.Treeview", height=5,
            selectmode="browse",
        )
        self.queue_tree.heading("status", text="状态", anchor="center")
        self.queue_tree.heading("title", text="视频")
        self.queue_tree.heading("progress", text="进度", anchor="center")

        self.queue_tree.column("status", width=50, anchor="center", stretch=False)
        self.queue_tree.column("title", width=420, stretch=True)
        self.queue_tree.column("progress", width=80, anchor="center", stretch=False)

        self.queue_tree.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # 树滚动条
        tree_scroll = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL,
                                     command=self.queue_tree.yview)
        self.queue_tree.configure(yscrollcommand=tree_scroll.set)

        # 绑定事件
        self.queue_tree.bind("<<TreeviewSelect>>", self._on_queue_select)
        self.queue_tree.bind("<Double-1>", self._on_queue_double_click)
        self.queue_tree.bind("<Button-3>", self._on_queue_right_click)

        # 操作按钮行
        q_btn_row = ttk.Frame(self.queue_frame)
        q_btn_row.pack(fill=tk.X, pady=(PAD, 0))

        self.batch_download_btn = ttk.Button(
            q_btn_row, text="▶  全部下载",
            style="Accent.TButton",
            command=self._start_all_downloads,
        )
        self.batch_download_btn.pack(side=tk.LEFT, fill=tk.X, expand=True,
                                      padx=(0, PAD))

        self.cancel_queue_btn = ttk.Button(
            q_btn_row, text="取消全部",
            style="Danger.TButton",
            command=self._cancel_all_downloads,
        )
        self.cancel_queue_btn.pack(side=tk.RIGHT, fill=tk.X, expand=True)

    def _build_video_info(self, parent):
        """视频信息卡片"""
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

        self.video_meta_label = ttk.Label(
            text_frame, text="", style="Muted.TLabel")
        self.video_meta_label.pack(anchor="w", pady=(PAD_TIGHT, 0))

        self.video_uploader_label = ttk.Label(
            text_frame, text="", style="Muted.TLabel")
        self.video_uploader_label.pack(anchor="w")

    def _build_format_section(self, parent):
        """格式选择和保存路径"""
        self.format_frame = ttk.Frame(parent)
        self.format_frame.pack(fill=tk.X, pady=(PAD_STD, PAD_STD))
        frame = self.format_frame

        ttk.Label(frame, text="分辨率", style="Heading.TLabel").pack(anchor="w")

        fmt_row = ttk.Frame(frame)
        fmt_row.pack(fill=tk.X, pady=(PAD, 0))
        self.format_combo = ttk.Combobox(
            fmt_row, textvariable=self.format_var,
            state="readonly", font=(FONT_UI, 10))
        self.format_combo.pack(fill=tk.X)

        path_label_frame = ttk.Frame(frame)
        path_label_frame.pack(fill=tk.X, pady=(PAD_STD, 0))
        ttk.Label(path_label_frame, text="保存到",
                  style="Heading.TLabel").pack(anchor="w")

        path_row = ttk.Frame(frame)
        path_row.pack(fill=tk.X, pady=(PAD, 0))
        self.save_entry = ttk.Entry(path_row, textvariable=self.save_path_var,
                                     font=(FONT_UI, 10))
        self.save_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, PAD))
        self.browse_btn = ttk.Button(path_row, text="浏览...",
                                      command=self._browse_save_path, width=8)
        self.browse_btn.pack(side=tk.RIGHT)

    def _build_download_button(self, parent):
        """下载按钮 — 单视频模式"""
        self.dl_btn_frame = ttk.Frame(parent)
        self.dl_btn_frame.pack(fill=tk.X, pady=(PAD, PAD_STD))

        self.download_btn = ttk.Button(
            self.dl_btn_frame, text="⬇  下载当前视频",
            style="Accent.TButton", command=self._start_single_download)
        self.download_btn.pack(fill=tk.X, ipady=4)

    def _build_progress_section(self, parent):
        """下载进度区域"""
        self.progress_frame = ttk.Frame(parent)

        self.progress_bar = ttk.Progressbar(
            self.progress_frame, mode="determinate", maximum=100)
        self.progress_bar.pack(fill=tk.X)

        self.pct_label = ttk.Label(
            self.progress_frame, text="0%",
            font=(FONT_UI, 24, "bold"), foreground=ACCENT,
            background=BG_PRIMARY, anchor="center")
        self.pct_label.pack(pady=(PAD_STD, PAD))

        info_row = ttk.Frame(self.progress_frame)
        info_row.pack(fill=tk.X)
        self.speed_label = ttk.Label(info_row, text="速度: --", style="Muted.TLabel")
        self.speed_label.pack(side=tk.LEFT)
        self.eta_label = ttk.Label(info_row, text="剩余: --", style="Muted.TLabel")
        self.eta_label.pack(side=tk.RIGHT)

    def _build_history_section(self, parent):
        """下载历史"""
        self.history_frame = ttk.Frame(parent)

        ttk.Separator(self.history_frame, orient=tk.HORIZONTAL).pack(
            fill=tk.X, pady=(PAD_STD, PAD_STD))

        hist_header = ttk.Frame(self.history_frame)
        hist_header.pack(fill=tk.X)
        ttk.Label(hist_header, text="下载历史",
                  style="Heading.TLabel").pack(side=tk.LEFT)
        self.clear_hist_btn = ttk.Button(hist_header, text="清除",
                                          command=self._clear_history, width=6)
        self.clear_hist_btn.pack(side=tk.RIGHT)

        self.history_listbox = tk.Listbox(
            self.history_frame, bg=BG_SECONDARY, fg=TEXT_PRIMARY,
            selectbackground=ACCENT, selectforeground="#ffffff",
            font=(FONT_UI, 9), height=6, borderwidth=0,
            highlightthickness=0, activestyle="none")
        self.history_listbox.pack(fill=tk.X, pady=(PAD, 0))

    def _build_status_bar(self, parent):
        """底部状态栏"""
        status_frame = ttk.Frame(parent)
        status_frame.pack(fill=tk.X, side=tk.BOTTOM, pady=(PAD_STD, 0))

        ttk.Separator(status_frame, orient=tk.HORIZONTAL).pack(fill=tk.X)

        self.status_label = ttk.Label(
            status_frame, text="✅  就绪", font=(FONT_UI, 10),
            foreground=TEXT_SECONDARY, background=BG_PRIMARY)
        self.status_label.pack(anchor="w", pady=(PAD, 0))

    # ═══════════════════════════════════════════════════════
    # URL 输入处理
    # ═══════════════════════════════════════════════════════

    def _get_urls_from_text(self):
        """从多行 Text 中提取非空 URL 列表"""
        text = self.url_text.get("1.0", "end-1c").strip()
        if not text:
            return []
        return [line.strip() for line in text.splitlines() if line.strip()]

    def _on_paste(self):
        """粘贴按钮：读取剪贴板并填入 Text"""
        try:
            clip = self.root.clipboard_get()
            if clip and clip.strip():
                # 如果 Text 中已有内容，追加到末尾
                current = self.url_text.get("1.0", "end-1c").rstrip()
                if current:
                    self.url_text.insert("end", "\n" + clip.strip())
                else:
                    self.url_text.insert("1.0", clip.strip())
        except tk.TclError:
            pass

    def _clear_url_text(self):
        """清空 URL 输入"""
        self.url_text.delete("1.0", "end")

    # ═══════════════════════════════════════════════════════
    # 队列管理
    # ═══════════════════════════════════════════════════════

    def _add_urls_to_queue(self):
        """解析 Text 中的 URL 并加入下载队列"""
        urls = self._get_urls_from_text()
        if not urls:
            self._update_status("⚠  请先输入视频链接", "warning")
            return

        # 过滤已存在的 URL
        existing_urls = {t.url for t in self.download_queue}
        new_urls = [u for u in urls if u not in existing_urls]

        if not new_urls:
            self._update_status("⚠  所有链接已在队列中", "warning")
            return

        for url in new_urls:
            task = DownloadTask(url=url, status="pending")
            self.download_queue.append(task)

        self._refresh_queue_ui()
        self._update_status(f"📋  已添加 {len(new_urls)} 个链接到队列 (共 {len(self.download_queue)} 个)", "info")

        # 自动开始解析队列中的 pending 任务
        self._parse_next_in_queue()

    def _parse_next_in_queue(self):
        """逐个解析队列中待解析的任务"""
        # 找到第一个 pending 任务
        for i, task in enumerate(self.download_queue):
            if task.status == "pending":
                task.status = "parsing"
                self._refresh_queue_ui()
                self._parse_task(task, i)
                return

    def _parse_task(self, task: DownloadTask, idx: int):
        """在后台线程解析单个 task 的 URL"""
        def _extract():
            try:
                ydl_opts = {"quiet": True, "no_warnings": True, "extract_flat": False}
                import yt_dlp
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
                task.error_msg = str(e)
                # 简化错误
                err = str(e)
                if "HTTP Error 404" in err:
                    task.error_msg = "视频未找到 (404)"
                elif "Unsupported URL" in err:
                    task.error_msg = "不支持的链接格式"
                elif "connection" in err.lower():
                    task.error_msg = "网络连接失败"

            self.parse_queue.put(("task_parsed", idx))

        threading.Thread(target=_extract, daemon=True).start()
        self.root.after(100, self._check_parse_result)

    def _check_parse_result(self):
        """轮询任务解析结果"""
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
                    # 继续解析下一个
                    self._parse_next_in_queue()
        except queue.Empty:
            # 还有任务在解析中
            if any(t.status == "parsing" for t in self.download_queue):
                self.root.after(200, self._check_parse_result)

    def _refresh_queue_ui(self):
        """刷新队列 Treeview 显示"""
        # 清空现有行
        for item in self.queue_tree.get_children():
            self.queue_tree.delete(item)

        status_icons = {
            "pending":   "⏳",
            "parsing":   "🔍",
            "queued":    "📋",
            "downloading": "⬇",
            "completed": "✅",
            "failed":    "❌",
            "cancelled": "⏹",
        }

        for i, task in enumerate(self.download_queue):
            icon = status_icons.get(task.status, "?")
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
        self.queue_title_label.configure(text=f"下载队列 ({count})")

        # 显示/隐藏队列区域
        if count > 0 and not self.queue_frame.winfo_ismapped():
            self.queue_frame.pack(fill=tk.X, pady=(0, PAD_STD))
        elif count == 0 and self.queue_frame.winfo_ismapped():
            self.queue_frame.pack_forget()

        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _remove_from_queue(self, idx: int):
        """从队列中删除指定任务"""
        if 0 <= idx < len(self.download_queue):
            task = self.download_queue[idx]
            if task.status == "downloading":
                self._update_status("⚠  无法删除正在下载的任务，请先取消", "warning")
                return
            del self.download_queue[idx]
            self._refresh_queue_ui()

    def _clear_completed(self):
        """清空已完成和失败的任务"""
        self.download_queue = [
            t for t in self.download_queue
            if t.status not in ("completed", "failed", "cancelled")
        ]
        self._refresh_queue_ui()

    def _on_queue_select(self, event):
        """点击队列项 — 预览视频信息"""
        selection = self.queue_tree.selection()
        if not selection:
            return
        idx = int(selection[0])
        task = self.download_queue[idx]

        if task.info:
            self._show_task_info(task)

    def _on_queue_double_click(self, event):
        """双击队列项 — 显示详情"""
        self._on_queue_select(event)

    def _on_queue_right_click(self, event):
        """右键菜单 — 删除/重试"""
        item = self.queue_tree.identify_row(event.y)
        if not item:
            return
        idx = int(item)
        task = self.download_queue[idx]

        menu = tk.Menu(self.root, tearoff=0, bg=BG_SECONDARY, fg=TEXT_PRIMARY,
                       activebackground=ACCENT, activeforeground="#ffffff",
                       font=(FONT_UI, 9))
        menu.add_command(label="删除", command=lambda: self._remove_from_queue(idx))
        if task.status == "failed":
            menu.add_command(label="重试解析",
                             command=lambda: self._retry_parse(idx))
        menu.add_separator()
        menu.add_command(label="清空已完成", command=self._clear_completed)
        menu.post(event.x_root, event.y_root)

    def _retry_parse(self, idx: int):
        """重试解析失败的任务"""
        task = self.download_queue[idx]
        task.status = "pending"
        task.error_msg = ""
        self._refresh_queue_ui()
        self._parse_next_in_queue()

    def _show_task_info(self, task: DownloadTask):
        """在视频信息卡片中显示任务详情"""
        if not task.info:
            return

        self.video_info = task.info
        self.video_formats = task.formats

        self.video_title_label.configure(text=task.title)
        self.video_meta_label.configure(
            text=f"时长: {task.duration}  ·  平台: {task.info.get('extractor_key', '?')}")
        self.video_uploader_label.configure(
            text=f"上传者: {task.uploader}" if task.uploader else "")

        # 填充格式
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

        # 显示信息卡片
        if not self.info_frame.winfo_ismapped():
            self.info_frame.pack(before=self.format_frame, fill=tk.X,
                                 pady=(0, PAD_STD))

        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    # ═══════════════════════════════════════════════════════
    # 格式处理（共享）
    # ═══════════════════════════════════════════════════════

    def _filter_formats(self, info: dict) -> list:
        """过滤并去重可用格式列表"""
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
                existing_size = existing.get("filesize") or existing.get("filesize_approx") or 0
                new_size = f.get("filesize") or f.get("filesize_approx") or 0
                if new_size > existing_size:
                    usable.remove(existing)
                    f_copy = dict(f)
                    f_copy["key"] = key
                    usable.append(f_copy)
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
        """打开文件夹选择对话框"""
        current = self.save_path_var.get()
        if not os.path.isdir(current):
            current = os.path.expanduser("~\\Downloads")
        path = filedialog.askdirectory(title="选择保存位置", initialdir=current)
        if path:
            self.save_path_var.set(path)

    # ═══════════════════════════════════════════════════════
    # 单视频下载（保留兼容）
    # ═══════════════════════════════════════════════════════

    def _start_single_download(self):
        """单视频模式：从解析的 info 下载（兼容旧行为）"""
        url = self._get_urls_from_text()
        url = url[0] if url else ""

        save_path = self.save_path_var.get().strip()
        fmt_idx = self.format_combo.current()

        if not url:
            self._update_status("⚠  请输入视频链接", "warning")
            return
        if not self.video_formats or fmt_idx < 0:
            self._update_status("⚠  请先解析视频链接（点击队列中的任务）", "warning")
            return
        if not save_path or not os.path.isdir(save_path):
            self._update_status("⚠  请选择保存位置", "warning")
            return

        # 创建单任务
        task = DownloadTask(url=url, status="downloading")
        if self.video_info:
            task.info = self.video_info
            task.title = self.video_info.get("title", "")
            task.formats = self.video_formats
        task.format_id = self.video_formats[fmt_idx].get("format_id", "")

        self._current_task = task
        self._batch_mode = False

        self._start_task_download(task)

    # ═══════════════════════════════════════════════════════
    # 批量下载引擎
    # ═══════════════════════════════════════════════════════

    def _start_all_downloads(self):
        """批量模式入口：逐个下载队列中的任务"""
        # 收集所有 queued 任务
        ready = [t for t in self.download_queue if t.status == "queued"]
        if not ready:
            self._update_status("⚠  队列中没有待下载的任务", "warning")
            return

        save_path = self.save_path_var.get().strip()
        if not save_path or not os.path.isdir(save_path):
            self._update_status("⚠  请选择保存位置", "warning")
            return

        self._batch_mode = True
        self._update_status(f"⬇  开始批量下载 ({len(ready)} 个视频)...", "progress")
        self._process_next()

    def _process_next(self):
        """处理队列中下一个待下载任务"""
        # 找第一个 queued 任务
        for task in self.download_queue:
            if task.status == "queued":
                self._current_task = task
                self._start_task_download(task)
                return

        # 全部完成
        self._batch_mode = False
        self._current_task = None
        completed = sum(1 for t in self.download_queue if t.status == "completed")
        failed = sum(1 for t in self.download_queue if t.status == "failed")
        self._update_status(f"✅  批量下载完成 — 成功 {completed} / 失败 {failed}", "success")
        self._set_ui_state("ready")
        self.download_btn.configure(state="normal")
        self._hide_progress()

    def _start_task_download(self, task: DownloadTask):
        """对单个 task 启动下载"""
        task.status = "downloading"
        task.progress = 0.0
        self.downloading = True
        self.cancel_requested = False

        self._refresh_queue_ui()
        self._set_ui_state("downloading")

        # 显示进度区域
        self._show_progress()

        self.progress_bar["value"] = 0
        self.pct_label.configure(text="0%")
        self.speed_label.configure(text="速度: --")
        self.eta_label.configure(text="剩余: --")

        task_label = task.title or task.url[:50]
        self._update_status(f"⬇  正在下载: {task_label}", "progress")

        save_path = self.save_path_var.get().strip()
        format_id = task.format_id

        # 如果 task 没有 format_id，用最佳默认值
        if not format_id and task.formats:
            format_id = task.formats[0].get("format_id", "best")
        if not format_id:
            format_id = "best"

        threading.Thread(
            target=self._download_thread,
            args=(task.url, format_id, save_path),
            daemon=True,
        ).start()

        self._poll_progress()

    def _cancel_all_downloads(self):
        """取消当前下载（批量模式下停止队列）"""
        if self.downloading:
            self.cancel_requested = True
            # 把剩余 queued 标记为 cancelled
            for task in self.download_queue:
                if task.status == "queued":
                    task.status = "cancelled"
            self._update_status("⏹  正在取消...", "warning")
        else:
            self._update_status("⏹  没有正在进行的下载", "info")

    def _download_thread(self, url, format_id, save_path):
        """后台下载线程"""
        import yt_dlp
        try:
            ydl_opts = {
                "format": format_id,
                "outtmpl": os.path.join(save_path, "%(title)s.%(ext)s"),
                "progress_hooks": [self._progress_hook],
                "quiet": True,
                "no_warnings": True,
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
        """yt-dlp 进度回调 — 在下载线程中运行"""
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
                "downloaded": d.get("downloaded_bytes", 0),
                "total": d.get("total_bytes") or d.get("total_bytes_estimate", 0),
            })

    def _poll_progress(self):
        """主线程轮询进度队列 — 更新 UI"""
        if not self.downloading:
            return

        try:
            while True:
                data = self.progress_queue.get_nowait()
                status = data.get("status", "")

                if status == "finished":
                    self._on_task_done(data)
                    return
                elif status == "error":
                    self._on_task_error(data)
                    return
                elif status == "cancelled":
                    self._on_task_cancelled()
                    return
                else:
                    self._update_progress_ui(data)
        except queue.Empty:
            pass

        self._poll_after_id = self.root.after(100, self._poll_progress)

    def _update_progress_ui(self, data):
        """更新进度条和标签"""
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

        # 更新当前任务和 Treeview
        if self._current_task:
            self._current_task.progress = pct
            self._current_task.speed = speed
            self._current_task.eta = eta
            self._refresh_queue_ui()

    def _on_task_done(self, data):
        """单个任务下载完成"""
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
            # 继续下一个
            self.root.after(300, self._process_next)
        else:
            # 单视频模式
            self._current_task = None
            self._set_ui_state("ready")
            self.download_btn.configure(state="normal")
            self.progress_bar["value"] = 100
            self.pct_label.configure(text="100%")

    def _on_task_error(self, data):
        """单个任务下载失败"""
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
            self._update_status(f"❌  失败: {task.error_msg}", "error")

        self._refresh_queue_ui()

        if self._batch_mode:
            self.root.after(300, self._process_next)
        else:
            self._current_task = None
            self._set_ui_state("ready")
            self.download_btn.configure(state="normal")

    def _on_task_cancelled(self):
        """下载已取消"""
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
        """显示进度区域"""
        self.progress_frame.pack_forget()
        self.progress_frame.pack(before=self.dl_btn_frame, fill=tk.X,
                                  pady=(0, PAD_STD))
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _hide_progress(self):
        """隐藏进度区域"""
        self.progress_frame.pack_forget()
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    # ═══════════════════════════════════════════════════════
    # UI 状态管理
    # ═══════════════════════════════════════════════════════

    def _set_ui_state(self, state):
        """集中控制各控件的状态"""
        states = {
            "ready": {
                "url": "normal", "paste": "normal", "add_queue": "normal",
                "clear_url": "normal", "platform": "readonly",
                "format": "disabled", "save": "normal", "browse": "normal",
                "download": "disabled", "batch_dl": "normal",
            },
            "parsing": {
                "url": "normal", "paste": "normal", "add_queue": "disabled",
                "clear_url": "normal", "platform": "readonly",
                "format": "disabled", "save": "normal", "browse": "normal",
                "download": "disabled", "batch_dl": "disabled",
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
        """更新状态栏"""
        colors = {
            "info":    TEXT_SECONDARY,
            "success": SUCCESS_COLOR,
            "error":   ERROR_COLOR,
            "warning": WARNING_COLOR,
            "progress": ACCENT,
        }
        color = colors.get(status_type, TEXT_SECONDARY)
        try:
            self.status_label.configure(text=text, foreground=color)
        except tk.TclError:
            pass

    # ═══════════════════════════════════════════════════════
    # 下载历史
    # ═══════════════════════════════════════════════════════

    def _add_to_history(self, title, filepath):
        """添加记录到下载历史"""
        entry = {
            "title": title,
            "path": filepath,
            "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        self.download_history.insert(0, entry)
        display = f"{entry['time']}  ·  {title}"
        self.history_listbox.insert(0, display)

        if len(self.download_history) > 50:
            self.download_history.pop()
            self.history_listbox.delete(tk.END)

        if not self.history_frame.winfo_ismapped():
            self.history_frame.pack(fill=tk.X, pady=(0, 0))

        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _clear_history(self):
        """清空下载历史"""
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

    @staticmethod
    def _check_ffmpeg():
        if shutil.which("ffmpeg"):
            return True
        common = [
            os.path.expandvars(r"%LOCALAPPDATA%\ffmpeg\bin\ffmpeg.exe"),
            os.path.expandvars(r"%ProgramFiles%\ffmpeg\bin\ffmpeg.exe"),
            r"C:\ffmpeg\bin\ffmpeg.exe",
            r"C:\tools\ffmpeg\bin\ffmpeg.exe",
        ]
        for p in common:
            if os.path.isfile(p):
                return True
        try:
            subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=5)
            return True
        except Exception:
            return False

    def _detect_platform(self, url):
        url_lower = url.lower()
        for platform, pattern in PLATFORM_PATTERNS.items():
            if re.search(pattern, url_lower):
                return platform
        return None

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
        self.root.destroy()

    def run(self):
        self.root.mainloop()


# ── 入口 ────────────────────────────────────────────────

def main():
    app = VideoDownloaderApp()
    app.run()


if __name__ == "__main__":
    main()
