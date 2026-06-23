#!/usr/bin/env python3
"""
Video Downloader — 桌面视频下载器
基于 yt-dlp + Tkinter 的 Windows 桌面视频下载工具。
支持 YouTube、Bilibili、Twitter/X、TikTok 等 1800+ 网站。
审美参考 Obsidian：深色主题、紫色 accent、4px 网格系统。
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

# yt-dlp extractor keys per platform (for platform hint)
PLATFORM_EXTRACTORS = {
    "youtube":   "youtube",
    "bilibili":  "bilibili",
    "twitter":   "twitter",
    "tiktok":    "tiktok",
    "instagram": "instagram",
    "vimeo":     "vimeo",
}

# ── 自定义异常 ──────────────────────────────────────────

class DownloadCancelled(Exception):
    """用户取消下载"""
    pass


# ── 主应用类 ────────────────────────────────────────────

class VideoDownloaderApp:
    """视频下载器主应用"""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Video Downloader")
        self.root.geometry("700x800")
        self.root.minsize(520, 680)
        self.root.configure(bg=BG_PRIMARY)

        self._set_app_id()

        # ── 状态变量 ──────────────────────────────
        self.url_var        = tk.StringVar()
        self.platform_var   = tk.StringVar(value="")
        self.save_path_var  = tk.StringVar(value=os.path.expanduser("~\\Downloads"))
        self.format_var     = tk.StringVar()

        # 视频信息（解析后填充）
        self.video_info     = None
        self.video_formats  = []
        self.thumbnail_img  = None   # tk.PhotoImage 引用（防 GC）
        self._thumb_path    = None   # 临时缩略图文件路径

        # 下载状态
        self.downloading    = False
        self.cancel_requested = False
        self.download_thread = None
        self.progress_queue = queue.Queue()
        self.parse_queue    = queue.Queue()
        self._parse_after_id = None
        self._poll_after_id  = None

        # 下载历史
        self.download_history = []

        # ffmpeg
        self.has_ffmpeg = self._check_ffmpeg()

        # ── 构建 UI ──────────────────────────────
        self._setup_styles()
        self._build_ui()
        self._bind_keys()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # 启动就置入默认路径
        self.save_path_var.set(os.path.expanduser("~\\Downloads"))

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
        self.root.bind("<Escape>", lambda e: self._cancel_download())

    # ═══════════════════════════════════════════════════════
    # 样式
    # ═══════════════════════════════════════════════════════

    def _setup_styles(self):
        """配置 ttk 样式 — Obsidian 深色主题"""
        style = ttk.Style()
        style.theme_use("clam")

        # ── 基础 ──────────────────────────────────
        style.configure(".",
            background=BG_PRIMARY,
            foreground=TEXT_PRIMARY,
            fieldbackground=BG_TERTIARY,
            bordercolor=BORDER,
            font=(FONT_UI, 10),
        )

        # ── Frame ──────────────────────────────────
        style.configure("TFrame", background=BG_PRIMARY)
        style.configure("Card.TFrame", background=BG_SECONDARY, relief="flat")

        # ── Label ──────────────────────────────────
        style.configure("TLabel",
            background=BG_PRIMARY,
            foreground=TEXT_PRIMARY,
            font=(FONT_UI, 10),
        )
        style.configure("Title.TLabel",
            font=(FONT_UI, 22, "bold"),
            foreground=ACCENT,
        )
        style.configure("Heading.TLabel",
            font=(FONT_UI, 13, "bold"),
            foreground=TEXT_PRIMARY,
        )
        style.configure("Card.TLabel",
            background=BG_SECONDARY,
            foreground=TEXT_PRIMARY,
            font=(FONT_UI, 10),
        )
        style.configure("CardHeading.TLabel",
            background=BG_SECONDARY,
            foreground=TEXT_PRIMARY,
            font=(FONT_UI, 12, "bold"),
        )
        style.configure("Muted.TLabel",
            foreground=TEXT_MUTED,
            font=(FONT_UI, 9),
        )
        style.configure("Success.TLabel", foreground=SUCCESS_COLOR)
        style.configure("Error.TLabel", foreground=ERROR_COLOR)
        style.configure("Warning.TLabel", foreground=WARNING_COLOR)

        # ── Button ─────────────────────────────────
        style.configure("TButton",
            background=BG_TERTIARY,
            foreground=TEXT_PRIMARY,
            borderwidth=1,
            relief="flat",
            padding=(PAD_STD, PAD),
            font=(FONT_UI, 10),
        )
        style.map("TButton",
            background=[("active", "#3a3a3a"), ("pressed", BG_TERTIARY)],
            foreground=[("active", "#ffffff")],
        )

        # Accent 按钮（紫色主按钮）
        style.configure("Accent.TButton",
            background=ACCENT,
            foreground="#ffffff",
            font=(FONT_UI, 12, "bold"),
            borderwidth=0,
            padding=(PAD_WIDE, PAD_COMFORT),
        )
        style.map("Accent.TButton",
            background=[("active", ACCENT_HOVER), ("pressed", ACCENT)],
            foreground=[("active", "#ffffff")],
        )

        # Danger 按钮（红色取消）
        style.configure("Danger.TButton",
            background=ERROR_COLOR,
            foreground="#ffffff",
            font=(FONT_UI, 12, "bold"),
            borderwidth=0,
            padding=(PAD_WIDE, PAD_COMFORT),
        )
        style.map("Danger.TButton",
            background=[("active", "#ef4444"), ("pressed", ERROR_COLOR)],
            foreground=[("active", "#ffffff")],
        )

        # ── Entry ──────────────────────────────────
        style.configure("TEntry",
            fieldbackground=BG_TERTIARY,
            foreground=TEXT_PRIMARY,
            borderwidth=1,
            relief="solid",
            padding=6,
        )
        style.map("TEntry",
            fieldbackground=[("focus", BG_TERTIARY)],
            bordercolor=[("focus", ACCENT)],
        )

        # ── Combobox ───────────────────────────────
        style.configure("TCombobox",
            fieldbackground=BG_TERTIARY,
            foreground=TEXT_PRIMARY,
            arrowcolor=TEXT_PRIMARY,
            background=BG_TERTIARY,
        )
        style.map("TCombobox",
            fieldbackground=[("readonly", BG_TERTIARY), ("focus", BG_TERTIARY)],
            bordercolor=[("focus", ACCENT)],
        )
        self.root.option_add("*TCombobox*Listbox.background", BG_SECONDARY)
        self.root.option_add("*TCombobox*Listbox.foreground", TEXT_PRIMARY)
        self.root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        self.root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")

        # ── Progressbar ────────────────────────────
        style.configure("TProgressbar",
            background=ACCENT,
            troughcolor=BG_SECONDARY,
            bordercolor=BORDER,
        )

        # ── Separator ──────────────────────────────
        style.configure("TSeparator", background=BORDER)

        # ── LabelFrame ─────────────────────────────
        style.configure("Card.TLabelframe", background=BG_SECONDARY)
        style.configure("Card.TLabelframe.Label",
            background=BG_SECONDARY,
            foreground=TEXT_PRIMARY,
            font=(FONT_UI, 11, "bold"),
        )

    # ═══════════════════════════════════════════════════════
    # UI 构建
    # ═══════════════════════════════════════════════════════

    def _build_ui(self):
        """构建全部界面"""
        # 主容器
        self.main_frame = ttk.Frame(self.root, padding=(PAD_XL, PAD_WIDE))
        self.main_frame.pack(fill=tk.BOTH, expand=True)

        # 滚动支持 — Canvas + Scrollbar
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

        # Canvas 大小跟随
        self._canvas.bind("<Configure>", self._on_canvas_configure)

        self._canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        # 滚动条先隐藏，内容多了再显示

        # ── 标题 ───────────────────────────────────
        self._build_title(self._scroll_frame)

        # ── URL 输入 ──────────────────────────────
        self._build_url_section(self._scroll_frame)

        # ── 视频信息卡片 ──────────────────────────
        self._build_video_info(self._scroll_frame)

        # ── 格式 & 保存路径 ───────────────────────
        self._build_format_section(self._scroll_frame)

        # ── 下载按钮 ──────────────────────────────
        self._build_download_button(self._scroll_frame)

        # ── 进度区域 ──────────────────────────────
        self._build_progress_section(self._scroll_frame)

        # ── 下载历史 ──────────────────────────────
        self._build_history_section(self._scroll_frame)

        # ── 状态栏 ────────────────────────────────
        self._build_status_bar(self.main_frame)

    def _on_canvas_configure(self, event):
        """Canvas 大小变化时调整内部 frame 宽度"""
        self._canvas.itemconfig(self._canvas_window, width=event.width)
        # 显示/隐藏滚动条
        if self._scroll_frame.winfo_reqheight() > event.height:
            self._scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        else:
            self._scrollbar.pack_forget()

    def _build_title(self, parent):
        """标题栏"""
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.X, pady=(0, PAD_WIDE))

        ttk.Label(frame, text="Video Downloader",
                  style="Title.TLabel").pack(anchor="w")

        subtitle = "下载 YouTube · Bilibili · Twitter · TikTok 等 1800+ 网站的视频"
        ttk.Label(frame, text=subtitle, style="Muted.TLabel").pack(anchor="w", pady=(PAD_TIGHT, 0))

        # FFmpeg 提示
        if not self.has_ffmpeg:
            ttk.Label(frame,
                text="⚠ FFmpeg 未安装 — 部分格式合并不可用",
                style="Warning.TLabel").pack(anchor="w", pady=(PAD, 0))

        ttk.Separator(parent, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=(PAD_STD, PAD_STD))

    def _build_url_section(self, parent):
        """URL 输入区域"""
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.X, pady=(0, PAD_STD))

        # 第一行：URL 标签 + 输入框 + 粘贴按钮
        row1 = ttk.Frame(frame)
        row1.pack(fill=tk.X)
        ttk.Label(row1, text="视频链接", style="Heading.TLabel").pack(anchor="w")

        row2 = ttk.Frame(frame)
        row2.pack(fill=tk.X, pady=(PAD, 0))

        self.url_entry = ttk.Entry(row2, textvariable=self.url_var, font=(FONT_UI, 11))
        self.url_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, PAD))

        self.paste_btn = ttk.Button(row2, text="粘贴", command=self._on_paste, width=8)
        self.paste_btn.pack(side=tk.RIGHT)

        # URL 变更防抖
        self.url_var.trace_add("write", self._on_url_change)

        # 第二行：平台选择
        row3 = ttk.Frame(frame)
        row3.pack(fill=tk.X, pady=(PAD, 0))

        ttk.Label(row3, text="平台").pack(side=tk.LEFT)

        platforms = list(PLATFORM_NAMES.values())
        self.platform_combo = ttk.Combobox(
            row3, textvariable=self.platform_var,
            values=platforms,
            state="readonly",
            width=16,
            font=(FONT_UI, 10),
        )
        self.platform_combo.set(PLATFORM_NAMES[""])
        self.platform_combo.pack(side=tk.LEFT, padx=(PAD, 0))
        self.platform_combo.bind("<<ComboboxSelected>>", self._on_platform_select)

    def _build_video_info(self, parent):
        """视频信息卡片"""
        self.info_frame = ttk.Frame(parent, style="Card.TFrame")
        # 默认隐藏，解析成功后显示

        # 内容用 pack 放在卡片内部
        self.info_inner = ttk.Frame(self.info_frame, style="Card.TFrame")
        self.info_inner.pack(fill=tk.X, padx=PAD_STD, pady=PAD_STD)

        # 缩略图
        self.thumb_label = ttk.Label(self.info_inner, style="Card.TLabel")
        self.thumb_label.pack(side=tk.LEFT, padx=(0, PAD_STD))

        # 右侧文字
        text_frame = ttk.Frame(self.info_inner, style="Card.TFrame")
        text_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.video_title_label = ttk.Label(
            text_frame, text="", style="CardHeading.TLabel",
            wraplength=420,
        )
        self.video_title_label.pack(anchor="w")

        self.video_meta_label = ttk.Label(
            text_frame, text="", style="Muted.TLabel",
        )
        self.video_meta_label.pack(anchor="w", pady=(PAD_TIGHT, 0))

        self.video_uploader_label = ttk.Label(
            text_frame, text="", style="Muted.TLabel",
        )
        self.video_uploader_label.pack(anchor="w")

    def _build_format_section(self, parent):
        """格式选择和保存路径"""
        self.format_frame = ttk.Frame(parent)
        self.format_frame.pack(fill=tk.X, pady=(PAD_STD, PAD_STD))
        frame = self.format_frame

        # 分辨率
        ttk.Label(frame, text="分辨率", style="Heading.TLabel").pack(anchor="w")

        fmt_row = ttk.Frame(frame)
        fmt_row.pack(fill=tk.X, pady=(PAD, 0))

        self.format_combo = ttk.Combobox(
            fmt_row, textvariable=self.format_var,
            state="readonly",
            font=(FONT_UI, 10),
        )
        self.format_combo.pack(fill=tk.X)
        self.format_combo.bind("<<ComboboxSelected>>", lambda e: None)

        # 保存路径
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
        """下载 / 取消按钮"""
        btn_frame = ttk.Frame(parent)
        btn_frame.pack(fill=tk.X, pady=(PAD, PAD_STD))

        self.download_btn = ttk.Button(
            btn_frame,
            text="⬇  开始下载",
            style="Accent.TButton",
            command=self._start_download,
        )
        self.download_btn.pack(fill=tk.X, ipady=4)

    def _build_progress_section(self, parent):
        """下载进度区域"""
        self.progress_frame = ttk.Frame(parent)
        # 默认隐藏

        # 进度条
        self.progress_bar = ttk.Progressbar(
            self.progress_frame,
            mode="determinate",
            maximum=100,
        )
        self.progress_bar.pack(fill=tk.X)

        # 百分比
        self.pct_label = ttk.Label(
            self.progress_frame,
            text="0%",
            font=(FONT_UI, 24, "bold"),
            foreground=ACCENT,
            background=BG_PRIMARY,
            anchor="center",
        )
        self.pct_label.pack(pady=(PAD_STD, PAD))

        # 速度 + ETA 行
        info_row = ttk.Frame(self.progress_frame)
        info_row.pack(fill=tk.X)

        self.speed_label = ttk.Label(info_row, text="速度: --", style="Muted.TLabel")
        self.speed_label.pack(side=tk.LEFT)

        self.eta_label = ttk.Label(info_row, text="剩余: --", style="Muted.TLabel")
        self.eta_label.pack(side=tk.RIGHT)

    def _build_history_section(self, parent):
        """下载历史"""
        self.history_frame = ttk.Frame(parent)
        # 默认隐藏

        ttk.Separator(self.history_frame, orient=tk.HORIZONTAL).pack(
            fill=tk.X, pady=(PAD_STD, PAD_STD))

        hist_header = ttk.Frame(self.history_frame)
        hist_header.pack(fill=tk.X)
        ttk.Label(hist_header, text="下载历史",
                  style="Heading.TLabel").pack(side=tk.LEFT)
        self.clear_hist_btn = ttk.Button(hist_header, text="清除",
                                          command=self._clear_history, width=6)
        self.clear_hist_btn.pack(side=tk.RIGHT)

        # 历史列表（使用 tk.Listbox 而非 ttk，因为后者不支持自定义颜色）
        self.history_listbox = tk.Listbox(
            self.history_frame,
            bg=BG_SECONDARY,
            fg=TEXT_PRIMARY,
            selectbackground=ACCENT,
            selectforeground="#ffffff",
            font=(FONT_UI, 9),
            height=6,
            borderwidth=0,
            highlightthickness=0,
            activestyle="none",
        )
        self.history_listbox.pack(fill=tk.X, pady=(PAD, 0))

    def _build_status_bar(self, parent):
        """底部状态栏"""
        status_frame = ttk.Frame(parent)
        status_frame.pack(fill=tk.X, side=tk.BOTTOM, pady=(PAD_STD, 0))

        ttk.Separator(status_frame, orient=tk.HORIZONTAL).pack(fill=tk.X)

        self.status_label = ttk.Label(
            status_frame,
            text="✅  就绪",
            font=(FONT_UI, 10),
            foreground=TEXT_SECONDARY,
            background=BG_PRIMARY,
        )
        self.status_label.pack(anchor="w", pady=(PAD, 0))

    # ═══════════════════════════════════════════════════════
    # URL 解析
    # ═══════════════════════════════════════════════════════

    def _on_url_change(self, *args):
        """URL 变更 — 防抖 500ms 后自动解析"""
        url = self.url_var.get().strip()
        if not url:
            return
        # 取消之前的待处理
        if self._parse_after_id:
            self.root.after_cancel(self._parse_after_id)
        self._parse_after_id = self.root.after(500, self._parse_url)

    def _on_paste(self):
        """粘贴按钮：读取剪贴板并立即解析"""
        try:
            text = self.root.clipboard_get()
            if text and text.strip():
                self.url_var.set(text.strip())
                # 取消防抖，立即解析
                if self._parse_after_id:
                    self.root.after_cancel(self._parse_after_id)
                self._parse_url()
        except tk.TclError:
            # 剪贴板可能为空或非文本
            pass

    def _on_platform_select(self, event):
        """平台选择变更"""
        url = self.url_var.get().strip()
        if url:
            if self._parse_after_id:
                self.root.after_cancel(self._parse_after_id)
            self._parse_url()

    def _get_platform_key(self):
        """将 combobox 选择映射回 platform key"""
        val = self.platform_var.get()
        for key, name in PLATFORM_NAMES.items():
            if name == val:
                return key
        return ""

    def _detect_platform(self, url):
        """根据 URL 自动检测平台"""
        url_lower = url.lower()
        for platform, pattern in PLATFORM_PATTERNS.items():
            if re.search(pattern, url_lower):
                return platform
        return None

    def _parse_url(self):
        """在后台线程解析 URL"""
        url = self.url_var.get().strip()
        if not url or self.downloading:
            return

        self._update_status("🔍  正在解析视频信息...", "info")
        self._set_ui_state("parsing")

        def _extract():
            try:
                ydl_opts = {
                    "quiet": True,
                    "no_warnings": True,
                    "extract_flat": False,
                }
                with __import__("yt_dlp").YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=False)

                # 如果是播放列表，取第一个
                if info and info.get("_type") == "playlist" and "entries" in info:
                    entries = info.get("entries", [])
                    if entries:
                        info = entries[0]
                    else:
                        self.parse_queue.put(("error", "播放列表为空"))
                        return

                self.parse_queue.put(("success", info))
            except Exception as e:
                err_msg = str(e)
                # 简化常见错误
                if "HTTP Error 404" in err_msg:
                    err_msg = "视频未找到 (404)"
                elif "HTTP Error 403" in err_msg:
                    err_msg = "访问被拒绝 (403)"
                elif "Unsupported URL" in err_msg:
                    err_msg = "不支持的链接格式"
                elif "connection" in err_msg.lower() or "getaddrinfo" in err_msg:
                    err_msg = "网络连接失败，请检查网络"
                self.parse_queue.put(("error", err_msg))

        threading.Thread(target=_extract, daemon=True).start()
        self.root.after(100, self._check_parse_result)

    def _check_parse_result(self):
        """轮询解析结果"""
        try:
            while True:
                status, data = self.parse_queue.get_nowait()
                if status == "success":
                    self._on_parse_complete(data)
                else:
                    self._update_status(f"❌  {data}", "error")
                    self._set_ui_state("ready")
        except queue.Empty:
            # 还在解析中，继续等待
            if not self.downloading:
                self.root.after(200, self._check_parse_result)

    def _on_parse_complete(self, info):
        """解析成功，填充 UI"""
        self.video_info = info

        title = info.get("title", "未知标题")
        duration = info.get("duration", 0)
        uploader = info.get("uploader", "") or info.get("channel", "") or ""
        thumb_url = info.get("thumbnail", "")

        # 填充文字
        self.video_title_label.configure(text=title)
        self.video_meta_label.configure(
            text=f"时长: {self._format_duration(duration)}  ·  "
                 f"平台: {info.get('extractor_key', '?')}"
        )
        self.video_uploader_label.configure(
            text=f"上传者: {uploader}" if uploader else ""
        )

        # 下载缩略图
        if thumb_url:
            self._download_thumbnail(thumb_url)

        # 填充格式
        display_strings = self._populate_formats(info)
        if display_strings:
            self.format_combo.configure(values=display_strings)
            self.format_combo.current(0)
            self._set_ui_state("ready_to_download")
            self._update_status(f"✅  解析完成 — {len(display_strings)} 种分辨率可选", "success")
        else:
            self._update_status("❌  未找到可下载的格式", "error")
            self._set_ui_state("ready")

        # 自动检测平台并更新下拉框
        detected = self._detect_platform(self.url_var.get())
        if detected and detected in PLATFORM_NAMES:
            self.platform_var.set(PLATFORM_NAMES[detected])

        # 显示信息卡片
        self.info_frame.pack(
            before=self.format_frame, fill=tk.X,
            pady=(0, PAD_STD),
        )

        # 确保 canvas 滚动区域更新
        self._canvas.configure(
            scrollregion=self._canvas.bbox("all"))

    def _populate_formats(self, info):
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
                # 保留 filesize 更大的
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

        # 按高度降序排列
        usable.sort(key=lambda x: x.get("height", 0), reverse=True)

        self.video_formats = usable

        # 构建显示字符串
        display = []
        for f in usable:
            h = f["height"]
            e = f.get("ext", "?")
            size = f.get("filesize") or f.get("filesize_approx") or 0
            display.append(f"{h}p ({e})  ~ {self._format_filesize(size)}")

        return display

    def _download_thumbnail(self, url):
        """下载缩略图到临时文件并显示"""
        try:
            import urllib.request
            import urllib.parse

            parsed = urllib.parse.urlparse(url)
            suffix = os.path.splitext(parsed.path)[1] or ".jpg"
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
            tmp_path = tmp.name
            tmp.close()

            urllib.request.urlretrieve(url, tmp_path)

            # 清理旧缩略图
            if self._thumb_path and os.path.isfile(self._thumb_path):
                try:
                    os.unlink(self._thumb_path)
                except Exception:
                    pass

            self._thumb_path = tmp_path

            # 用 tk.PhotoImage 加载（不做 resize，保持简单）
            img = tk.PhotoImage(file=tmp_path)

            # 如果宽度 > 240，等比缩小
            if img.width() > 240:
                scale = 240 / img.width()
                img = img.subsample(
                    max(1, int(1 / scale)),
                    max(1, int(1 / scale)),
                )

            self.thumbnail_img = img  # 保持引用防 GC
            self.thumb_label.configure(image=img)
        except Exception:
            # 缩略图失败不阻塞主流程
            pass

    # ═══════════════════════════════════════════════════════
    # 保存路径
    # ═══════════════════════════════════════════════════════

    def _browse_save_path(self):
        """打开文件夹选择对话框"""
        current = self.save_path_var.get()
        if not os.path.isdir(current):
            current = os.path.expanduser("~\\Downloads")
        path = filedialog.askdirectory(
            title="选择保存位置",
            initialdir=current,
        )
        if path:
            self.save_path_var.set(path)

    # ═══════════════════════════════════════════════════════
    # 下载
    # ═══════════════════════════════════════════════════════

    def _start_download(self):
        """开始下载"""
        url = self.url_var.get().strip()
        save_path = self.save_path_var.get().strip()
        fmt_idx = self.format_combo.current()

        # 验证
        if not url:
            self._update_status("⚠  请输入视频链接", "warning")
            return
        if not self.video_formats or fmt_idx < 0:
            self._update_status("⚠  请先解析视频链接", "warning")
            return
        if not save_path:
            self._update_status("⚠  请选择保存位置", "warning")
            return
        if not os.path.isdir(save_path):
            self._update_status("⚠  保存路径不存在", "warning")
            return

        selected_format = self.video_formats[fmt_idx]
        format_id = selected_format.get("format_id", "")

        # 切换 UI
        self.downloading = True
        self.cancel_requested = False
        self._set_ui_state("downloading")
        self.download_btn.configure(text="取消下载", style="Danger.TButton",
                                     command=self._cancel_download)

        # 显示进度区（放在下载按钮之前）
        self.progress_frame.pack_forget()
        btn_parent = self.download_btn.master
        self.progress_frame.pack(
            before=self.download_btn, fill=tk.X,
            pady=(0, PAD_STD),
        )

        self.progress_bar["value"] = 0
        self.pct_label.configure(text="0%")
        self.speed_label.configure(text="速度: --")
        self.eta_label.configure(text="剩余: --")

        self._update_status("⬇  正在下载...", "progress")

        # 启动下载线程
        threading.Thread(
            target=self._download_thread,
            args=(url, format_id, save_path),
            daemon=True,
        ).start()

        # 开始轮询进度
        self._poll_progress()

    def _cancel_download(self):
        """取消下载"""
        self.cancel_requested = True
        self._update_status("⏹  正在取消...", "warning")

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
                    self._on_download_complete(data)
                    return
                elif status == "error":
                    self._on_download_error(data)
                    return
                elif status == "cancelled":
                    self._on_download_cancelled()
                    return
                else:
                    self._update_progress_ui(data)
        except queue.Empty:
            pass

        # 继续轮询
        self._poll_after_id = self.root.after(100, self._poll_progress)

    def _update_progress_ui(self, data):
        """更新进度条和标签"""
        # 解析百分比
        pct_str = data.get("percent_str", "0%")
        try:
            pct = float(pct_str.replace("%", "").strip())
        except (ValueError, AttributeError):
            pct = 0

        self.progress_bar["value"] = pct
        self.pct_label.configure(text=f"{pct:.1f}%")

        # 速度
        speed = data.get("speed_str", "N/A").strip()
        if speed and speed != "N/A":
            self.speed_label.configure(text=f"速度: {speed}")

        # ETA
        eta = data.get("eta_str", "N/A").strip()
        if eta and eta != "N/A":
            self.eta_label.configure(text=f"剩余: {eta}")
        else:
            self.eta_label.configure(text="剩余: --")

    def _on_download_complete(self, data):
        """下载完成"""
        self.downloading = False
        self.download_btn.configure(text="⬇  开始下载", style="Accent.TButton",
                                     command=self._start_download)
        self._set_ui_state("ready_to_download")

        filename = data.get("filename", "")
        basename = os.path.basename(filename) if filename else "未知文件"
        self._update_status(f"✅  下载完成: {basename}", "success")

        # 添加到历史
        title = self.video_info.get("title", "未知") if self.video_info else "未知"
        self._add_to_history(title, filename)

        # 清理进度条
        self.progress_bar["value"] = 100
        self.pct_label.configure(text="100%")

    def _on_download_error(self, data):
        """下载失败"""
        self.downloading = False
        self.download_btn.configure(text="⬇  开始下载", style="Accent.TButton",
                                     command=self._start_download)
        self._set_ui_state("ready_to_download")

        msg = data.get("message", "未知错误")
        # 简化常见错误
        if "Permission denied" in msg or "PermissionError" in msg:
            msg = "写入权限不足，请更换保存位置"
        elif "No space" in msg or "disk" in msg.lower():
            msg = "磁盘空间不足"
        elif "connection" in msg.lower():
            msg = "网络连接中断"

        self._update_status(f"❌  下载失败: {msg}", "error")

    def _on_download_cancelled(self):
        """下载已取消"""
        self.downloading = False
        self.download_btn.configure(text="⬇  开始下载", style="Accent.TButton",
                                     command=self._start_download)
        self._set_ui_state("ready_to_download")
        self._update_status("⏹  下载已取消", "info")

    # ═══════════════════════════════════════════════════════
    # UI 状态管理
    # ═══════════════════════════════════════════════════════

    def _set_ui_state(self, state):
        """集中控制各控件的状态"""
        states = {
            "ready": {
                "url": "normal", "paste": "normal", "platform": "readonly",
                "format": "disabled", "save": "normal", "browse": "normal",
                "download": "disabled",
            },
            "parsing": {
                "url": "normal", "paste": "normal", "platform": "readonly",
                "format": "disabled", "save": "normal", "browse": "normal",
                "download": "disabled",
            },
            "ready_to_download": {
                "url": "normal", "paste": "normal", "platform": "readonly",
                "format": "readonly", "save": "normal", "browse": "normal",
                "download": "normal",
            },
            "downloading": {
                "url": "disabled", "paste": "disabled", "platform": "disabled",
                "format": "disabled", "save": "disabled", "browse": "disabled",
                "download": "normal",  # 按钮变为取消
            },
        }

        s = states.get(state, states["ready"])
        try:
            self.url_entry.configure(state=s["url"])
            self.paste_btn.configure(state=s["paste"])
            self.platform_combo.configure(state=s["platform"])
            self.format_combo.configure(state=s["format"])
            self.save_entry.configure(state=s["save"])
            self.browse_btn.configure(state=s["browse"])

            if state != "downloading":
                if s["download"] == "normal":
                    self.download_btn.configure(state="normal")
                else:
                    self.download_btn.configure(state="disabled")
        except tk.TclError:
            # Widget 可能已被销毁
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

        # 最多保留 50 条
        if len(self.download_history) > 50:
            self.download_history.pop()
            self.history_listbox.delete(tk.END)

        # 显示历史区域
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
        """字节 -> 人类可读"""
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
        """秒 -> HH:MM:SS 或 MM:SS"""
        if not seconds or seconds <= 0:
            return "?"
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        if h:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"

    @staticmethod
    def _check_ffmpeg():
        """检测 ffmpeg 是否可用"""
        # PATH
        if shutil.which("ffmpeg"):
            return True
        # 常见路径
        common = [
            os.path.expandvars(r"%LOCALAPPDATA%\ffmpeg\bin\ffmpeg.exe"),
            os.path.expandvars(r"%ProgramFiles%\ffmpeg\bin\ffmpeg.exe"),
            r"C:\ffmpeg\bin\ffmpeg.exe",
            r"C:\tools\ffmpeg\bin\ffmpeg.exe",
        ]
        for p in common:
            if os.path.isfile(p):
                return True
        # 尝试运行
        try:
            subprocess.run(
                ["ffmpeg", "-version"],
                capture_output=True,
                timeout=5,
            )
            return True
        except Exception:
            return False

    # ═══════════════════════════════════════════════════════
    # 生命周期
    # ═══════════════════════════════════════════════════════

    def _on_close(self):
        """窗口关闭"""
        if self.downloading:
            self.cancel_requested = True
        # 清理临时缩略图
        if self._thumb_path and os.path.isfile(self._thumb_path):
            try:
                os.unlink(self._thumb_path)
            except Exception:
                pass
        self.root.destroy()

    def run(self):
        """启动应用"""
        self.root.mainloop()


# ── 入口 ────────────────────────────────────────────────

def main():
    app = VideoDownloaderApp()
    app.run()


if __name__ == "__main__":
    main()
