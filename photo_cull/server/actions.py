from __future__ import annotations

from ..paths import REPORT_DIR

from ..cull.scoring import set_manual

from ..cull.organize import Layout

from types import SimpleNamespace

import os
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

from ..cull.organize import org_resync, org_trash_copies, organize
from ..cull.report import load_results, summarize, write_report
from ..cull.trash import TRASH_DIR, trash_photo
from ..cull.xmp import apply_marks
from ..i18n import t
from .jobs import JOB
from .settings import _remember

# ───────────────────────── 报告里的标记与删除 ─────────────────────────

def _current():
    if not JOB.result:
        raise RuntimeError(t("server.no_result"))
    out = Path(JOB.result["out"])
    photos, meta = load_results(out)
    return out, photos, meta


def mark_photo(path: str, score: int) -> dict:
    """报告里手动打分：1–10 分，−1 为淘汰，0 为清除分数。"""
    if isinstance(score, bool) or not isinstance(score, (int, float)) or not -1 <= score <= 10:
        raise ValueError(t("server.bad_score"))
    with JOB.edit:
        out, photos, meta = _current()
        p = next((x for x in photos if x.path == path and not x.trashed), None)
        if p is None:
            raise ValueError(t("server.photo_not_found"))
        set_manual(p, score, SimpleNamespace(**(meta.get("scoring") or {})))
        # 人工调整是明确的操作：即使上次是演练模式也写入，并同步到配对的每个文件
        written = apply_marks(p, False, meta.get("jpeg_embed", True), meta.get("xmp_all", False))
        moved = None
        try:   # 整理过的话，输出文件夹里的这张也换到新分数对应的位置／名字
            st = org_resync(p, photos, meta)
            moved = st and st["files"]
        except Exception as e:
            print("同步整理输出失败：", e, file=sys.__stderr__)
        write_report(photos, out, meta)
        JOB.result = summarize(photos, out, meta)
        return {"photo": asdict(p), "written": written, "organized": moved, "summary": JOB.result}


def trash_photos(paths: list) -> dict:
    with JOB.edit:
        out, photos, meta = _current()
        root = Path(meta.get("src") or out.parent)
        want = set(paths)
        done, files = [], 0
        for p in photos:
            if p.path in want and not p.trashed:
                files += len(trash_photo(p, root))
                try:
                    files += len(org_trash_copies(p, meta))
                except Exception as e:
                    print("删除整理输出里的副本失败：", e, file=sys.__stderr__)
                done.append(p.path)
        write_report(photos, out, meta)
        JOB.result = summarize(photos, out, meta)
        try:
            import send2trash  # noqa: F401
            where = t("common.trash_win" if os.name == "nt" else "common.trash_mac")
        except ImportError:
            where = t("server.trash_fallback", dir=TRASH_DIR)
        return {"trashed": done, "files": files, "where": where, "summary": JOB.result}


def organize_now(o: dict) -> dict:
    """在报告里复核完之后，按当前分数整理。"""
    with JOB.edit:
        out, photos, meta = _current()
        src = Path(meta.get("src") or out.parent)
        target = Path(str(o.get("org_dir") or "").strip() or t("cull.org.default_dir")).expanduser()
        if not target.is_absolute():
            target = src / target
        prev = meta.get("organized") or {}
        same = prev.get("out") and Path(prev["out"]) == target.resolve()
        lay = Layout.from_record(prev if same else None, by_result=bool(o.get("org_result", True)),
                                 by_category=bool(o.get("org_category", True)), by_format=bool(o.get("org_format", True)),
                                 rename=bool(o.get("org_rename", True)))
        st = organize(photos, target, lay, move=bool(o.get("org_move")))
        meta["organized"] = st
        write_report(photos, out, meta)
        JOB.result = summarize(photos, out, meta)
        _remember(**{k: o[k] for k in ("org_dir", "org_result", "org_category", "org_format", "org_rename", "org_move") if k in o})
        return {"organized": JOB.result["organized"], "summary": JOB.result}


def load_previous(folder: str) -> dict:
    out = Path(folder).expanduser() / REPORT_DIR
    if not (out / "results.json").is_file():
        raise ValueError(t("server.no_prev"))
    photos, meta = load_results(out)
    meta.setdefault("src", str(Path(folder).expanduser()))
    JOB.reset()
    JOB.result = summarize(photos, out, meta)
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
