from __future__ import annotations

from ..paths import WEB

import csv
import json
import os
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from .. import i18n
from ..i18n import t
from ..version import VERSION
from .ai.prompts import GENRE_LEGACY
from .flags import flag_code, flag_text
from .model import CATEGORIES, SCHEMA, Photo, photos_from_json, shown
from .scoring import counts

# ───────────────────────── 报告与结果文件 ─────────────────────────

REPORT_PREFIXES = ("common", "report", "flag", "genre", "cat")


def category_text(cat: str, lang: str | None = None) -> str:
    return t("cat." + cat, lang) if cat in CATEGORIES else cat


def load_results(out: Path) -> tuple[list[Photo], dict]:
    """读 results.json 和 meta.json。旧格式（1.7.1 及以前）自动转换，问题标记／题材的中文写法也转成代码。"""
    photos, schema = photos_from_json(json.loads((out / "results.json").read_text(encoding="utf-8")))
    for p in photos:
        p.flags = [flag_code(f) for f in p.flags]
        if p.ai and p.ai.get("genre") in GENRE_LEGACY:
            p.ai["genre"] = GENRE_LEGACY[p.ai["genre"]]
    meta_path = out / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    if schema < SCHEMA:
        meta["upgraded_from"] = schema
    return photos, meta


def summarize(photos: list[Photo], out: Path, meta: dict) -> dict:
    live = [p for p in photos if not p.trashed]
    c = counts(photos)
    return {"out": str(out), "report": str(out / "report.html"), "total": len(live),
            "pick": c["pick"], "moment": c["moment"], "usable": c["usable"], "reject": c["reject"], "error": c["error"],
            "kept": c["pick"] + c["moment"] + c["usable"],
            "bursts": len({p.group for p in live if p.group_size > 1 and p.category != "error"}),
            "pairs": sum(1 for p in live if len(p.members) > 1),
            "trashed": sum(1 for p in photos if p.trashed),
            "xmp": meta.get("xmp", 0), "dry_run": meta.get("dry_run", False),
            "organized": {k: v for k, v in (meta.get("organized") or {}).items() if k != "plan"} or None}


def write_results(photos: list[Photo], out: Path, meta: dict):
    """results.json（schema 2）和 meta.json：先写临时文件再替换，写到一半断电也不会坏。"""
    data = {"schema": SCHEMA, "version": VERSION, "photos": [asdict(p) for p in photos]}
    for name, obj in (("results.json", data), ("meta.json", {k: v for k, v in meta.items() if k != "upgraded_from"})):
        tmp = out / (name + ".tmp")
        tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(out / name)
    return data["photos"]


def write_csv(photos: list[Photo], out: Path, lang: str):
    sep = t("cull.msg.list_sep", lang)
    with open(out / "results.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow([t("report.csv." + k, lang) for k in ("file", "pair", "result", "score", "stars", "label", "local",
                                                       "ai", "ai_score", "highlight", "blur", "faces", "burst",
                                                       "issues", "comment", "deleted")])
        for p in photos:
            a = p.ai or {}
            w.writerow([p.name, " + ".join(Path(m).name for m in p.members), category_text(p.category, lang),
                        shown(p.score) if p.category != "error" else "", p.stars, p.label, shown(p.local_score),
                        a.get("provider", ""), shown(a["overall"]) if a.get("overall") else "",
                        round(p.highlight, 2), p.blur, p.faces, f"{p.group}/{p.group_size}",
                        sep.join(flag_text(x, lang) for x in p.flags), a.get("comment", ""),
                        t("report.csv.yes", lang) if p.trashed else ""])


def write_report(photos: list[Photo], out: Path, meta: dict, lang: str | None = None):
    """results.json／meta.json／results.csv，以及独立的 report.html。
    报告页由 web/report/ 的模板生成：样式、脚本和当前语言的语言包都内联进去，
    所以 report.html 单独拷走（或直接双击打开）也能看。"""
    lang = lang or i18n.current()
    rows = write_results(photos, out, meta)
    write_csv(photos, out, lang)
    web = WEB
    page = (web / "report" / "report.html").read_text(encoding="utf-8")
    css = (web / "common" / "tokens.css").read_text(encoding="utf-8") + "\n" + (web / "report" / "report.css").read_text(encoding="utf-8")
    js = (web / "common" / "i18n.js").read_text(encoding="utf-8") + "\n" + (web / "report" / "report.js").read_text(encoding="utf-8")
    b = i18n.bundle(None, lang)
    d = {k: v for k, v in b["dict"].items() if k.split(".", 1)[0] in REPORT_PREFIXES}
    d["common.trash"] = d.get("common.trash_win" if os.name == "nt" else "common.trash_mac", "")
    safe = lambda obj: json.dumps(obj, ensure_ascii=False).replace("</", "<\\/")
    info = {"src": meta.get("src", ""), "when": datetime.now().strftime("%Y-%m-%d %H:%M"), "ver": VERSION}
    for k, v in {"__LANG__": i18n.html_lang(lang), "__CSS__": css, "__I18N__": safe({"lang": lang, "langs": b["langs"], "dict": d}),
                 "__DATA__": safe(rows), "__INFO__": safe(info), "__JS__": js.replace("</script", "<\\/script")}.items():
        page = page.replace(k, v)
    (out / "report.html").write_text(page, encoding="utf-8")
