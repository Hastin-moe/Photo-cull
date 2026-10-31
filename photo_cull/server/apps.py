from __future__ import annotations

from ..paths import FROZEN

from ..paths import ROOT

import atexit
import json
import os
import secrets
import subprocess
import sys
from pathlib import Path

from .. import i18n
from ..cull.report import write_report
from .actions import _current
from .jobs import JOB
from .settings import CONFIG_DIR

TOKEN = secrets.token_urlsafe(16)

# ───────────────────────── 两个程序怎么跑 ─────────────────────────
# 一体模式（默认，gui.py --app all，启动文件和 Mac 应用都用它）：同一个进程里起两个本地服务，
#   筛选、编辑各占一个端口；/shell 页面把两个界面放在同一个窗口里，顶部直接切换，状态都保留。
# 单独模式（gui.py --app cull／--app edit）：一个进程只跑一个程序。需要另一个时自动在后台把它启动起来。
# 每个服务把端口和令牌登记到 ~/.photo-cull/apps/<app>.json（仅本人可读），供另一个进程找到它。
APP = "cull"                 # 单独模式下本进程的程序；一体模式下每个服务各自的程序见 server.app
APP_NAMES = ("cull", "edit")
LOCAL: dict = {}             # 本进程里正在跑的服务：app → {"port", "token"}
      # 打包成 Mac 应用（PyInstaller）后运行
_EXT = ".bat" if os.name == "nt" else ".command"


def _registry(app: str) -> Path:
    return CONFIG_DIR / "apps" / f"{app}.json"


def register(port: int, app: str | None = None):
    app = app or APP
    LOCAL[app] = {"port": port, "token": TOKEN, "pid": os.getpid()}
    f = _registry(app)
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps({"port": port, "token": TOKEN, "pid": os.getpid()}), encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(f)

    def bye():
        try:
            if json.loads(f.read_text(encoding="utf-8")).get("pid") == os.getpid():
                f.unlink()
        except Exception:
            pass
    atexit.register(bye)


def peer(app: str) -> dict | None:
    """另一个程序是否在运行：本进程里有就直接用；否则读登记文件，再向它的 /ping 确认（防止端口已被别的程序占用）。"""
    if app in LOCAL:
        return LOCAL[app]
    try:
        d = json.loads(_registry(app).read_text(encoding="utf-8"))
        import urllib.request
        with urllib.request.urlopen(f"http://127.0.0.1:{int(d['port'])}/ping", timeout=0.6) as r:
            if json.loads(r.read().decode("utf-8")).get("app") == app:
                return d
    except Exception:
        pass
    return None


def start_peer(app: str, wait: float = 20.0) -> dict | None:
    """单独模式下需要另一个程序时，在后台把它启动起来（不再要求用户先去双击启动文件）。"""
    if FROZEN or os.environ.get("PHOTO_CULL_NO_AUTOSTART"):
        return None
    env = dict(os.environ, PHOTO_CULL_NO_BROWSER="1")
    env.pop("PHOTO_CULL_PORT", None)
    try:
        subprocess.Popen([sys.executable, "-m", "photo_cull.server", "--app", app], env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                         start_new_session=True, cwd=str(ROOT))
    except OSError:
        return None
    import time
    end = time.time() + wait
    while time.time() < end:
        d = peer(app)
        if d:
            return d
        time.sleep(0.25)
    return None


def set_language(code) -> str:
    """界面切换语言：保存（两个程序共用）；筛选程序里已有结果时，按新语言重新生成报告。"""
    lang = i18n.save_lang(code)
    if "cull" in LOCAL and JOB.result and not JOB.running:
        try:
            with JOB.edit:
                out, photos, meta = _current()
                write_report(photos, out, meta)
        except Exception as e:
            print("report:", e, file=sys.__stderr__)
    return lang
