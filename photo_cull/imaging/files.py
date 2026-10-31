"""找照片：按「同一文件夹＋同名」把 RAW 和 JPEG／HIF 配成一组。筛选和编辑的文件列表共用。"""
from __future__ import annotations

from pathlib import Path

from ..paths import ORG_MANIFEST, REPORT_DIR, TRASH_DIR
from .formats import IMG_EXT, JPEG_EXT, RAW_EXT


def collect(src: Path, recursive: bool) -> list[list[Path]]:
    """按 同一文件夹＋同名（不分大小写）分组：RAW 与 JPEG／HIF 自动配对。"""
    it = src.rglob("*") if recursive else src.iterdir()
    groups: dict = {}
    org_roots = {m.parent for m in src.rglob(ORG_MANIFEST) if m.parent != src} if recursive else set()
    for f in it:
        if (not f.is_file() or f.name.startswith(".") or f.suffix.lower() not in RAW_EXT | IMG_EXT
                or REPORT_DIR in f.parts or TRASH_DIR in f.parts
                or any(r in f.parents for r in org_roots)):
            continue
        groups.setdefault((str(f.parent), f.stem.lower()), []).append(f)
    order = lambda f: (0 if f.suffix.lower() in RAW_EXT else 1 if f.suffix.lower() in JPEG_EXT else 2, f.name)
    return [sorted(g, key=order) for _, g in sorted(groups.items())]
