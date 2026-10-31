# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 打包配置：生成「照片工具.app」（macOS，自带 Python 和全部依赖）。
# 不要直接运行它，请用 tools/build_mac_app.py（或双击「打包Mac应用.command」）。
import os
import re
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

ROOT = Path(SPECPATH).resolve().parent
VERSION = re.search(r'^VERSION = "([^"]+)"', (ROOT / "photo_cull" / "version.py").read_text(encoding="utf-8"), re.M).group(1)
SHORT = ".".join((re.findall(r"\d+", VERSION) + ["0", "0"])[:3])       # 1.8-beta → 1.8.0

datas = [(str(ROOT / d), d) for d in ("web", "locales", "luts")]
binaries = []
# cv2 交给 PyInstaller 自带的 hook 处理：手动收集会把 OpenCV 的加载脚本当成数据文件复制进去，运行时报「recursion is detected」
for pkg in ("rawpy", "pillow_heif"):
    binaries += collect_dynamic_libs(pkg)
    datas += collect_data_files(pkg)
datas += collect_data_files("certifi")
# 人脸／闭眼检测用的 Haar 模型（cv2/data/*.xml）：OpenCV 的 hook 不带这些文件，单独加上
import importlib.util
_cv2 = importlib.util.find_spec("cv2")
if _cv2 and _cv2.origin:
    _xml = Path(_cv2.origin).parent / "data"
    datas += [(str(f), "cv2/data") for f in sorted(_xml.glob("*.xml"))]

a = Analysis(
    [str(ROOT / "desktop.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=collect_submodules("photo_cull") + ["webview.platforms.cocoa", "exifread", "send2trash",
                   "send2trash.mac", "pillow_heif", "rawpy", "anthropic", "openai"],
    excludes=["tkinter", "matplotlib", "IPython", "PySide6", "PyQt5", "PyQt6", "pytest", "webview.platforms.qt",
              "webview.platforms.gtk", "webview.platforms.winforms", "webview.platforms.edgechromium"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="PhotoCull", console=False,
          argv_emulation=False, target_arch=None, codesign_identity=None, entitlements_file=None)
coll = COLLECT(exe, a.binaries, a.datas, name="PhotoCull")
app = BUNDLE(
    coll,
    name="照片工具.app",
    icon=str(ROOT / "packaging" / "icon.icns"),
    bundle_identifier="io.github.photo-cull",
    version=SHORT,
    info_plist={
        "CFBundleName": "照片工具",
        "CFBundleDisplayName": "照片工具",
        "CFBundleShortVersionString": SHORT,
        "CFBundleVersion": VERSION,
        "CFBundleDevelopmentRegion": "zh_CN",
        "CFBundleLocalizations": ["zh_CN", "en", "ja", "ko"],
        "LSApplicationCategoryType": "public.app-category.photography",
        "LSMinimumSystemVersion": "11.0",
        "NSHighResolutionCapable": True,
        "NSRequiresAquaSystemAppearance": False,
        "NSHumanReadableCopyright": "photo-cull contributors · MIT License",
    },
)
