from __future__ import annotations

import json
from pathlib import Path

from .params import normalize_params

# ───────────────────────── 编辑记录 ─────────────────────────

def edit_path(photo: str) -> Path:
    p = Path(photo)
    return p.parent / "photo-cull-report" / "edits" / (p.name + ".json")


def load_edit(photo: str) -> dict:
    try:
        return normalize_params(json.loads(edit_path(photo).read_text(encoding="utf-8")))
    except Exception:
        return normalize_params(None)


def save_edit(photo: str, P: dict) -> str:
    f = edit_path(photo)
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(normalize_params(P), ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(f)
    return str(f)


def has_edit(photo: str) -> bool:
    return edit_path(photo).is_file()
