from __future__ import annotations

import os
import sys
import threading
import webbrowser
from http.server import ThreadingHTTPServer

from .. import i18n
from ..i18n import t
from . import apps as _apps
from .apps import APP_NAMES, TOKEN, register
from .handler import Handler
from .pages import app_name
from .runtime import running_shell, start_all


def main(argv=None):
    import argparse
    import signal
    import time
    ap = argparse.ArgumentParser(prog="gui.py", description="Photo Cull / Photo Edit")
    ap.add_argument("--app", choices=list(APP_NAMES) + ["all"], default="all",
                    help="all = both in one window (default); cull / edit = run only one")
    ap.add_argument("--start", choices=list(APP_NAMES), default="cull", help="with --app all: which page to show first")
    ap.add_argument("--lang", choices=list(i18n.LANGS), help="interface language (default: saved choice or system language)")
    a = ap.parse_args(argv)
    if a.lang:
        i18n.save_lang(a.lang)
    for sig in (signal.SIGTERM, getattr(signal, "SIGHUP", None)):   # 关掉终端窗口时也清理登记
        if sig is not None:
            signal.signal(sig, lambda *_: sys.exit(0))
    browser = not os.environ.get("PHOTO_CULL_NO_BROWSER")
    if a.app == "all":
        existing = running_shell()
        if existing:                                   # 已经开着：直接打开那个窗口
            url = existing + f"&start={a.start}"
            print(t("server.already_running"), url, flush=True)
            if browser:
                webbrowser.open(url)
            return
        url = start_all().replace("start=cull", f"start={a.start}")
        print(t("server.started", name=t("common.app.suite")), url, flush=True)
        print(t("server.close_hint"), flush=True)
        if browser:
            threading.Timer(0.6, lambda: webbrowser.open(url)).start()
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
        return
    _apps.APP = a.app
    port = int(os.environ.get("PHOTO_CULL_PORT", "0"))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.app = _apps.APP
    register(server.server_address[1])
    url = f"http://127.0.0.1:{server.server_address[1]}/?t={TOKEN}"
    print(t("server.started", name=app_name(_apps.APP)), url, flush=True)
    print(t("server.close_hint"), flush=True)
    if browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()
