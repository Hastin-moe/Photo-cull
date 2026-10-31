from __future__ import annotations

from ..paths import THUMB_DIR

import hashlib
import io
import os
from pathlib import Path

from PIL import Image

from ..cull.pipeline import collect
from ..i18n import t
from ..imaging.exif import exposure_text, read_exif
from ..imaging.formats import RAW_EXT
from ..imaging.preview import load_preview
from .logspace import guess_space
from .params import EDIT_EXT
from .records import has_edit
from .refs import LUT_DIR, style_ref
from .styles import LIBRARY_SCOPE, builtin_group_label, user_lut_items

# ───────────────────────── 文件列表与素材库 ─────────────────────────

def list_folder(folder: str) -> list[dict]:
    d = Path(folder).expanduser()
    if not d.is_dir():
        raise ValueError(t("server.folder_not_found"))
    groups = collect(d, False)
    items = []
    for g in groups:
        primary = g[0]
        if primary.suffix.lower() not in EDIT_EXT:
            continue
        items.append({"path": str(primary), "name": primary.name,
                      "pair": [m.suffix.upper().lstrip(".") for m in g] if len(g) > 1 else [],
                      "raw": primary.suffix.lower() in RAW_EXT, "edited": has_edit(str(primary))})
    return items


def default_library() -> str:
    if LUT_DIR.is_dir():
        return "builtin"
    for c in (Path.home() / "Desktop" / "预设与LUT", Path.home() / "Desktop"):
        if c.is_dir():
            return str(c)
    return str(Path.home())


def scan_library(root: str, limit: int = 8000) -> dict:
    """root ＝ "builtin"（内置 LUT）或一个文件夹。"""
    builtin = root in ("builtin", "", "（内置）") or Path(root).expanduser().resolve() == LUT_DIR
    r = LUT_DIR if builtin else Path(root).expanduser()
    if not r.is_dir():
        raise ValueError(t("edit.err.lib_not_found"))
    scope = [] if builtin else [s for s in LIBRARY_SCOPE if (r / s).is_dir()]
    starts = [r / s for s in scope] if scope else [r]
    items = []
    walk = (w for st in starts for w in os.walk(st))
    for dirpath, dirnames, filenames in walk:
        dirnames[:] = sorted(d for d in dirnames if not d.startswith(".") and d != "__MACOSX")
        for fn in sorted(filenames):
            low = fn.lower()
            if fn.startswith(".") or not (low.endswith(".cube") or low.endswith(".xmp")):
                continue
            full = Path(dirpath) / fn
            rel = full.relative_to(r)
            item = {"path": style_ref(str(full)) if builtin else str(full), "name": full.stem.replace(".cube", ""),
                    "group": rel.parent.as_posix(), "kind": "cube" if low.endswith(".cube") else "xmp"}
            if builtin:
                item["group_label"] = builtin_group_label(item["group"])
            if item["kind"] == "cube":
                sp, warn = guess_space(str(full))
                item["space"] = sp
                item["warn"] = bool(warn)
            items.append(item)
            if len(items) >= limit:
                return {"root": "builtin" if builtin else str(r), "items": items, "truncated": True, "scope": scope, "builtin": builtin}
    if builtin:
        items.extend(user_lut_items())
    return {"root": "builtin" if builtin else str(r), "items": items, "truncated": False, "scope": scope, "builtin": builtin}


# ───────────────────────── 缩略图 ─────────────────────────




def thumbnail(path: str, side: int = 360) -> bytes:
    p = Path(path)
    st = p.stat()
    key = hashlib.sha1(f"{p}|{st.st_mtime}|{st.st_size}|{side}".encode()).hexdigest()
    cached = THUMB_DIR / (key + ".jpg")
    if cached.is_file():
        return cached.read_bytes()
    img = load_preview(p, side * 2)
    img.thumbnail((side, side), Image.LANCZOS)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=82)
    data = buf.getvalue()
    try:
        THUMB_DIR.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(data)
    except OSError:
        pass
    return data


def _exif_text(p: Path) -> str:
    try:
        e = read_exif(p)
        return " · ".join(x for x in (e.get("model", ""), e.get("lens", ""), exposure_text(e)) if x)
    except Exception:
        return ""
