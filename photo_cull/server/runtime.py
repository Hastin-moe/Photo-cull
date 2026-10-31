from __future__ import annotations

import json
import os
import threading
from http.server import ThreadingHTTPServer
from urllib.parse import quote  # noqa: E402

from .apps import APP_NAMES, peer, register
from .handler import Handler
from .pages import shell_url


def running_shell() -> str | None:
    """已经有一个一体模式的进程在跑：返回它的窗口地址（再次双击启动文件时直接打开它，不再起第二份）。"""
    d = peer("cull")
    if not d or d.get("pid") == os.getpid():
        return None
    try:
        import urllib.request
        with urllib.request.urlopen(f"http://127.0.0.1:{int(d['port'])}/ping", timeout=0.6) as r:
            if not json.loads(r.read().decode("utf-8")).get("shell"):
                return None
    except Exception:
        return None
    return f"http://127.0.0.1:{int(d['port'])}/shell?t={quote(d['token'])}"


_SERVERS: list = []


def start_all() -> str:
    """一体模式：在后台线程里起筛选、编辑两个服务，返回一体窗口的地址。"""
    base = int(os.environ.get("PHOTO_CULL_PORT", "0"))
    for i, app in enumerate(APP_NAMES):
        srv = ThreadingHTTPServer(("127.0.0.1", base + i if base else 0), Handler)
        srv.app = app
        srv.daemon_threads = True
        register(srv.server_address[1], app)
        _SERVERS.append(srv)
        threading.Thread(target=srv.serve_forever, daemon=True, name=f"photo-cull-{app}").start()
    return shell_url()


def stop_all():
    for srv in _SERVERS:
        try:
            srv.shutdown()
        except Exception:
            pass
