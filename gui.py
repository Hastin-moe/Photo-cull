#!/usr/bin/env python3
"""照片筛选工具 · 图形界面

在本机启动一个只监听 127.0.0.1 的小服务器，并用浏览器打开界面。
分析、细评、写 XMP 全部调用同目录下的 cull.py。
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
import editor_ui  # noqa: E402
from urllib.parse import parse_qs, quote  # noqa: E402

CONFIG_DIR = Path.home() / ".photo-cull"
CONFIG = CONFIG_DIR / "settings.json"
TOKEN = secrets.token_urlsafe(16)
PROVIDERS = cull.PROVIDERS

DEFAULTS = {
    "folder": "", "recursive": False, "ai": False, "provider": "claude", "ai_alts": False,
    "model_claude": PROVIDERS["claude"]["default"], "model_openai": PROVIDERS["openai"]["default"],
    "model_grok": PROVIDERS["grok"]["default"], "model_gemini": PROVIDERS["gemini"]["default"],
    "key_claude": "", "key_openai": "", "key_grok": "", "key_gemini": "", "remember_key": False,
    "edit_folder": "", "edit_library": "",
    "xmp": True, "jpeg_embed": True, "xmp_all": False, "dry_run": True,
    "org": False, "org_dir": "", "org_result": True, "org_format": True, "org_rename": True, "org_move": False,
    "burst_gap": 15.0, "scene_gap": 60.0, "similarity": 0.6, "blur_warn": 0.58, "blur_reject": 0.75,
    "clip_high": 0.04, "clip_low": 0.30, "workers": 4,
}
KEYS = ("key_claude", "key_openai", "key_grok", "key_gemini")
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
APP_NAMES = {"cull": "照片筛选", "edit": "照片编辑"}
_EXT = ".bat" if os.name == "nt" else ".command"
LAUNCHERS = {"cull": "启动筛选" + _EXT, "edit": "启动编辑" + _EXT}
FILE_MANAGER = "资源管理器" if os.name == "nt" else "访达"
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
    name, cmd = APP_NAMES[app], LAUNCHERS[app]
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{name}没有运行</title><style>body{{font:15px/1.6 -apple-system,"PingFang SC","Microsoft YaHei UI","Microsoft YaHei",sans-serif;background:#f4f3ef;color:#1c1c1a;display:flex;
align-items:center;justify-content:center;min-height:100vh;margin:0;padding:16px}}@media (prefers-color-scheme:dark){{body{{background:#141413;color:#ecebe6}}}}
.b{{max-width:440px}}h2{{margin:0 0 8px}}code{{background:#8882;padding:1px 6px;border-radius:5px}}button{{font:inherit;margin-top:14px;padding:7px 16px;border-radius:8px;border:1px solid #8886;background:transparent;color:inherit;cursor:pointer}}</style></head>
<body><div class="b"><h2>「{name}」没有在运行</h2><p>请双击「照片筛选工具」文件夹里的 <code>{cmd}</code>，等它在浏览器打开后，回到这里点「重试」。</p>
<button onclick="location.reload()">重试</button></div></body></html>""".encode("utf-8")


def build_argv(o: dict) -> list[str]:
    argv = [o["folder"]]
    if o.get("recursive"): argv.append("-r")
    if o.get("ai"):
        prov = o.get("provider") if o.get("provider") in PROVIDERS else "claude"
        argv += ["--ai", "--provider", prov, "--model", o.get("model_" + prov) or PROVIDERS[prov]["default"]]
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
        JOB.error = "已取消。已完成的细评结果保存在缓存里，下次不会重复收费。"
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
        raise RuntimeError("还没有筛选结果")
    out = Path(JOB.result["out"])
    photos, meta = cull.load_results(out)
    return out, photos, meta


def mark_photo(path: str, stars: int) -> dict:
    if not isinstance(stars, int) or not -1 <= stars <= 5:
        raise ValueError("星级必须是 -1（拒绝）到 5")
    with JOB.edit:
        out, photos, meta = _current()
        p = next((x for x in photos if x.path == path and not x.trashed), None)
        if p is None:
            raise ValueError("找不到这张照片")
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
            where = "废纸篓"
        except ImportError:
            where = f"照片文件夹里的 {cull.TRASH_DIR}"
        return {"trashed": done, "files": files, "where": where, "summary": JOB.result}


def organize_now(o: dict) -> dict:
    """在报告里复核完之后，按当前星级整理。"""
    with JOB.edit:
        out, photos, meta = _current()
        src = Path(meta.get("src") or out.parent)
        target = Path(str(o.get("org_dir") or "").strip() or "整理输出").expanduser()
        if not target.is_absolute():
            target = src / target
        st = cull.organize(photos, target, bool(o.get("org_result", True)), bool(o.get("org_format", True)),
                           bool(o.get("org_rename", True)), bool(o.get("org_move")))
        meta["organized"] = st
        cull.write_report(photos, out, meta)
        JOB.result = cull.summarize(photos, out, meta)
        _remember(**{k: o[k] for k in ("org_dir", "org_result", "org_format", "org_rename", "org_move") if k in o})
        return {"organized": JOB.result["organized"], "summary": JOB.result}


def load_previous(folder: str) -> dict:
    out = Path(folder).expanduser() / "photo-cull-report"
    if not (out / "results.json").is_file():
        raise ValueError("这个文件夹还没有筛选结果，请先运行一次")
    photos, meta = cull.load_results(out)
    meta.setdefault("src", str(Path(folder).expanduser()))
    JOB.reset()
    JOB.result = cull.summarize(photos, out, meta)
    return JOB.result


# ───────────────────────── 系统交互 ─────────────────────────

def choose_folder(start: str = "", prompt: str = "选择要筛选的照片文件夹") -> str:
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
        raise RuntimeError("当前系统无法弹出文件夹选择框，请直接粘贴路径。")


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
        page = editor_ui.PAGE if APP == "edit" else PAGE
        if url.path == "/" or (url.path == "/edit" and APP == "edit"):
            html_ = page.replace("__VER__", cull.VERSION).replace("__FM__", FILE_MANAGER)
            return self._send(200, html_.encode("utf-8"), "text/html; charset=utf-8")
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
            s["providers"] = {k: {"name": v["name"], "models": v["models"], "console": v["console"], "env": v["env"]}
                              for k, v in PROVIDERS.items()}
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
                               "levels": editor.VIG_LEVELS})
        if url.path == "/api/edit/export_status":
            return self._json(editor.SESSION.export)
        self._send(404, b"not found")

    def do_POST(self):
        if not self._authorized():
            return self._send(403, b"forbidden")
        length = int(self.headers.get("Content-Length") or 0)
        if length > 200 * 1024 * 1024:
            return self._json({"error": "请求太大"}, 413)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._json({"error": "bad json"}, 400)
        path = urlparse(self.path).path
        shared = path in ("/api/choose", "/api/quit")
        if not shared and (APP == "edit") != path.startswith("/api/edit/"):
            return self._send(404, b"not found")
        try:
            if path == "/api/choose":
                prompt = "选择整理输出的文件夹" if body.get("what") == "org" else "选择要筛选的照片文件夹"
                return self._json({"folder": choose_folder(body.get("start", ""), prompt)})
            if path == "/api/run":
                if JOB.running:
                    return self._json({"error": "已有任务在运行"}, 409)
                folder = Path(str(body.get("folder", ""))).expanduser()
                if not folder.is_dir():
                    return self._json({"error": "找不到这个文件夹"}, 400)
                body["folder"] = str(folder)
                prov = body.get("provider", "claude")
                if prov not in PROVIDERS:
                    return self._json({"error": "未知的模型提供方"}, 400)
                if body.get("ai") and not (body.get("key_" + prov) or os.environ.get(PROVIDERS[prov]["env"])):
                    return self._json({"error": f"开启 {PROVIDERS[prov]['name']} 细评需要填写 API Key"}, 400)
                try:
                    save_settings(body)
                except OSError as e:   # 设置保存失败不影响运行
                    print("设置未保存：", e, file=sys.__stderr__)
                threading.Thread(target=run_job, args=(body,), daemon=True).start()
                return self._json({"ok": True})
            if path == "/api/load":
                if JOB.running:
                    return self._json({"error": "已有任务在运行"}, 409)
                return self._json({"result": load_previous(str(body.get("folder", "")))})
            if path == "/api/mark":
                if JOB.running:
                    return self._json({"error": "筛选进行中，请稍后再改"}, 409)
                return self._json(mark_photo(str(body.get("path", "")), body.get("stars")))
            if path == "/api/trash":
                if JOB.running:
                    return self._json({"error": "筛选进行中，请稍后再删"}, 409)
                paths = body.get("paths")
                if not isinstance(paths, list) or not paths:
                    return self._json({"error": "没有选择照片"}, 400)
                return self._json(trash_photos([str(x) for x in paths]))
            if path == "/api/organize":
                if JOB.running:
                    return self._json({"error": "筛选进行中，请稍后再整理"}, 409)
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
                self.send_header("X-Notes", quote("；".join(meta["notes"])))
            self.end_headers()
            self.wfile.write(data)
            return
        if path == "/api/edit/auto":
            return self._json(S.auto(body.get("params") or {}, str(body.get("style") or editor.DEFAULT_METER)))
        if path == "/api/edit/save":
            p = str(body.get("path", ""))
            if not p or p != S.path:
                raise ValueError("只能保存当前打开的照片")
            return self._json({"file": editor.save_edit(p, body.get("params") or {})})
        if path == "/api/edit/lut_add":
            files = body.get("files") or []
            if not isinstance(files, list) or not files:
                raise ValueError("没有选择文件")
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
                    extra = "这个外观只为 JPEG 设计（Lightroom 里不能用于 RAW），套在 RAW 上效果可能有偏差"
                elif mode != "raw" and not d.get("for_jpeg", True):
                    extra = "这个外观只为 RAW 设计（Lightroom 里不能用于 JPEG），套在 JPEG 上颜色可能明显偏差；请改用同一套里标注 JPG 的版本"
                if extra:
                    d["warning"] = (d["warning"] + "；" if d.get("warning") else "") + extra
            return self._json(d)
        if path == "/api/edit/export":
            p = str(body.get("path", ""))
            if not p or p != S.path:
                raise ValueError("只能导出当前打开的照片")
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


def _remember(**kw):
    try:
        s = load_settings()
        s.update(kw)
        save_settings(s)
    except OSError:
        pass


PAGE = r"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>照片筛选</title>
<style>
:root{--bg:#f4f3ef;--panel:#fff;--fg:#1c1c1a;--mut:#74726c;--line:#e2e0da;--soft:#efede8;--acc:#1c1c1a;--acc-fg:#fff;
--g:#2f8a4c;--y:#b8860b;--r:#c0392b;--focus:#3b6fd8;--shadow:0 1px 2px #0000000d,0 8px 24px #00000008}
@media (prefers-color-scheme:dark){:root{--bg:#141413;--panel:#1e1e1c;--fg:#ecebe6;--mut:#9b9992;--line:#33322e;--soft:#272724;--acc:#ecebe6;--acc-fg:#141413;--shadow:none}}
*{box-sizing:border-box}html,body{margin:0;height:100%}
body{background:var(--bg);color:var(--fg);font:14px/1.5 -apple-system,BlinkMacSystemFont,"PingFang SC","Helvetica Neue","Microsoft YaHei UI","Microsoft YaHei","Segoe UI",sans-serif;-webkit-font-smoothing:antialiased}
header{display:flex;align-items:center;justify-content:space-between;padding:14px 22px;border-bottom:1px solid var(--line)}
.brand{display:flex;align-items:center;gap:14px}.brand h1{font-size:17px;margin:0;letter-spacing:.02em}.ver{color:var(--mut);font-size:12px}
.tabs{display:flex;gap:4px;background:var(--soft);padding:3px;border-radius:9px}.tabs a{padding:5px 14px;border-radius:7px;color:var(--mut);text-decoration:none;font-weight:600;font-size:13px}
.tabs a.on{background:var(--panel);color:var(--fg);box-shadow:0 1px 2px #0002}
.xlink{font-size:13px;color:var(--mut);text-decoration:none;border:1px solid var(--line);border-radius:7px;padding:4px 10px}.xlink:hover{color:var(--fg);background:var(--soft)}
.pill{font-size:12px;padding:3px 10px;border-radius:999px;background:var(--soft);color:var(--mut)}.pill.run{background:#3b6fd81a;color:var(--focus)}.pill.ok{background:#2f8a4c1a;color:var(--g)}.pill.err{background:#c0392b1a;color:var(--r)}
.app{display:grid;grid-template-columns:360px 1fr;height:calc(100% - 55px)}
aside{border-right:1px solid var(--line);overflow:auto;padding:18px 18px 110px;position:relative}
section.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px;margin-bottom:12px;box-shadow:var(--shadow)}
.ct{font-size:12px;font-weight:600;color:var(--mut);letter-spacing:.06em;margin:0 0 10px}
.folder{display:flex;gap:8px}.folder input{flex:1;min-width:0}
input[type=text],input[type=password],input[type=number],select{font:inherit;color:var(--fg);background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:7px 9px;width:100%}
input:focus,select:focus,button:focus-visible{outline:2px solid var(--focus);outline-offset:1px}
button{font:inherit;cursor:pointer;border-radius:8px;border:1px solid var(--line);background:var(--panel);color:var(--fg);padding:7px 12px;white-space:nowrap}
button:hover{background:var(--soft)}button:disabled{opacity:.45;cursor:default}
.primary{background:var(--acc);color:var(--acc-fg);border-color:var(--acc);font-weight:600}.primary:hover{background:var(--acc);opacity:.88}
.seg{display:grid;grid-template-columns:1fr 1fr;background:var(--soft);border-radius:9px;padding:3px;gap:3px}
.seg.three{grid-template-columns:1fr 1fr 1fr}.seg.four{grid-template-columns:repeat(4,1fr)}.seg.four button{padding:7px 2px}.seg button{border:0;background:transparent;padding:7px 6px;font-size:13px}.seg button.on{background:var(--panel);box-shadow:0 1px 2px #0002;font-weight:600}
.chk{display:flex;align-items:flex-start;gap:9px;padding:6px 0;cursor:pointer}.chk input{margin:3px 0 0;accent-color:var(--acc)}
.chk small,.hint{display:block;color:var(--mut);font-size:12px;line-height:1.4}
.field{margin-top:10px}.field label{display:block;font-size:12px;color:var(--mut);margin-bottom:4px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:10px}
details summary{cursor:pointer;font-size:12px;font-weight:600;color:var(--mut);letter-spacing:.06em;list-style:none}details summary::before{content:"▸ ";}details[open] summary::before{content:"▾ "}
.runbar{position:fixed;bottom:0;left:0;width:360px;padding:14px 18px;background:linear-gradient(transparent,var(--bg) 30%);display:flex;gap:8px}
.runbar .primary{flex:1;padding:11px}
main{overflow:auto;padding:22px;display:flex;flex-direction:column;gap:16px}
.empty{margin:auto;max-width:520px;text-align:center;color:var(--mut)}.empty h2{color:var(--fg);font-size:20px;margin:0 0 8px}
.steps{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:22px;text-align:left}
.steps div{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:12px}.steps b{display:block;color:var(--fg);margin-bottom:2px}
.stages{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}
.stage{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:12px 14px}
.stage .h{display:flex;justify-content:space-between;font-size:13px}.stage .h span{color:var(--mut)}
.stage.active{border-color:var(--focus)}.stage.done .h b::after{content:" ✓";color:var(--g)}.stage.skip{opacity:.45}
.prog{height:6px;border-radius:9px;background:var(--soft);margin-top:10px;overflow:hidden}.prog i{display:block;height:100%;width:0;background:var(--focus);transition:width .3s}
.stage.done .prog i{background:var(--g)}
.log{background:var(--panel);border:1px solid var(--line);border-radius:12px}
.log pre{margin:0;padding:12px 14px;max-height:180px;overflow:auto;font:12px/1.55 ui-monospace,Menlo,Consolas,monospace;color:var(--mut);white-space:pre-wrap}
.stats{display:grid;grid-template-columns:repeat(7,1fr);gap:10px}
.stat{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:12px 14px}.stat b{font-size:24px;display:block;line-height:1.2}.stat span{font-size:12px;color:var(--mut)}
.stat.g b{color:var(--g)}.stat.y b{color:var(--y)}.stat.r b{color:var(--r)}
.actions{display:flex;gap:8px;flex-wrap:wrap;align-items:center}.note{color:var(--mut);font-size:12px}
.err{background:#c0392b14;border:1px solid #c0392b55;color:var(--r);border-radius:12px;padding:12px 14px}
iframe{width:100%;flex:1;min-height:560px;border:1px solid var(--line);border-radius:12px;background:var(--bg)}
.modal{position:fixed;inset:0;background:#0007;display:none;align-items:center;justify-content:center;z-index:10;padding:16px}
.modal.show{display:flex}.dlg{background:var(--panel);border-radius:14px;padding:22px;max-width:420px;width:100%;box-shadow:0 20px 60px #0004}
.dlg h3{margin:0 0 8px;font-size:17px}.dlg p{margin:6px 0;color:var(--mut)}.dlg .big{font-size:28px;font-weight:700;color:var(--fg)}
.dlg .row{display:flex;justify-content:flex-end;gap:8px;margin-top:18px}
.hidden{display:none!important}
@media (max-width:860px){.app{grid-template-columns:1fr;height:auto}aside{border-right:0;padding-bottom:18px}.runbar{position:static;width:auto;padding:0 18px 18px;background:none}
.stats{grid-template-columns:repeat(3,1fr)!important}.stages,.steps{grid-template-columns:1fr}}
</style></head><body>
<header><div class="brand"><h1>照片筛选</h1><span class="ver">photo-cull __VER__</span></div><div class="brand"><a class="xlink" data-href="/open/edit" target="_blank" rel="noopener" title="在新标签页打开照片编辑程序（需要先双击「启动编辑」）">照片编辑 ↗</a><span class="pill" id="pill">就绪</span></div></header>
<div class="app">
<aside>
 <section class="card"><p class="ct">照片文件夹</p>
  <div class="folder"><input type="text" id="folder" placeholder="选择或粘贴文件夹路径" spellcheck="false"><button id="pick">选择…</button></div>
  <label class="chk"><input type="checkbox" id="recursive"><span>包含子文件夹</span></label>
  <p class="hint" style="margin:4px 0 8px">同一文件夹里同名的 RAW（DNG／ARW／RAF…）和 JPEG 会自动配对，一起评分、标记和删除。</p>
  <button id="loadPrev" style="width:100%">载入这个文件夹上次的结果</button>
 </section>
 <section class="card"><p class="ct">筛选方式</p>
  <div class="seg" data-mode><button data-ai="0">仅本地筛选</button><button data-ai="1">本地＋AI 细评</button></div>
  <p class="hint" id="modeHint" style="margin:10px 0 0"></p>
  <div id="aiBox">
   <div class="field"><label>评价模型</label><div class="seg four" id="provSeg"><button data-p="claude">Claude</button><button data-p="openai">ChatGPT</button><button data-p="grok">Grok</button><button data-p="gemini">Gemini</button></div></div>
   <div class="field"><label>模型名称</label><input type="text" id="model" list="modelList" spellcheck="false" autocomplete="off"><datalist id="modelList"></datalist>
    <span class="hint">可从列表选择，也可以直接填写服务商提供的其他模型名称。</span></div>
   <div class="field"><label id="keyLabel">API Key</label><input type="password" id="api_key" autocomplete="off" spellcheck="false">
    <span class="hint" id="keyHint"></span></div>
   <label class="chk"><input type="checkbox" id="remember_key"><span>记住在这台电脑<small>保存在 ~/.photo-cull，仅本人可读</small></span></label>
   <label class="chk"><input type="checkbox" id="ai_alts"><span>连拍备选也细评<small>更全面，但费用更高</small></span></label>
  </div>
 </section>
 <section class="card"><p class="ct">输出</p>
  <label class="chk"><input type="checkbox" id="xmp"><span>写入星级与色标<small>RAW 写 XMP 边车文件，Lightroom Classic／Capture One 可读</small></span></label>
  <label class="chk"><input type="checkbox" id="jpeg_embed"><span>同步写入 JPEG 内嵌 XMP<small>Lightroom 里 JPEG 也能看到星级；只改元数据，写完逐字节核对画面数据不变</small></span></label>
  <label class="chk"><input type="checkbox" id="xmp_all"><span>单独的 JPEG／HEIC 也写边车 XMP<small>给 Capture One 用；Lightroom 不读 JPEG 的边车</small></span></label>
  <label class="chk"><input type="checkbox" id="dry_run"><span>演练模式<small>只生成报告，不写星级、不整理文件。第一次建议开启</small></span></label>
 </section>
 <section class="card"><p class="ct">整理输出</p>
  <label class="chk"><input type="checkbox" id="org"><span>评分后整理到输出文件夹<small>也可以先不勾，在报告里复核完再点「按当前星级整理」</small></span></label>
  <div id="orgBox">
   <div class="field"><label>输出文件夹</label><div class="folder"><input type="text" id="org_dir" placeholder="留空＝照片文件夹/整理输出" spellcheck="false"><button id="pickOrg">选择…</button></div></div>
   <div class="field"><label>方式</label><div class="seg" id="orgMode"><button data-m="0">复制</button><button data-m="1">移动</button></div>
    <span class="hint" id="orgHint" style="margin-top:6px"></span></div>
   <label class="chk"><input type="checkbox" id="org_result"><span>分成 保留／淘汰 两个文件夹<small>淘汰＝拒绝（X）的照片，其余都算保留</small></span></label>
   <label class="chk"><input type="checkbox" id="org_format"><span>每个里面再分 JPEG／RAW</span></label>
   <label class="chk"><input type="checkbox" id="org_rename"><span>重命名为 星级_机型_原文件名<small>只改输出文件夹里的，原文件名不变</small></span></label>
   <p class="hint" id="orgEx" style="margin:6px 0 0;font-family:ui-monospace,Menlo,monospace;word-break:break-all"></p>
  </div>
 </section>
 <section class="card"><details><summary>高级参数</summary>
  <div class="grid2" style="margin-top:12px">
   <div class="field"><label>连拍间隔（秒）</label><input type="number" id="burst_gap" step="1" min="0"></div>
   <div class="field"><label>同场景间隔（秒）</label><input type="number" id="scene_gap" step="5" min="0"></div>
   <div class="field"><label>同场景相似度</label><input type="number" id="similarity" step="0.05" min="0" max="1"></div>
   <div class="field"><label>模糊提示阈值</label><input type="number" id="blur_warn" step="0.01" min="0" max="1"></div>
   <div class="field"><label>模糊淘汰阈值</label><input type="number" id="blur_reject" step="0.01" min="0" max="1"></div>
   <div class="field"><label>高光溢出提示</label><input type="number" id="clip_high" step="0.01" min="0" max="1"></div>
   <div class="field"><label>暗部死黑提示</label><input type="number" id="clip_low" step="0.05" min="0" max="1"></div>
   <div class="field"><label>并行数</label><input type="number" id="workers" step="1" min="1" max="16"></div>
  </div>
  <p class="hint" style="margin-top:10px">清晰照片被误判模糊 → 调高两个模糊阈值；同一场景没分到一组 → 调大「同场景间隔」或调小「同场景相似度」。</p>
 </details></section>
 <div class="runbar"><button class="primary" id="run">开始筛选</button><button id="cancel" class="hidden">取消</button></div>
</aside>
<main id="main">
 <div class="empty" id="empty"><h2>选一个文件夹，开始筛选</h2>
  <div>支持 Leica／松下 DNG、Sony ARW、富士 RAF 等 RAW，以及 JPG／HEIC／PNG。同名 RAW＋JPEG 自动配对。画面数据不会被改动。</div>
  <div class="steps"><div><b>1 · 本地分析</b>对焦、曝光、人脸与闭眼、连拍分组，不花钱</div>
   <div><b>2 · AI 细评</b>可选 Claude／ChatGPT／Grok／Gemini，只评入围照片，调用前先确认用量</div>
   <div><b>3 · 复核与整理</b>在报告里改星级、删除废片，RAW 和 JPEG 同步；可按星级分文件夹、重命名</div></div></div>
 <div id="work" class="hidden" style="display:flex;flex-direction:column;gap:16px;flex:1">
  <div class="stages">
   <div class="stage" id="st-analyze"><div class="h"><b>本地分析</b><span></span></div><div class="prog"><i></i></div></div>
   <div class="stage" id="st-ai"><div class="h"><b id="aiStageName">AI 细评</b><span></span></div><div class="prog"><i></i></div></div>
   <div class="stage" id="st-xmp"><div class="h"><b>写入结果</b><span></span></div><div class="prog"><i></i></div></div>
  </div>
  <div class="err hidden" id="err"></div>
  <div id="done" class="hidden" style="display:flex;flex-direction:column;gap:14px;flex:1">
   <div class="stats" id="stats"></div>
   <div class="actions"><button class="primary" id="openReport">在浏览器中打开报告</button><button id="revealReport">在__FM__中显示报告</button><button id="revealPhotos">打开照片文件夹</button><button id="orgNow">按当前星级整理</button><button id="revealOrg" class="hidden">打开整理输出</button><span class="note" id="doneNote"></span></div>
   <iframe id="report" title="筛选报告"></iframe>
  </div>
  <details class="log" id="logBox"><summary style="padding:10px 14px">运行日志</summary><pre id="log"></pre></details>
 </div>
</main></div>
<div class="modal" id="modal"><div class="dlg"><h3>确认调用 AI 细评</h3>
 <p>将对 <span class="big" id="mCount">0</span> 张入围照片调用 <b id="mModel"></b>。</p>
 <p id="mTokens"></p><p class="hint">已评过的照片会命中缓存，不会重复收费。实际费用以服务商账单为准。</p>
 <div class="row"><button id="mNo">跳过细评</button><button class="primary" id="mYes">继续</button></div></div></div>
<script>
const TOKEN=new URLSearchParams(location.search).get("t")||"";const $=id=>document.getElementById(id);
const api=(p,b)=>fetch(p,{method:b?"POST":"GET",headers:{"X-Token":TOKEN,"Content-Type":"application/json"},body:b?JSON.stringify(b):undefined}).then(async r=>{const j=await r.json().catch(()=>({}));if(!r.ok)throw new Error(j.error||r.statusText);return j});
const F=["folder","recursive","remember_key","ai_alts","xmp","jpeg_embed","xmp_all","dry_run","org","org_dir","org_result","org_format","org_rename","burst_gap","scene_gap","similarity","blur_warn","blur_reject","clip_high","clip_low","workers"];
let S={ai:false,provider:"claude",models:{},keys:{},envKeys:{},P:{},orgMove:false},since=0,timer=null;
const PH={claude:"sk-ant-…",openai:"sk-…",grok:"xai-…",gemini:"AIza…"};
document.querySelectorAll(".xlink").forEach(a=>a.href=a.dataset.href+"?t="+encodeURIComponent(TOKEN));
function setAI(v){S.ai=v;document.querySelectorAll(".seg[data-mode] button").forEach(b=>b.classList.toggle("on",(b.dataset.ai=="1")==v));
 $("aiBox").classList.toggle("hidden",!v);$("modeHint").textContent=v?"本地先淘汰废片和连拍重复帧，只把入围照片缩小后发给所选模型，评价构图、光线、瞬间。":"只做技术筛选，完全在本机运行，不联网、不花钱。"}
function stash(){S.models[S.provider]=$("model").value.trim();S.keys[S.provider]=$("api_key").value.trim()}
function setProv(p,keep){if(!keep)stash();S.provider=p;const info=S.P[p]||{name:p,models:[],console:"",env:""};
 document.querySelectorAll("#provSeg button").forEach(b=>b.classList.toggle("on",b.dataset.p==p));
 $("model").value=S.models[p]||info.models[0]||"";$("modelList").innerHTML=info.models.map(m=>`<option value="${m}">`).join("");
 $("keyLabel").textContent=info.name+" API Key";$("api_key").value=S.keys[p]||"";$("api_key").placeholder=PH[p]||"";
 $("keyHint").textContent=S.envKeys[p]?`已检测到环境变量 ${info.env}，可留空。`:`在 ${info.console} 申请，按量付费，与网页版订阅无关。`}
function setOrgMove(v){S.orgMove=v;document.querySelectorAll("#orgMode button").forEach(b=>b.classList.toggle("on",(b.dataset.m=="1")==v));
 $("orgHint").textContent=v?"照片会从原文件夹搬走。已导入 Lightroom／Capture One 的照片移动后会显示「文件丢失」，需要在软件里重新定位。":"原文件夹保持不变，输出文件夹里是一份副本（需要双倍空间）。再次整理时会更新这份副本，不会重复复制。";syncOrg()}
function syncOrg(){const on=$("org").checked;$("orgBox").style.opacity=on?1:.5;
 const r=$("org_result").checked,f=$("org_format").checked,n=$("org_rename").checked,d=$("org_dir").value.trim()||"整理输出";
 const base=d.replace(/[\\/]+$/,"").split(/[\\/]/).pop()||d,ex=(st,file)=>[base,r?(st=="X"?"淘汰":"保留"):"",f?(/\.(jpe?g|heic|png)$/i.test(file)?"JPEG":"RAW"):"",(n?st+"_ILCE-1M2_":"")+file].filter(Boolean).join("/");
 $("orgEx").textContent="例："+ex("4","DSC01234.ARW")+"\n　　"+ex("X","DSC01235.JPG");$("orgEx").style.whiteSpace="pre-wrap"}
function orgOpts(){return{org_dir:$("org_dir").value.trim(),org_result:$("org_result").checked,org_format:$("org_format").checked,org_rename:$("org_rename").checked,org_move:S.orgMove}}
function collect(){stash();const o={ai:S.ai,provider:S.provider,org_move:S.orgMove};F.forEach(k=>{const e=$(k);o[k]=e.type=="checkbox"?e.checked:e.type=="number"?Number(e.value):e.value.trim()});
 ["claude","openai","grok","gemini"].forEach(p=>{o["model_"+p]=S.models[p]||"";o["key_"+p]=S.keys[p]||""});return o}
function fill(s){F.forEach(k=>{const e=$(k);if(e.type=="checkbox")e.checked=!!s[k];else e.value=s[k]??""});
 S.P=s.providers||{};S.envKeys=s.env_keys||{};["claude","openai","grok","gemini"].forEach(p=>{S.models[p]=s["model_"+p];S.keys[p]=s["key_"+p]||""});
 setAI(!!s.ai);setProv(s.provider||"claude",true);syncXmp();setOrgMove(!!s.org_move)}
function syncXmp(){const on=$("xmp").checked;["jpeg_embed","xmp_all"].forEach(k=>$(k).disabled=!on)}
function pill(t,c){const p=$("pill");p.textContent=t;p.className="pill "+(c||"")}
function stageUI(st){const order=["analyze","ai","xmp","done"],cur=order.indexOf(st.stage);
 [["analyze",0],["ai",1],["xmp",2]].forEach(([k,i])=>{const el=$("st-"+k),bar=el.querySelector("i"),lab=el.querySelector(".h span");
  const skip=k=="ai"&&!S.runAI;el.className="stage"+(skip?" skip":cur>i?" done":cur==i?" active":"");
  let pct=cur>i?100:cur==i&&st.total?st.done/st.total*100:0;bar.style.width=(skip?0:pct)+"%";
  lab.textContent=skip?"未开启":cur>i?"完成":cur==i&&st.total&&k!="xmp"?`${st.done}/${st.total}`:cur==i?"进行中":"等待"})}
function stats(r,reload){const items=[["总数",r.total,""],["RAW+JPEG 配对",r.pairs||0,""],["4★以上",r.top,"g"],["入围",r.candidate,"g"],["连拍备选",r.alt,"y"],["淘汰",r.reject,"r"]];
 if(r.error)items.push(["读取失败",r.error,"r"]);if(r.trashed)items.push(["已删除",r.trashed,""]);
 $("stats").style.gridTemplateColumns=`repeat(${Math.min(items.length,8)},1fr)`;
 $("stats").innerHTML=items.map(([k,v,c])=>`<div class="stat ${c}"><b>${v}</b><span>${k}</span></div>`).join("");
 $("doneNote").textContent=r.dry_run?"演练模式：未批量写入星级。报告里手动改的星级会立即写入。":r.xmp?`已为 ${r.xmp} 张照片同步写入星级。Lightroom 请执行「元数据 → 从文件读取元数据」。`:"未批量写入星级。";
 const g=r.organized;$("revealOrg").classList.toggle("hidden",!(g&&!g.dry_run));
 if(g){const verb=g.mode=="move"?"移动":"复制";$("doneNote").textContent+=g.dry_run?` 演练：本应${verb} ${g.photos} 张到 ${g.out}。`:` 已${verb}整理 ${g.photos} 张（保留 ${g.kept}，淘汰 ${g.rejected}）到 ${g.out}。`+(g.errors&&g.errors.length?` ${g.errors.length} 个文件失败，详见日志。`:"")}
 if(reload!==false)$("report").src=`/out/${TOKEN}/report.html?`+Date.now()}
window.addEventListener("message",e=>{if(e.origin===location.origin&&e.data&&e.data.pc=="summary")stats(e.data.s,false)});
async function poll(){try{const st=await api("/api/status?since="+since);since=st.next;
 if(st.lines.length){const l=$("log");l.textContent+=st.lines.join("\n")+"\n";l.scrollTop=l.scrollHeight}
 stageUI(st);
 if(st.pending){$("mCount").textContent=st.pending.count;$("mModel").textContent=st.pending.model;
  const fm=n=>n>=1e6?(n/1e6).toFixed(2)+"M":Math.round(n/1e3)+"K";$("mTokens").textContent=`预计约 ${fm(st.pending.tokens_in)} 输入 token ＋ ${fm(st.pending.tokens_out)} 输出 token（粗估）。`;$("modal").classList.add("show")}
 else $("modal").classList.remove("show");
 if(!st.running){clearInterval(timer);timer=null;$("run").disabled=false;$("loadPrev").disabled=false;$("cancel").classList.add("hidden");
  if(st.error){$("err").textContent=st.error;$("err").classList.remove("hidden");pill("出错","err");$("logBox").open=true}
  if(st.result){stats(st.result);$("done").classList.remove("hidden");pill("完成","ok")}
  else if(!st.error)pill("就绪")}}catch(e){console.log(e)}}
function showWork(){$("empty").classList.add("hidden");$("work").classList.remove("hidden");$("err").classList.add("hidden")}
async function run(){const o=collect();if(!o.folder){alert("请先选择照片文件夹");return}
 if(o.ai&&!o["key_"+o.provider]&&!S.envKeys[o.provider]){alert(`开启 ${(S.P[o.provider]||{}).name||""} 细评需要填写 API Key`);$("api_key").focus();return}
 try{await api("/api/run",o)}catch(e){alert(e.message);return}
 S.runAI=o.ai;$("aiStageName").textContent=o.ai?((S.P[o.provider]||{}).name||"AI")+" 细评":"AI 细评";
 since=0;$("log").textContent="";showWork();$("done").classList.add("hidden");$("run").disabled=true;$("loadPrev").disabled=true;$("cancel").classList.remove("hidden");
 pill("运行中","run");stageUI({stage:"analyze",done:0,total:0});timer=setInterval(poll,400)}
async function loadPrev(){const folder=$("folder").value.trim();if(!folder){alert("请先选择照片文件夹");return}
 try{const r=await api("/api/load",{folder});S.runAI=false;showWork();stageUI({stage:"done",done:1,total:1});stats(r.result);$("done").classList.remove("hidden");pill("已载入","ok")}catch(e){alert(e.message)}}
$("provSeg").querySelectorAll("button").forEach(b=>b.onclick=()=>setProv(b.dataset.p));
document.querySelectorAll(".seg[data-mode] button").forEach(b=>b.onclick=()=>setAI(b.dataset.ai=="1"));
$("xmp").onchange=syncXmp;$("run").onclick=run;$("loadPrev").onclick=loadPrev;$("cancel").onclick=()=>api("/api/cancel",{});
$("pick").onclick=async()=>{$("pick").disabled=true;try{const r=await api("/api/choose",{start:$("folder").value});if(r.folder)$("folder").value=r.folder}catch(e){alert(e.message)}$("pick").disabled=false};
$("mYes").onclick=()=>{api("/api/confirm",{yes:true});$("modal").classList.remove("show")};
$("mNo").onclick=()=>{api("/api/confirm",{yes:false});$("modal").classList.remove("show")};
$("openReport").onclick=()=>window.open(`/out/${TOKEN}/report.html`,"_blank");
$("revealReport").onclick=()=>api("/api/reveal",{what:"report"});$("revealOrg").onclick=()=>api("/api/reveal",{what:"org"});
["org","org_result","org_format","org_rename"].forEach(k=>$(k).onchange=syncOrg);$("org_dir").oninput=syncOrg;
$("orgMode").querySelectorAll("button").forEach(b=>b.onclick=()=>setOrgMove(b.dataset.m=="1"));
$("pickOrg").onclick=async()=>{$("pickOrg").disabled=true;try{const r=await api("/api/choose",{start:$("org_dir").value||$("folder").value,what:"org"});if(r.folder){$("org_dir").value=r.folder;syncOrg()}}catch(e){alert(e.message)}$("pickOrg").disabled=false};
$("orgNow").onclick=async()=>{const o=orgOpts();
 if(o.org_move&&!confirm("移动模式会把照片从原文件夹搬到输出文件夹。确定继续吗？"))return;
 $("orgNow").disabled=true;try{const r=await api("/api/organize",o);stats(r.summary);
  const g=r.organized;if(g&&g.errors&&g.errors.length){const l=$("log");l.textContent+="整理失败：\n"+g.errors.join("\n")+"\n";$("logBox").open=true}}catch(e){alert(e.message)}$("orgNow").disabled=false};$("revealPhotos").onclick=()=>api("/api/reveal",{what:"photos"});
api("/api/settings").then(fill).catch(()=>{document.body.innerHTML="<p style='padding:40px'>链接已失效，请重新运行启动程序。</p>"});
</script></body></html>"""


def main(argv=None):
    global APP
    import argparse
    import signal
    ap = argparse.ArgumentParser(prog="gui.py", description="照片筛选／照片编辑 图形界面")
    ap.add_argument("--app", choices=list(APP_NAMES), default="cull", help="cull＝照片筛选，edit＝照片编辑")
    APP = ap.parse_args(argv).app
    port = int(os.environ.get("PHOTO_CULL_PORT", "0"))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    register(server.server_address[1])
    for sig in (signal.SIGTERM, getattr(signal, "SIGHUP", None)):   # 关掉终端窗口时也清理登记
        if sig is not None:
            signal.signal(sig, lambda *_: sys.exit(0))
    url = f"http://127.0.0.1:{server.server_address[1]}/?t={TOKEN}"
    print(f"{APP_NAMES[APP]} 已启动：", url, flush=True)
    print("关闭这个终端窗口即可退出。", flush=True)
    if not os.environ.get("PHOTO_CULL_NO_BROWSER"):
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
