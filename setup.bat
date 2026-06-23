@echo off
chcp 65001 >nul
title Video Downloader - 安装向导

:: ═══════════════════════════════════════════════════
::  Video Downloader 一键安装脚本
::  自动检测环境 · 安装缺失组件 · 创建快捷方式
:: ═══════════════════════════════════════════════════

echo.
echo   ╔══════════════════════════════════════╗
echo   ║   🎬 Video Downloader 安装向导       ║
echo   ║   支持 1800+ 网站视频下载            ║
echo   ╚══════════════════════════════════════╝
echo.

:: ── 1. 检测 FFmpeg ──────────────────────────────
echo   [1/3] 检测 FFmpeg...
where ffmpeg >nul 2>&1
if %errorlevel% equ 0 (
    echo     ✅ FFmpeg 已安装
    goto :create_shortcut
)

:: 检查常见路径
if exist "%LOCALAPPDATA%\ffmpeg\bin\ffmpeg.exe" (
    set PATH=%LOCALAPPDATA%\ffmpeg\bin;%PATH%
    echo     ✅ FFmpeg 已找到
    goto :create_shortcut
)
if exist "%ProgramFiles%\ffmpeg\bin\ffmpeg.exe" (
    set PATH=%ProgramFiles%\ffmpeg\bin;%PATH%
    echo     ✅ FFmpeg 已找到
    goto :create_shortcut
)

echo     ⚠ FFmpeg 未安装 — 正在自动安装...
echo.

:: 尝试 winget 安装
where winget >nul 2>&1
if %errorlevel% equ 0 (
    echo     正在通过 winget 下载 FFmpeg...
    winget install --id Gyan.FFmpeg --accept-source-agreements --accept-package-agreements
    if %errorlevel% equ 0 (
        echo     ✅ FFmpeg 安装完成！
        goto :create_shortcut
    )
)

:: winget 不可用，打开浏览器
echo     无法自动安装。正在打开下载页面...
start "" "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
echo.
echo     📥 请手动下载并安装 FFmpeg:
echo        1. 解压下载的 zip 文件
echo        2. 将 bin 文件夹路径添加到系统环境变量 PATH
echo        3. 重新运行本脚本
echo.
pause
goto :end

:: ── 2. 创建桌面快捷方式 ──────────────────────────
:create_shortcut
echo.
echo   [2/3] 创建桌面快捷方式...

set SHORTCUT_PATH=%USERPROFILE%\Desktop\Video Downloader.lnk
set TARGET_PATH=%~dp0VideoDownloader.exe

:: 使用 PowerShell 创建快捷方式
powershell -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('%SHORTCUT_PATH%'); $s.TargetPath = '%TARGET_PATH%'; $s.WorkingDirectory = '%~dp0'; $s.Description = '视频下载器 - 支持 1800+ 网站'; $s.Save()"

if exist "%SHORTCUT_PATH%" (
    echo     ✅ 桌面快捷方式已创建
) else (
    echo     ⚠ 快捷方式创建失败，请手动创建
)

:: ── 3. 完成 ──────────────────────────────────────
echo.
echo   [3/3] 安装完成！
echo.
echo   ╔══════════════════════════════════════╗
echo   ║   ✅ 安装成功！                      ║
echo   ║                                      ║
echo   ║   双击桌面上的 "Video Downloader"    ║
echo   ║   即可开始使用                        ║
echo   ╚══════════════════════════════════════╝
echo.
echo   小提示:
echo   - 粘贴视频链接自动解析
echo   - 支持 YouTube/Bilibili/Twitter 等
echo   - 顶部可切换 iOS 浅色/深色主题
echo.

pause
:end
exit /b 0
