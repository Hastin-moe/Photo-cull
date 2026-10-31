from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path

from ..i18n import t
from ..imaging.exif import capture_time, exposure_text, read_exif
from ..imaging.formats import IMG_EXT, JPEG_EXT, RAW_EXT
from ..imaging.preview import _fit, load_preview
from .ai.review import AI_SIDE
from .analysis import analyze
from .model import Photo
from .organize import ORG_MANIFEST
from .trash import TRASH_DIR

THUMB_SIDE = 520   # 报告缩略图


# ───────────────────────── 主流程 ─────────────────────────

def collect(src: Path, recursive: bool) -> list[list[Path]]:
    """按 同一文件夹＋同名（不分大小写）分组：RAW 与 JPEG／HIF 自动配对。"""
    it = src.rglob("*") if recursive else src.iterdir()
    groups: dict = {}
    org_roots = {m.parent for m in src.rglob(ORG_MANIFEST) if m.parent != src} if recursive else set()
    for f in it:
        if (not f.is_file() or f.name.startswith(".") or f.suffix.lower() not in RAW_EXT | IMG_EXT
                or "photo-cull-report" in f.parts or TRASH_DIR in f.parts
                or any(r in f.parents for r in org_roots)):
            continue
        groups.setdefault((str(f.parent), f.stem.lower()), []).append(f)
    order = lambda f: (0 if f.suffix.lower() in RAW_EXT else 1 if f.suffix.lower() in JPEG_EXT else 2, f.name)
    return [sorted(g, key=order) for _, g in sorted(groups.items())]


def process_one(members: list[Path], thumbs: Path, keep_preview: bool):
    primary = members[0]
    p = Photo(path=str(primary), name=primary.name, kind="raw" if primary.suffix.lower() in RAW_EXT else "image",
              members=[str(m) for m in members])
    # 分析优先用相机直出 JPEG（全尺寸、颜色即机内效果）；失败再用 RAW 内嵌预览
    candidates = [m for m in members if m.suffix.lower() in JPEG_EXT] + [m for m in members if m.suffix.lower() not in JPEG_EXT]
    img, errors = None, []
    for src in candidates:
        try:
            e = read_exif(src)
            img = load_preview(src)       # 评分按全尺寸解码（模糊阈值据此调定），之后只缩放一次
            p.source = str(src)
            break
        except Exception as ex:
            errors.append(f"{src.name}: {type(ex).__name__}: {ex}")
    try:
        if img is None:
            raise RuntimeError("; ".join(errors) or t("cull.msg.unreadable"))
        if not e.get("dt") and p.kind == "raw":
            e = {**read_exif(primary), **{k: v for k, v in e.items() if v}}
        p.time = capture_time(e, primary)
        p.time_text = datetime.fromtimestamp(p.time).strftime("%Y-%m-%d %H:%M:%S")
        p.camera, p.lens, p.exposure = e.get("model", ""), e.get("lens", ""), exposure_text(e)
        img = analyze(img, p)          # 换成 2400 的那张，后面的缩略图、AI 用图都从它缩
        tname = hashlib.sha1(str(primary).encode()).hexdigest()[:16] + ".jpg"
        _fit(img, THUMB_SIDE).save(thumbs / tname, "JPEG", quality=82)
        p.thumb = "thumbs/" + tname
    except Exception as ex:
        p.error = f"{type(ex).__name__}: {ex}"
        img = None
    return p, (_fit(img, AI_SIDE) if (img is not None and keep_preview) else None)
