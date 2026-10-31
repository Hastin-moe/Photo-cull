from __future__ import annotations

from ..paths import WEB

import json
import os
import sys
from pathlib import Path
from urllib.parse import quote  # noqa: E402

from .. import i18n
from ..i18n import t
from ..version import VERSION
from .apps import _EXT, APP_NAMES, LOCAL, TOKEN


STATIC_TYPES = {".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                ".svg": "image/svg+xml", ".png": "image/png", ".woff2": "font/woff2", ".json": "application/json"}
LAUNCHERS = {"cull": "启动筛选" + _EXT, "edit": "启动编辑" + _EXT}      # 启动文件名本身不随语言变化
_PLAT = "win" if os.name == "nt" else "mac" if sys.platform == "darwin" else "other"


def app_name(app: str) -> str:
    return t("common.app." + app)


def lang_bundle(prefixes=None, lang=None) -> dict:
    """网页用的语言包，补上与系统有关的说法（访达／资源管理器、废纸篓／回收站）；prefixes 限定分组（报告页用）。"""
    b = i18n.bundle(None, lang)
    d = dict(b["dict"])
    d["common.file_manager"] = d.get("common.file_manager_" + _PLAT, "")
    d["common.trash"] = d.get("common.trash_" + ("win" if _PLAT == "win" else "mac"), "")
    if prefixes:
        d = {k: v for k, v in d.items() if k.split(".", 1)[0] in prefixes}
    b["dict"] = d
    return b


def render_page(app: str) -> bytes:
    """web/<app>/index.html ＋ 版本号、语言、语言包。每次请求都读文件：改界面不用重启程序。"""
    html_ = (WEB / app / "index.html").read_text(encoding="utf-8")
    data = json.dumps(lang_bundle(), ensure_ascii=False).replace("</", "<\\/")
    return (html_.replace("__VER__", VERSION).replace("__LANG__", i18n.html_lang())
            .replace("__I18N__", data)).encode("utf-8")
EDIT_GET = {"/api/edit/thumb", "/api/edit/state", "/api/edit/export_status"}
CULL_GET = {"/api/settings", "/api/status"}


def help_page(app: str) -> bytes:
    import html as _h
    name, cmd = app_name(app), LAUNCHERS[app]
    page = (WEB / "help.html").read_text(encoding="utf-8")
    for k, v in {"__LANG__": i18n.html_lang(), "__TITLE__": t("server.peer.title", name=name),
                 "__HEAD__": t("server.peer.head", name=name), "__BODY__": t("server.peer.body", cmd=f"<code>{_h.escape(cmd)}</code>"),
                 "__RETRY__": t("server.peer.retry")}.items():
        page = page.replace(k, v)
    return page.encode("utf-8")


def render_shell(start: str = "cull", path: str = "") -> bytes | None:
    """web/shell/index.html：两个界面各放一个 iframe，切换时只换显示，不重新加载。"""
    if set(LOCAL) != set(APP_NAMES):
        return None
    base = lambda app: f"http://127.0.0.1:{LOCAL[app]['port']}/?t={quote(TOKEN)}&shell=1"
    edit_url = base("edit") + (f"&path={quote(path)}" if path else "")
    page = (WEB / "shell" / "index.html").read_text(encoding="utf-8")
    data = json.dumps(lang_bundle(("common",)), ensure_ascii=False).replace("</", "<\\/")
    for k, v in {"__VER__": VERSION, "__LANG__": i18n.html_lang(), "__I18N__": data,
                 "__CULL_URL__": base("cull"), "__EDIT_URL__": edit_url,
                 "__START__": start if start in APP_NAMES else "cull"}.items():
        page = page.replace(k, v)
    return page.encode("utf-8")


def shell_url(start: str = "cull") -> str:
    return f"http://127.0.0.1:{LOCAL['cull']['port']}/shell?t={quote(TOKEN)}&start={start}"
