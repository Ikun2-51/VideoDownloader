# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

Windows 桌面视频下载器，Python 3.12 + Tkinter 实现，基于 yt-dlp 引擎。

- 支持 YouTube / Bilibili / Twitter / TikTok / Instagram 等 1800+ 网站
- Obsidian 风格深色主题（#0d0d0d + #6930C7 紫色 accent）
- PyInstaller 打包为独立 exe

## 常用命令

```bash
# 运行应用
python video_downloader.py

# 语法检查
python -m py_compile video_downloader.py

# 打包为独立 exe
pyinstaller --onefile --windowed --name "VideoDownloader" --clean --collect-all yt_dlp video_downloader.py
```

Python 路径（未加入 PATH 时）:
```
%LOCALAPPDATA%\Programs\Python\Python312\python.exe
%LOCALAPPDATA%\Programs\Python\Python312\Scripts\pyinstaller.exe
```

## 架构

单文件 `video_downloader.py`（~1655 行），`VideoDownloaderApp` 类承载全部逻辑。

**批量下载**: 支持多行 URL 输入，解析后加入下载队列，逐个排队下载。`DownloadTask` 数据类管理每个任务状态。

**主题系统**: `ColorTheme` dataclass + 3 套预设（iOS 浅色 / iOS 深色 / Obsidian 深色），支持自定义调色盘编辑，主题自动持久化到 `%APPDATA%\VideoDownloader\theme.json`。

**压缩包导出**: 内置 `_export_zip()` 一键打包源码为 zip，包含 `video_downloader.py`、`CLAUDE.md`、`.gitignore`、`requirements.txt`、`README.md`。

**依赖**: `yt-dlp`（视频解析和下载引擎），可选 `ffmpeg`（视频和音频流合并）

**数据流**: `URL 输入 → 防抖 500ms → 后台线程 extract_info() → 队列 → 主线程填充 UI → 用户选择分辨率和路径 → 后台线程 download() → progress_hook → 队列 → 主线程每 100ms 更新进度`

**线程安全**:
- `threading.Thread(daemon=True)` — 解析和下载在后台运行
- `queue.Queue()` — 后台线程到主线程的唯一通信通道
- `tk.after(100, callback)` — 主线程轮询队列更新 UI
- `self.cancel_requested` bool — GIL 保证原子性，安全取消下载

**UI 布局** (从上到下):
1. 标题 + 副标题
2. URL 输入 + 粘贴按钮 + 平台选择下拉
3. 视频信息卡片（缩略图 + 标题/时长/上传者）— 解析后显示
4. 分辨率下拉 + 保存路径 + 浏览按钮
5. 下载/取消按钮（紫色 accent 大按钮）
6. 进度条 + 百分比 + 速度 + ETA — 下载时显示
7. 下载历史列表
8. 状态栏

## Obsidian 色板

| 角色 | 色值 | 用途 |
|------|------|------|
| BG_PRIMARY | #0d0d0d | 主背景 |
| BG_SECONDARY | #1a1a1a | 卡片/面板 |
| BG_TERTIARY | #2a2a2a | 输入框 |
| TEXT_PRIMARY | #cfcfcf | 主文字 |
| TEXT_SECONDARY | #808080 | 次要文字 |
| TEXT_MUTED | #595959 | 占位文字 |
| ACCENT | #6930C7 | 紫色强调 |
| SUCCESS | #4ade80 | 绿色 |
| ERROR | #f87171 | 红色 |
| WARNING | #fbbf24 | 黄色 |
