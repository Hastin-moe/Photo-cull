from __future__ import annotations

import shutil
from pathlib import Path

from .model import Photo
from .xmp import sidecar_path

from ..paths import TRASH_DIR  # noqa: F401  （没有 send2trash 时的退路文件夹）


# ───────────────────────── 同步删除（移到废纸篓） ─────────────────────────

def trash_photo(p: Photo, root: Path) -> list[str]:
    """把配对的所有文件及其 XMP 一起移到废纸篓；没有 send2trash 时移到 照片文件夹/_待删除。"""
    files = [Path(m) for m in (p.members or [p.path])]
    side = sidecar_path(files[0])
    targets = [f for f in files + [side, side.with_suffix(".xmp.cull-bak")] if f.exists()]
    try:
        from send2trash import send2trash
    except ImportError:
        send2trash = None
    moved = []
    for t in targets:
        if send2trash:
            send2trash(str(t))
        else:
            try:
                rel = t.resolve().relative_to(root.resolve())
            except ValueError:
                rel = Path(t.name)
            dest = root / TRASH_DIR / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(t), str(dest))
        moved.append(t.name)
    p.trashed = True
    return moved
