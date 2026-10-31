"""所有固定位置集中在这里：程序自带的资源（界面、语言包、LUT）和用户数据文件夹。

ROOT 是工具文件夹（源码运行时是仓库根目录；打包成 Mac 应用后是应用里的资源目录），
web/、locales/、luts/ 都在它下面。用户数据统一放在 ~/.photo-cull/。
"""
from __future__ import annotations

import sys
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))          # PyInstaller 打包后运行
ROOT = Path(getattr(sys, "_MEIPASS", "")) if FROZEN and getattr(sys, "_MEIPASS", None) \
    else Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
LOCALE_DIR = ROOT / "locales"
LUT_DIR = ROOT / "luts"
LUT_ALIASES = ROOT / "lut-aliases.json"               # 可选：旧编辑记录里的 LUT 路径对应表

CONFIG_DIR = Path.home() / ".photo-cull"
SETTINGS = CONFIG_DIR / "settings.json"
LANG_FILE = CONFIG_DIR / "lang.json"
USER_LUT_DIR = CONFIG_DIR / "luts"
THUMB_DIR = CONFIG_DIR / "thumbs"
LOG_DIR = CONFIG_DIR / "logs"
WEBVIEW_DIR = CONFIG_DIR / "webview"

REPORT_DIR = "photo-cull-report"                      # 照片文件夹里的结果文件夹名
