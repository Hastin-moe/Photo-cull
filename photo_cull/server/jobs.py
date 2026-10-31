from __future__ import annotations

from ..cull.scoring import HIGHLIGHT_WEIGHTS

import contextlib
import io
import threading
import traceback

from ..cull import state as _state
from ..cull.ai.providers import PROVIDERS
from ..cull.cli import main
from ..cull.state import CANCEL, Cancelled
from ..i18n import t
from .settings import DEFAULTS

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
        self.ai = False
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
                    "error": self.error, "pending": self.pending, "ai": self.ai}

    # 回调
    def progress(self, stage, done, total):
        with self.lock:
            self.stage, self.done, self.total = stage, done, total

    def confirm(self, count, tokens_in, tokens_out, model):
        with self.lock:
            self.pending = {"count": count, "tokens_in": tokens_in, "tokens_out": tokens_out, "model": model}
        self.answered.clear()
        while not self.answered.wait(0.3):
            if CANCEL.is_set():
                break
        with self.lock:
            self.pending = None
        return bool(self.answer)


JOB = Job()


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
        if o.get("org_category", True): argv.append("--by-category")
        if o.get("org_format", True): argv.append("--by-format")
        if o.get("org_rename", True): argv.append("--rename")
        if o.get("org_move"): argv.append("--move")
    for key, flag in [("burst_gap", "--burst-gap"), ("scene_gap", "--scene-gap"), ("similarity", "--similarity"),
                      ("blur_warn", "--blur-warn"), ("blur_reject", "--blur-reject"),
                      ("clip_high", "--clip-high"), ("clip_low", "--clip-low"), ("workers", "--workers"),
                      ("pick_ai", "--pick-ai"), ("pick_local", "--pick-local")]:
        argv += [flag, str(o.get(key, DEFAULTS[key]))]
    argv += ["--weights", ",".join(f"{k}={float(o.get('w_' + k, DEFAULTS['w_' + k]))}" for k in HIGHLIGHT_WEIGHTS)]
    return argv


def run_job(options: dict):
    JOB.reset()
    JOB.running = True
    JOB.ai = bool(options.get("ai"))
    CANCEL.clear()
    _state.PROGRESS = JOB.progress
    prov = options.get("provider", "claude")
    _state.API_KEYS = {prov: options["key_" + prov]} if options.get("ai") and options.get("key_" + prov) else {}
    writer = LogWriter(JOB)
    try:
        with contextlib.redirect_stdout(writer), contextlib.redirect_stderr(writer):
            JOB.result = main(build_argv(options), confirm=JOB.confirm)
    except Cancelled:
        JOB.error = t("server.cancelled")
    except SystemExit as e:
        JOB.error = str(e.code) if e.code not in (None, 0) else None
    except Exception as e:
        JOB.error = f"{type(e).__name__}: {e}"
        JOB.log(traceback.format_exc())
    finally:
        JOB.running = False
        _state.PROGRESS = None
        _state.API_KEYS = {}
