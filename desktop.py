#!/usr/bin/env python3
"""照片工具 · 桌面应用入口（Mac 应用「照片工具.app」就是从这里启动的）。

一个原生窗口里同时放着「照片筛选」和「照片编辑」，顶部直接切换，不需要终端、不需要先双击启动文件。
窗口用 macOS 自带的 WebKit（通过 pywebview），界面和浏览器里的完全一样（web/ 目录）。
没装 pywebview 时退回到默认浏览器里打开。

    python3 desktop.py              # 打开窗口
    python3 desktop.py --selftest   # 自检：启动服务、检查依赖和资源，然后退出（打包脚本用它验证 .app）
"""
from __future__ import annotations

import json
import os
import sys
import time
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from photo_cull.paths import LOG_DIR, WEBVIEW_DIR  # noqa: E402


def _load_cv2_frozen():
    """打包后的应用里直接加载 OpenCV 的二进制模块。

    OpenCV 的 cv2/__init__.py 是一个「加载器」：它改 sys.path 后再 import 一次 cv2 去找二进制模块。
    在 .app 里 Frameworks 目录排在 sys.path 前面，第二次 import 又找回 cv2 这个包本身，于是报
    「recursion is detected during loading of cv2 binary extensions」。这里跳过加载器，直接载入
    cv2*.so，并补上程序用到的 cv2.data.haarcascades（人脸检测模型的位置）。"""
    if not getattr(sys, "frozen", False) or "cv2" in sys.modules:
        return
    base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent)) / "cv2"
    so = next(iter(sorted(base.glob("cv2*.so"))), None)
    if so is None:
        return
    import importlib.machinery
    import importlib.util
    import types
    try:
        loader = importlib.machinery.ExtensionFileLoader("cv2", str(so))
        spec = importlib.util.spec_from_file_location("cv2", str(so), loader=loader)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["cv2"] = mod
        loader.exec_module(mod)
    except Exception as e:                           # noqa: BLE001
        sys.modules.pop("cv2", None)
        print("cv2 直接加载失败：", e, file=sys.stderr)
        return
    data = types.ModuleType("cv2.data")
    data.haarcascades = str((base / "data").resolve()) + os.sep
    mod.data = data
    sys.modules["cv2.data"] = data


def _log_to_file():
    """打包后的应用没有终端：把输出写到 ~/.photo-cull/logs/app.log，出问题时可以发回来看。"""
    if not getattr(sys, "frozen", False) or os.environ.get("PHOTO_CULL_CONSOLE"):
        return
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    f = LOG_DIR / "app.log"
    if f.exists() and f.stat().st_size > 2_000_000:
        f.replace(LOG_DIR / "app.old.log")
    fh = open(f, "a", encoding="utf-8", buffering=1)
    fh.write(f"\n── {time.strftime('%Y-%m-%d %H:%M:%S')} 启动 ──\n")
    sys.stdout = sys.stderr = fh


def selftest() -> int:
    """检查打包结果：依赖能否导入、资源是否齐全、两个服务能否启动、页面能否生成。"""
    import urllib.request
    ok = True

    def report(name, good, info=""):
        nonlocal ok
        print(f"{'✓' if good else '✗'} {name} {info}", flush=True)
        ok = ok and good
    for mod in ("numpy", "PIL", "cv2", "rawpy", "exifread", "pillow_heif", "send2trash", "anthropic", "openai", "webview"):
        try:
            m = __import__(mod)
            report(mod, True, getattr(m, "__version__", ""))
        except Exception as e:                       # noqa: BLE001
            report(mod, False, f"{type(e).__name__}: {e}")
    from photo_cull import i18n
    from photo_cull.paths import LUT_DIR, WEB
    from photo_cull.server import apps, runtime
    n = len(list(LUT_DIR.rglob("*.cube")))
    try:
        from photo_cull.cull.analysis import _cascade
        c = _cascade("haarcascade_frontalface_default.xml")
        report("人脸检测模型", c is not None, getattr(__import__("cv2").data, "haarcascades", ""))
    except Exception as e:                           # noqa: BLE001
        report("人脸检测模型", False, f"{type(e).__name__}: {e}")
    report("内置 LUT", n >= 39, f"{n} 个（{LUT_DIR}）")
    report("语言包", all((i18n.LOCALE_DIR / f"{k}.json").is_file() for k in i18n.LANGS), str(i18n.LOCALE_DIR))
    report("界面文件", (WEB / "shell" / "index.html").is_file(), str(WEB))
    url = runtime.start_all()
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        html_ = op.open(url, timeout=5).read().decode("utf-8")
        report("一体窗口页面", "f-cull" in html_ and "f-edit" in html_)
        for app in ("cull", "edit"):
            d = apps.LOCAL[app]
            ping = json.loads(op.open(f"http://127.0.0.1:{d['port']}/ping", timeout=5).read())
            page = op.open(f"http://127.0.0.1:{d['port']}/?t={d['token']}&shell=1", timeout=5).read().decode("utf-8")
            report(f"{app} 服务", ping.get("app") == app and "window.I18N" in page)
    except Exception as e:                           # noqa: BLE001
        report("服务", False, f"{type(e).__name__}: {e}")
    runtime.stop_all()
    print("自检通过" if ok else "自检有问题", flush=True)
    return 0 if ok else 1


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    _load_cv2_frozen()
    if "--selftest" in argv:
        return selftest()
    _log_to_file()
    from photo_cull.i18n import t
    from photo_cull.server import runtime
    url = runtime.running_shell() or runtime.start_all()      # 已经有一份在跑（比如用启动文件开的）就直接用它
    print("shell:", url, flush=True)
    try:
        import webview
    except ImportError:
        print("pywebview 不可用，改用浏览器打开", flush=True)
        webbrowser.open(url)
        print(t("server.close_hint"), flush=True)
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            return 0
    webview.create_window(t("common.app.suite"), url, width=1440, height=920, min_size=(1100, 700), text_select=True)
    storage = WEBVIEW_DIR       # 记住界面里的小设置（缩略图大小、面板折叠等）
    storage.mkdir(parents=True, exist_ok=True)
    try:
        webview.start(private_mode=False, storage_path=str(storage), debug=bool(os.environ.get("PHOTO_CULL_DEBUG")))
    except TypeError:                                  # 旧版 pywebview 没有这些参数
        webview.start()
    runtime.stop_all()
    return 0


if __name__ == "__main__":
    sys.exit(main())
