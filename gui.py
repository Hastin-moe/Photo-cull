#!/usr/bin/env python3
"""照片筛选工具 · 图形界面

在本机启动一个只监听 127.0.0.1 的小服务器，并用浏览器打开界面。
分析、细评、写 XMP 全部调用同目录下的 cull.py。

前后端分离：界面是 web/ 里的静态文件（HTML／CSS／JS），这里只负责提供页面和 /api 接口。
界面文字在 locales/*.json，页面打开时把当前语言的语言包注入到 window.I18N。
"""
from __future__ import annotations

import atexit
import contextlib
import io
import json
import mimetypes
import os
import secrets
import subprocess
import sys
import threading
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cull  # noqa: E402
import editor  # noqa: E402
import i18n  # noqa: E402
from i18n import t  # noqa: E402
from urllib.parse import parse_qs, quote  # noqa: E402

CONFIG_DIR = Path.home() / ".photo-cull"
CONFIG = CONFIG_DIR / "settings.json"
TOKEN = secrets.token_urlsafe(16)
PROVIDERS = cull.PROVIDERS
WEB = Path(__file__).resolve().parent / "web"
STATIC_TYPES = {".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                ".svg": "image/svg+xml", ".png": "image/png", ".woff2": "font/woff2", ".json": "application/json"}

DEFAULTS = {
    "folder": "", "recursive": False, "ai": False, "provider": "claude", "ai_alts": False,
    **{"model_" + k: v["default"] for k, v in PROVIDERS.items()},
    **{"key_" + k: "" for k in PROVIDERS}, "remember_key": False, "base_url_custom": "",
    "edit_folder": "", "edit_library": "",
    "xmp": True, "jpeg_embed": True, "xmp_all": False, "dry_run": True,
    "org": False, "org_dir": "", "org_result": True, "org_format": True, "org_rename": True, "org_move": False,
    "burst_gap": 15.0, "scene_gap": 60.0, "similarity": 0.6, "blur_warn": 0.58, "blur_reject": 0.75,
    "clip_high": 0.04, "clip_low": 0.30, "workers": 4,
}
KEYS = tuple("key_" + k for k in PROVIDERS)
TUNING = {"burst_gap", "scene_gap", "similarity", "blur_warn", "blur_reject", "clip_high", "clip_low"}
SETTINGS_VERSION = 3


def load_settings() -> dict:
    s = dict(DEFAULTS)
    try:
        saved = json.loads(CONFIG.read_text(encoding="utf-8"))
        if saved.get("settings_version", 0) < 2:          # 旧版本的阈值算法不同，恢复默认
            saved = {k: v for k, v in saved.items() if k not in TUNING}
        if saved.get("api_key") and not saved.get("key_claude"):   # 1.0/1.1 只有 Claude 一个 Key
            saved["key_claude"] = saved["api_key"]
        if saved.get("model", "").startswith("claude"):
            saved.setdefault("model_claude", saved["model"])
        s.update({k: v for k, v in saved.items() if k in DEFAULTS})
    except Exception:
        pass
    return s


def save_settings(s: dict):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    old = load_settings()
    data = {k: s.get(k, old.get(k, v)) for k, v in DEFAULTS.items()}
    data["settings_version"] = SETTINGS_VERSION
    if not data.get("remember_key"):
        for k in KEYS:
            data[k] = ""
    tmp = CONFIG.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(CONFIG)


# ───────────────────────── 任务状态 ─────────────────────────

class LogWriter(io.TextIOBase):
    def __init__(self, job):
        self.job, self.buf = job, ""

    def write(self, text):
        self.buf += text
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            if line.strip():
                self.job.log(line)
        return len(text)


class Job:
    def __init__(self):
        self.lock = threading.Lock()
        self.edit = threading.Lock()    # 标记／删除操作串行执行
        self.reset()

    def reset(self):
        self.running = False
        self.lines = []
        self.stage, self.done, self.total = "idle", 0, 0
        self.result, self.error = None, None
        self.pending = None
        self.answer = None
        self.answered = threading.Event()

    def log(self, line):
        with self.lock:
            self.lines.append(line)

    def snapshot(self, since: int) -> dict:
        with self.lock:
            return {"running": self.running, "stage": self.stage, "done": self.done, "total": self.total,
                    "lines": self.lines[since:], "next": len(self.lines), "result": self.result,
                    "error": self.error, "pending": self.pending}

    # 回调
    def progress(self, stage, done, total):
        with self.lock:
            self.stage, self.done, self.total = stage, done, total

    def confirm(self, count, tokens_in, tokens_out, model):
        with self.lock:
            self.pending = {"count": count, "tokens_in": tokens_in, "tokens_out": tokens_out, "model": model}
        self.answered.clear()
        while not self.answered.wait(0.3):
            if cull.CANCEL.is_set():
                break
        with self.lock:
            self.pending = None
        return bool(self.answer)


JOB = Job()

# ───────────────────────── 两个独立程序 ─────────────────────────
# 筛选、编辑各自用一个启动文件开成独立进程（gui.py --app cull／--app edit），互不阻塞。
# 启动时把自己的端口和令牌登记到 ~/.photo-cull/apps/<app>.json（仅本人可读），
# 这样从报告点「编辑」时能直接跳到正在运行的编辑程序；没在运行就提示去启动。
APP = "cull"
APP_NAMES = ("cull", "edit")
_EXT = ".bat" if os.name == "nt" else ".command"
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
    return (html_.replace("__VER__", cull.VERSION).replace("__LANG__", i18n.html_lang())
            .replace("__I18N__", data)).encode("utf-8")
EDIT_GET = {"/api/edit/thumb", "/api/edit/state", "/api/edit/export_status"}
CULL_GET = {"/api/settings", "/api/status"}


def _registry(app: str) -> Path:
    return CONFIG_DIR / "apps" / f"{app}.json"


def register(port: int):
    f = _registry(APP)
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
    """另一个程序是否在运行：读登记文件，再向它的 /ping 确认（防止端口已被别的程序占用）。"""
    try:
        d = json.loads(_registry(app).read_text(encoding="utf-8"))
        import urllib.request
        with urllib.request.urlopen(f"http://127.0.0.1:{int(d['port'])}/ping", timeout=0.6) as r:
            if json.loads(r.read().decode("utf-8")).get("app") == app:
                return d
    except Exception:
        pass
    return None


def help_page(app: str) -> bytes:
    import html as _h
    name, cmd = app_name(app), LAUNCHERS[app]
    page = (WEB / "help.html").read_text(encoding="utf-8")
    for k, v in {"__LANG__": i18n.html_lang(), "__TITLE__": t("server.peer.title", name=name),
                 "__HEAD__": t("server.peer.head", name=name), "__BODY__": t("server.peer.body", cmd=f"<code>{_h.escape(cmd)}</code>"),
                 "__RETRY__": t("server.peer.retry")}.items():
        page = page.replace(k, v)
    return page.encode("utf-8")


def build_argv(o: dict) -> list[str]:
    argv = [o["folder"]]          # 语言不用传：同一进程里 i18n.current() 就是界面当前的语言
    if o.get("recursive"): argv.append("-r")
    if o.get("ai"):
        prov = o.get("provider") if o.get("provider") in PROVIDERS else "claude"
        argv += ["--ai", "--provider", prov, "--model", o.get("model_" + prov) or PROVIDERS[prov]["default"] or ""]
        if prov == "custom":
            argv += ["--base-url", str(o.get("base_url_custom") or "")]
        if o.get("ai_alts"): argv.append("--ai-alts")
    if not o.get("xmp"): argv.append("--no-xmp")
    if not o.get("jpeg_embed", True): argv.append("--no-jpeg-embed")
    if o.get("xmp_all"): argv.append("--xmp-all")
    if o.get("dry_run"): argv.append("--dry-run")
    if o.get("org"):
        argv.append("--organize=" + str(o.get("org_dir") or "").strip())
        if o.get("org_result", True): argv.append("--by-result")
        if o.get("org_format", True): argv.append("--by-format")
        if o.get("org_rename", True): argv.append("--rename")
        if o.get("org_move"): argv.append("--move")
    for key, flag in [("burst_gap", "--burst-gap"), ("scene_gap", "--scene-gap"), ("similarity", "--similarity"),
                      ("blur_warn", "--blur-warn"), ("blur_reject", "--blur-reject"),
                      ("clip_high", "--clip-high"), ("clip_low", "--clip-low"), ("workers", "--workers")]:
        argv += [flag, str(o.get(key, DEFAULTS[key]))]
    return argv


def run_job(options: dict):
    JOB.reset()
    JOB.running = True
    cull.CANCEL.clear()
    cull.PROGRESS = JOB.progress
    prov = options.get("provider", "claude")
    cull.API_KEYS = {prov: options["key_" + prov]} if options.get("ai") and options.get("key_" + prov) else {}
    writer = LogWriter(JOB)
    try:
        with contextlib.redirect_stdout(writer), contextlib.redirect_stderr(writer):
            JOB.result = cull.main(build_argv(options), confirm=JOB.confirm)
    except cull.Cancelled:
        JOB.error = t("server.cancelled")
    except SystemExit as e:
        JOB.error = str(e.code) if e.code not in (None, 0) else None
    except Exception as e:
        JOB.error = f"{type(e).__name__}: {e}"
        JOB.log(traceback.format_exc())
    finally:
        JOB.running = False
        cull.PROGRESS = None
        cull.API_KEYS = {}


# ───────────────────────── 报告里的标记与删除 ─────────────────────────

def _current():
    if not JOB.result:
        raise RuntimeError(t("server.no_result"))
    out = Path(JOB.result["out"])
    photos, meta = cull.load_results(out)
    return out, photos, meta


def mark_photo(path: str, stars: int) -> dict:
    if not isinstance(stars, int) or not -1 <= stars <= 5:
        raise ValueError(t("server.bad_stars"))
    with JOB.edit:
        out, photos, meta = _current()
        p = next((x for x in photos if x.path == path and not x.trashed), None)
        if p is None:
            raise ValueError(t("server.photo_not_found"))
        p.stars, p.label, p.manual = stars, cull.label_for(stars) if stars else "", True
        # 人工调整是明确的操作：即使上次是演练模式也写入，并同步到配对的每个文件
        written = cull.apply_marks(p, False, meta.get("jpeg_embed", True), meta.get("xmp_all", False))
        moved = None
        try:   # 整理过的话，输出文件夹里的这张也换到新星级对应的位置／名字
            st = cull.org_resync(p, photos, meta)
            moved = st and st["files"]
        except Exception as e:
            print("同步整理输出失败：", e, file=sys.__stderr__)
        cull.write_report(photos, out, meta)
        JOB.result = cull.summarize(photos, out, meta)
        return {"photo": cull.asdict(p), "written": written, "organized": moved, "summary": JOB.result}


def trash_photos(paths: list) -> dict:
    with JOB.edit:
        out, photos, meta = _current()
        root = Path(meta.get("src") or out.parent)
        want = set(paths)
        done, files = [], 0
        for p in photos:
            if p.path in want and not p.trashed:
                files += len(cull.trash_photo(p, root))
                try:
                    files += len(cull.org_trash_copies(p, meta))
                except Exception as e:
                    print("删除整理输出里的副本失败：", e, file=sys.__stderr__)
                done.append(p.path)
        cull.write_report(photos, out, meta)
        JOB.result = cull.summarize(photos, out, meta)
        try:
            import send2trash  # noqa: F401
            where = t("common.trash_win" if os.name == "nt" else "common.trash_mac")
        except ImportError:
            where = t("server.trash_fallback", dir=cull.TRASH_DIR)
        return {"trashed": done, "files": files, "where": where, "summary": JOB.result}


def organize_now(o: dict) -> dict:
    """在报告里复核完之后，按当前星级整理。"""
    with JOB.edit:
        out, photos, meta = _current()
        src = Path(meta.get("src") or out.parent)
        target = Path(str(o.get("org_dir") or "").strip() or t("cull.org.default_dir")).expanduser()
        if not target.is_absolute():
            target = src / target
        prev = meta.get("organized") or {}
        dirs = cull.result_dirs(prev) if prev.get("out") and Path(prev["out"]) == target.resolve() else None
        st = cull.organize(photos, target, bool(o.get("org_result", True)), bool(o.get("org_format", True)),
                           bool(o.get("org_rename", True)), bool(o.get("org_move")), dirs=dirs)
        meta["organized"] = st
        cull.write_report(photos, out, meta)
        JOB.result = cull.summarize(photos, out, meta)
        _remember(**{k: o[k] for k in ("org_dir", "org_result", "org_format", "org_rename", "org_move") if k in o})
        return {"organized": JOB.result["organized"], "summary": JOB.result}


def load_previous(folder: str) -> dict:
    out = Path(folder).expanduser() / "photo-cull-report"
    if not (out / "results.json").is_file():
        raise ValueError(t("server.no_prev"))
    photos, meta = cull.load_results(out)
    meta.setdefault("src", str(Path(folder).expanduser()))
    JOB.reset()
    JOB.result = cull.summarize(photos, out, meta)
    return JOB.result


# ───────────────────────── 系统交互 ─────────────────────────

def choose_folder(start: str = "", prompt: str = "") -> str:
    prompt = (prompt or t("server.choose.photos")).replace('"', "'")
    if sys.platform == "darwin":
        script = f'POSIX path of (choose folder with prompt "{prompt}"'
        if start and Path(start).is_dir():
            script += f' default location (POSIX file "{start}")'
        script += ")"
        r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
        return r.stdout.strip().rstrip("/") if r.returncode == 0 else ""
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk(); root.withdraw(); root.attributes("-topmost", True)
        path = filedialog.askdirectory(initialdir=start or str(Path.home()))
        root.destroy()
        return path or ""
    except Exception:
        raise RuntimeError(t("server.choose.unavailable"))


def reveal(path: str):
    if sys.platform == "darwin":
        subprocess.run(["open", path])
    elif os.name == "nt":
        os.startfile(path)  # type: ignore[attr-defined]
    else:
        subprocess.run(["xdg-open", path])


# ───────────────────────── HTTP ─────────────────────────

class Handler(BaseHTTPRequestHandler):
    server_version = "photo-cull"

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
        d = peer(app)
        if not d:
            return self._send(200, help_page(app), "text/html; charset=utf-8")
        extra = "".join(f"&{k}={quote(v[0])}" for k, v in q.items() if k != "t" and v)
        self.send_response(302)
        self.send_header("Location", f"http://127.0.0.1:{int(d['port'])}/?t={quote(d['token'])}{extra}")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/" or (url.path == "/edit" and APP == "edit"):
            return self._send(200, render_page(APP), "text/html; charset=utf-8")
        if url.path.startswith("/static/"):                     # 界面的 CSS／JS（不含任何个人数据，不需要令牌）
            target = (WEB / unquote(url.path[len("/static/"):])).resolve()
            if WEB.resolve() not in target.parents or not target.is_file() or target.suffix not in STATIC_TYPES:
                return self._send(404, b"not found")
            return self._send(200, target.read_bytes(), STATIC_TYPES[target.suffix])
        if url.path == "/ping":
            return self._json({"app": APP})
        if url.path.startswith("/open/") or url.path == "/edit":       # /edit：旧版报告里的「编辑」按钮
            target = "edit" if url.path == "/edit" else url.path.split("/")[2]
            if target in APP_NAMES and target != APP:
                return self._goto(target, url.query)
            return self._send(404, b"not found")
        if (APP == "cull" and url.path in EDIT_GET) or (APP == "edit" and (url.path in CULL_GET or url.path.startswith("/out/"))):
            return self._send(404, b"not found")
        if url.path == "/api/edit/thumb":                       # <img> 无法带请求头，令牌放在查询参数里
            q = parse_qs(url.query)
            if not secrets.compare_digest((q.get("t") or [""])[0], TOKEN):
                return self._send(403, b"forbidden")
            try:
                return self._send(200, editor.thumbnail((q.get("p") or [""])[0]), "image/jpeg")
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
                lib_ = editor.default_library()
            return self._json({"defaults": editor.normalize_params(None), "library": lib_,
                               "folder": s.get("edit_folder", ""), "cull_folder": cf_,
                               "spaces": editor.active_spaces(), "meters": editor.meter_list(),
                               "default_meter": editor.DEFAULT_METER, "lenses": editor.lens_list(),
                               "levels": editor.vig_levels()})
        if url.path == "/api/edit/export_status":
            return self._json(editor.SESSION.export)
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
        if not shared and (APP == "edit") != path.startswith("/api/edit/"):
            return self._send(404, b"not found")
        try:
            if path == "/api/lang":
                return self._json({"lang": set_language(body.get("lang"))})
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
                if body.get("ai") and not (body.get("key_" + prov) or cull.env_key(prov)):
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
                cull.CANCEL.set()
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
        S = editor.SESSION
        if path == "/api/edit/list":
            folder = str(body.get("folder", ""))
            items = editor.list_folder(folder)
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
            return self._json(S.auto(body.get("params") or {}, str(body.get("style") or editor.DEFAULT_METER)))
        if path == "/api/edit/save":
            p = str(body.get("path", ""))
            if not p or p != S.path:
                raise ValueError(t("server.only_current_save"))
            return self._json({"file": editor.save_edit(p, body.get("params") or {})})
        if path == "/api/edit/lut_add":
            files = body.get("files") or []
            if not isinstance(files, list) or not files:
                raise ValueError(t("server.no_files"))
            added, failed = [], []
            for f in files[:50]:
                try:
                    added.append(editor.add_user_lut(str(f.get("name", "")), str(f.get("text", ""))))
                except (ValueError, OSError) as e:
                    failed.append({"name": str(f.get("name", "")), "error": str(e)})
            return self._json({"added": added, "failed": failed, "folder": str(editor.USER_LUT_DIR)})
        if path == "/api/edit/lut_remove":
            return self._json({"removed": editor.remove_user_lut(str(body.get("path", "")))})
        if path == "/api/edit/library":
            root = str(body.get("root", ""))
            res = editor.scan_library(root)
            _remember(edit_library=res["root"])
            return self._json(res)
        if path == "/api/edit/style":
            d = editor.describe_style(str(body.get("path", "")), body.get("root") or None)
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


def set_language(code) -> str:
    """界面切换语言：保存（两个程序共用）；筛选程序里已有结果时，按新语言重新生成报告。"""
    lang = i18n.save_lang(code)
    if APP == "cull" and JOB.result and not JOB.running:
        try:
            with JOB.edit:
                out, photos, meta = _current()
                cull.write_report(photos, out, meta)
        except Exception as e:
            print("report:", e, file=sys.__stderr__)
    return lang


def _remember(**kw):
    try:
        s = load_settings()
        s.update(kw)
        save_settings(s)
    except OSError:
        pass


def main(argv=None):
    global APP
    import argparse
    import signal
    ap = argparse.ArgumentParser(prog="gui.py", description="Photo Cull / Photo Edit")
    ap.add_argument("--app", choices=list(APP_NAMES), default="cull", help="cull = Photo Cull, edit = Photo Edit")
    ap.add_argument("--lang", choices=list(i18n.LANGS), help="interface language (default: saved choice or system language)")
    a = ap.parse_args(argv)
    APP = a.app
    if a.lang:
        i18n.save_lang(a.lang)
    port = int(os.environ.get("PHOTO_CULL_PORT", "0"))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    register(server.server_address[1])
    for sig in (signal.SIGTERM, getattr(signal, "SIGHUP", None)):   # 关掉终端窗口时也清理登记
        if sig is not None:
            signal.signal(sig, lambda *_: sys.exit(0))
    url = f"http://127.0.0.1:{server.server_address[1]}/?t={TOKEN}"
    print(t("server.started", name=app_name(APP)), url, flush=True)
    print(t("server.close_hint"), flush=True)
    if not os.environ.get("PHOTO_CULL_NO_BROWSER"):
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
