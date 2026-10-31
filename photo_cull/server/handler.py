from __future__ import annotations

import json
import mimetypes
import os
import secrets
import subprocess
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse  # noqa: E402

from .. import i18n
from ..cull.ai.providers import PROVIDERS, env_key
from ..cull.state import CANCEL
from ..edit.auto import DEFAULT_METER, meter_list
from ..edit.library import default_library, list_folder, scan_library, thumbnail
from ..edit.logspace import active_spaces
from ..edit.params import normalize_params
from ..edit.presets import describe_style
from ..edit.records import save_edit
from ..edit.refs import USER_LUT_DIR
from ..edit.render import lens_list, vig_levels
from ..edit.session import SESSION
from ..edit.styles import add_user_lut, remove_user_lut
from ..i18n import t
from . import apps as _apps
from .actions import (
    choose_folder,
    load_previous,
    mark_photo,
    organize_now,
    reveal,
    trash_photos,
)
from .apps import APP_NAMES, LOCAL, TOKEN, peer, set_language, start_peer
from .jobs import JOB, run_job
from .pages import (
    CULL_GET,
    EDIT_GET,
    STATIC_TYPES,
    WEB,
    help_page,
    render_page,
    render_shell,
)
from .settings import _remember, load_settings, save_settings

# ───────────────────────── HTTP ─────────────────────────

class Handler(BaseHTTPRequestHandler):
    server_version = "photo-cull"

    @property
    def app(self) -> str:
        return getattr(self.server, "app", _apps.APP)

    def log_message(self, *a):
        pass

    def _send(self, code, body: bytes, ctype="application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _authorized(self):
        return secrets.compare_digest(self.headers.get("X-Token", ""), TOKEN)

    def _goto(self, app: str, query: str):
        """跳到另一个程序（带上 path 等参数）；没运行就显示启动说明。"""
        q = parse_qs(query)
        if not secrets.compare_digest((q.get("t") or [""])[0], TOKEN):
            return self._send(403, b"forbidden")
        d = peer(app) or start_peer(app)
        if not d:
            return self._send(200, help_page(app), "text/html; charset=utf-8")
        extra = "".join(f"&{k}={quote(v[0])}" for k, v in q.items() if k != "t" and v)
        self.send_response(302)
        self.send_header("Location", f"http://127.0.0.1:{int(d['port'])}/?t={quote(d['token'])}{extra}")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/" or (url.path == "/edit" and self.app == "edit"):
            return self._send(200, render_page(self.app), "text/html; charset=utf-8")
        if url.path == "/shell":                                 # 一体窗口：两个界面放在同一页里切换
            q = parse_qs(url.query)
            if not secrets.compare_digest((q.get("t") or [""])[0], TOKEN):
                return self._send(403, b"forbidden")
            page = render_shell((q.get("start") or ["cull"])[0], (q.get("path") or [""])[0])
            if page is None:
                return self._send(404, b"not available")
            return self._send(200, page, "text/html; charset=utf-8")
        if url.path.startswith("/static/"):                     # 界面的 CSS／JS（不含任何个人数据，不需要令牌）
            target = (WEB / unquote(url.path[len("/static/"):])).resolve()
            if WEB.resolve() not in target.parents or not target.is_file() or target.suffix not in STATIC_TYPES:
                return self._send(404, b"not found")
            return self._send(200, target.read_bytes(), STATIC_TYPES[target.suffix])
        if url.path == "/ping":
            return self._json({"app": self.app, "shell": set(LOCAL) == set(APP_NAMES)})
        if url.path.startswith("/open/") or url.path == "/edit":       # /edit：旧版报告里的「编辑」按钮
            target = "edit" if url.path == "/edit" else url.path.split("/")[2]
            if target in APP_NAMES and target != self.app:
                return self._goto(target, url.query)
            return self._send(404, b"not found")
        if (self.app == "cull" and url.path in EDIT_GET) or (self.app == "edit" and (url.path in CULL_GET or url.path.startswith("/out/"))):
            return self._send(404, b"not found")
        if url.path == "/api/edit/thumb":                       # <img> 无法带请求头，令牌放在查询参数里
            q = parse_qs(url.query)
            if not secrets.compare_digest((q.get("t") or [""])[0], TOKEN):
                return self._send(403, b"forbidden")
            try:
                return self._send(200, thumbnail((q.get("p") or [""])[0]), "image/jpeg")
            except Exception:
                return self._send(404, b"no thumb")
        parts = url.path.split("/")
        # /out/<token>/report.html —— 只提供当前报告目录内的文件
        if len(parts) >= 4 and parts[1] == "out" and secrets.compare_digest(parts[2], TOKEN):
            res = JOB.result
            if not res:
                return self._send(404, b"no report")
            base = Path(res["out"]).resolve()
            target = (base / unquote("/".join(parts[3:]))).resolve()
            if base not in target.parents and target != base or not target.is_file():
                return self._send(404, b"not found")
            ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            return self._send(200, target.read_bytes(), ctype)
        if not self._authorized():
            return self._send(403, b"forbidden")
        if url.path == "/api/settings":
            s = load_settings()
            s["env_keys"] = {k: bool(os.environ.get(v["env"]) or os.environ.get(v.get("alt_env", "") or "-"))
                             for k, v in PROVIDERS.items()}
            s["providers"] = {k: {"name": v["name"], "models": [{"id": m, "note": v.get("notes", {}).get(m, "")} for m in v["models"]],
                                  "default": v["default"], "console": v["console"], "env": v["env"], "key_ph": v.get("key_ph", "")}
                              for k, v in PROVIDERS.items()}
            s["provider_order"] = list(PROVIDERS)
            s["lang_saved"] = bool(i18n.saved_lang() or i18n.normalize(os.environ.get("PHOTO_CULL_LANG")))   # 已选过就不再按浏览器语言自动切换
            try:
                import send2trash  # noqa: F401
                s["trash_ok"] = True
            except ImportError:
                s["trash_ok"] = False
            return self._json(s)
        if url.path == "/api/status":
            since = int((url.query.split("since=")[-1] or 0)) if "since=" in url.query else 0
            return self._json(JOB.snapshot(since))
        if url.path == "/api/edit/state":
            s = load_settings()
            # 「筛选结果」按钮：筛选程序最近一次处理的文件夹（两个程序共用设置文件）
            cf_ = s.get("folder") or ""
            if not (cf_ and (Path(cf_).expanduser() / "photo-cull-report" / "results.json").is_file()):
                cf_ = ""
            lib_ = s.get("edit_library") or ""
            # 以前默认用桌面的「预设与LUT」，现在这些 LUT 已经内置；没另选过素材库的，改用内置
            if not lib_ or Path(lib_).expanduser() == Path.home() / "Desktop" / "预设与LUT":
                lib_ = default_library()
            return self._json({"defaults": normalize_params(None), "library": lib_,
                               "folder": s.get("edit_folder", ""), "cull_folder": cf_,
                               "spaces": active_spaces(), "meters": meter_list(),
                               "default_meter": DEFAULT_METER, "lenses": lens_list(),
                               "levels": vig_levels()})
        if url.path == "/api/edit/export_status":
            return self._json(SESSION.export)
        self._send(404, b"not found")

    def do_POST(self):
        if not self._authorized():
            return self._send(403, b"forbidden")
        length = int(self.headers.get("Content-Length") or 0)
        if length > 200 * 1024 * 1024:
            return self._json({"error": t("server.too_large")}, 413)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._json({"error": "bad json"}, 400)
        path = urlparse(self.path).path
        shared = path in ("/api/choose", "/api/quit", "/api/lang")
        if not shared and (self.app == "edit") != path.startswith("/api/edit/"):
            return self._send(404, b"not found")
        try:
            if path == "/api/lang":
                return self._json({"lang": set_language(body.get("lang"))})
            if path == "/api/open_report":                     # Mac 应用的窗口里不能开新标签页：用默认浏览器打开报告
                if not JOB.result:
                    raise ValueError(t("server.no_result"))
                webbrowser.open(f"http://127.0.0.1:{self.server.server_address[1]}/out/{TOKEN}/report.html")
                return self._json({"ok": True})
            if path == "/api/choose":
                prompt = t("server.choose.org" if body.get("what") == "org" else "server.choose.photos")
                return self._json({"folder": choose_folder(body.get("start", ""), prompt)})
            if path == "/api/run":
                if JOB.running:
                    return self._json({"error": t("server.busy")}, 409)
                folder = Path(str(body.get("folder", ""))).expanduser()
                if not folder.is_dir():
                    return self._json({"error": t("server.folder_not_found")}, 400)
                body["folder"] = str(folder)
                prov = body.get("provider", "claude")
                if prov not in PROVIDERS:
                    return self._json({"error": t("server.bad_provider")}, 400)
                if body.get("ai") and not (body.get("key_" + prov) or env_key(prov)):
                    return self._json({"error": t("cull.err.need_key", name=PROVIDERS[prov]["name"])}, 400)
                if body.get("ai") and prov == "custom" and not (str(body.get("base_url_custom") or "").startswith(("http://", "https://"))
                                                               and str(body.get("model_custom") or "").strip()):
                    return self._json({"error": t("cull.err.custom_incomplete")}, 400)
                try:
                    save_settings(body)
                except OSError as e:   # 设置保存失败不影响运行
                    print("设置未保存：", e, file=sys.__stderr__)
                threading.Thread(target=run_job, args=(body,), daemon=True).start()
                return self._json({"ok": True})
            if path == "/api/load":
                if JOB.running:
                    return self._json({"error": t("server.busy")}, 409)
                return self._json({"result": load_previous(str(body.get("folder", "")))})
            if path == "/api/mark":
                if JOB.running:
                    return self._json({"error": t("server.busy_mark")}, 409)
                return self._json(mark_photo(str(body.get("path", "")), body.get("stars")))
            if path == "/api/trash":
                if JOB.running:
                    return self._json({"error": t("server.busy_trash")}, 409)
                paths = body.get("paths")
                if not isinstance(paths, list) or not paths:
                    return self._json({"error": t("server.no_selection")}, 400)
                return self._json(trash_photos([str(x) for x in paths]))
            if path == "/api/organize":
                if JOB.running:
                    return self._json({"error": t("server.busy_org")}, 409)
                return self._json(organize_now(body))
            if path.startswith("/api/edit/"):
                return self._edit_post(path, body)
            if path == "/api/confirm":
                JOB.answer = bool(body.get("yes"))
                JOB.answered.set()
                return self._json({"ok": True})
            if path == "/api/cancel":
                CANCEL.set()
                JOB.answer = False
                JOB.answered.set()
                return self._json({"ok": True})
            if path == "/api/reveal":
                if JOB.result:
                    what = body.get("what")
                    org = JOB.result.get("organized") or {}
                    if what == "org" and org.get("out") and Path(org["out"]).exists():
                        reveal(org["out"])
                    else:
                        reveal(JOB.result["out"] if what == "report" else str(Path(JOB.result["out"]).parent))
                return self._json({"ok": True})
            if path == "/api/quit":
                self._json({"ok": True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
        except (ValueError, RuntimeError) as e:
            return self._json({"error": str(e)}, 400)
        except Exception as e:
            return self._json({"error": f"{type(e).__name__}: {e}"}, 500)
        self._send(404, b"not found")

    def _edit_post(self, path, body):
        S = SESSION
        if path == "/api/edit/list":
            folder = str(body.get("folder", ""))
            items = list_folder(folder)
            _remember(edit_folder=str(Path(folder).expanduser()))
            return self._json({"items": items})
        if path == "/api/edit/open":
            return self._json(S.open(str(body.get("path", ""))))
        if path == "/api/edit/render":
            data, meta = S.render_jpeg(body.get("params") or {}, "fast" if body.get("quality") == "fast" else "full",
                                       int(body.get("seq") or 0), str(body.get("client") or "")[:64],
                                       int(body.get("side") or 0))
            if data is None:
                self.send_response(204)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Render-Ms", str(meta.get("ms", 0)))
            if meta.get("notes"):
                self.send_header("X-Notes", quote(t("common.sep").join(meta["notes"])))
            self.end_headers()
            self.wfile.write(data)
            return
        if path == "/api/edit/auto":
            return self._json(S.auto(body.get("params") or {}, str(body.get("style") or DEFAULT_METER)))
        if path == "/api/edit/save":
            p = str(body.get("path", ""))
            if not p or p != S.path:
                raise ValueError(t("server.only_current_save"))
            return self._json({"file": save_edit(p, body.get("params") or {})})
        if path == "/api/edit/lut_add":
            files = body.get("files") or []
            if not isinstance(files, list) or not files:
                raise ValueError(t("server.no_files"))
            added, failed = [], []
            for f in files[:50]:
                try:
                    added.append(add_user_lut(str(f.get("name", "")), str(f.get("text", ""))))
                except (ValueError, OSError) as e:
                    failed.append({"name": str(f.get("name", "")), "error": str(e)})
            return self._json({"added": added, "failed": failed, "folder": str(USER_LUT_DIR)})
        if path == "/api/edit/lut_remove":
            return self._json({"removed": remove_user_lut(str(body.get("path", "")))})
        if path == "/api/edit/library":
            root = str(body.get("root", ""))
            res = scan_library(root)
            _remember(edit_library=res["root"])
            return self._json(res)
        if path == "/api/edit/style":
            d = describe_style(str(body.get("path", "")), body.get("root") or None)
            mode = (S.info or {}).get("mode")
            if d.get("look") and mode:
                extra = ""
                if mode == "raw" and not d.get("for_raw", True):
                    extra = t("edit.warn.look_jpeg_only")
                elif mode != "raw" and not d.get("for_jpeg", True):
                    extra = t("edit.warn.look_raw_only")
                if extra:
                    d["warning"] = (d["warning"] + t("common.sep") if d.get("warning") else "") + extra
            return self._json(d)
        if path == "/api/edit/export":
            p = str(body.get("path", ""))
            if not p or p != S.path:
                raise ValueError(t("server.only_current_export"))
            fmt = "tiff" if body.get("fmt") == "tiff" else "jpeg"
            st = S.start_export(p, body.get("params") or {}, body.get("out_dir") or None, fmt,
                                int(body.get("quality") or 95), int(body.get("long_edge") or 0))
            return self._json(st)
        if path == "/api/edit/reveal":
            target = str(body.get("path", ""))
            if target and Path(target).exists():
                if sys.platform == "darwin":
                    subprocess.run(["open", "-R", target])
                elif os.name == "nt":
                    subprocess.run(["explorer", "/select," + str(Path(target))])    # 打开文件夹并选中这个文件
                else:
                    reveal(str(Path(target).parent))
            return self._json({"ok": True})
        return self._send(404, b"not found")
