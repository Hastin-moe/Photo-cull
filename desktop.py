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
import threading
import time
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
LOG_DIR = Path.home() / ".photo-cull" / "logs"


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
    import gui
    import editor
    import i18n
    n = len(list(editor.LUT_DIR.rglob("*.cube")))
    report("内置 LUT", n >= 39, f"{n} 个（{editor.LUT_DIR}）")
    report("语言包", all((i18n.LOCALE_DIR / f"{k}.json").is_file() for k in i18n.LANGS), str(i18n.LOCALE_DIR))
    report("界面文件", (gui.WEB / "shell" / "index.html").is_file(), str(gui.WEB))
    url = gui.start_all()
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        html_ = op.open(url, timeout=5).read().decode("utf-8")
        report("一体窗口页面", "f-cull" in html_ and "f-edit" in html_)
        for app in ("cull", "edit"):
            d = gui.LOCAL[app]
            ping = json.loads(op.open(f"http://127.0.0.1:{d['port']}/ping", timeout=5).read())
            page = op.open(f"http://127.0.0.1:{d['port']}/?t={d['token']}&shell=1", timeout=5).read().decode("utf-8")
            report(f"{app} 服务", ping.get("app") == app and "window.I18N" in page)
    except Exception as e:                           # noqa: BLE001
        report("服务", False, f"{type(e).__name__}: {e}")
    gui.stop_all()
    print("自检通过" if ok else "自检有问题", flush=True)
    return 0 if ok else 1


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--selftest" in argv:
        return selftest()
    _log_to_file()
    import gui
    from i18n import t
    url = gui.running_shell() or gui.start_all()      # 已经有一份在跑（比如用启动文件开的）就直接用它
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
    storage = Path.home() / ".photo-cull" / "webview"       # 记住界面里的小设置（缩略图大小、面板折叠等）
    storage.mkdir(parents=True, exist_ok=True)
    try:
        webview.start(private_mode=False, storage_path=str(storage), debug=bool(os.environ.get("PHOTO_CULL_DEBUG")))
    except TypeError:                                  # 旧版 pywebview 没有这些参数
        webview.start()
    gui.stop_all()
    return 0


if __name__ == "__main__":
    sys.exit(main())
