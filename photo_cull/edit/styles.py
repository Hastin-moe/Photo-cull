from __future__ import annotations

import os
import re
import threading
from pathlib import Path

from ..i18n import t
from .logspace import guess_space
from .lut3d import load_cube
from .refs import USER, USER_LUT_DIR, style_ref

LIBRARY_SCOPE = ()   # 非内置素材库：留空＝列出文件夹里全部 LUT／预设
USER_GROUP = "我的 LUT"          # 分组的内部名字；界面显示用 group_label（随语言变化）
USER_LUT_MAX = 64 * 1024 * 1024        # 单个 .cube 最大 64 MB（65³ 的 LUT 约 9 MB）


def builtin_group_label(folder: str) -> str:
    """内置 LUT 的文件夹名 → 界面显示名（文件夹名本身不随语言变化，免得编辑记录里的引用失效）。"""
    low = folder.lower()
    if low.startswith("fujifilm"):
        return t("edit.lib.group.fujifilm")
    if low.startswith("leica"):
        return t("edit.lib.group.leica")
    return folder


# ───── 用户添加的 LUT
def user_lut_items() -> list:
    if not USER_LUT_DIR.is_dir():
        return []
    out = []
    for f in sorted(USER_LUT_DIR.rglob("*.cube"), key=lambda x: x.name.lower()):
        if f.name.startswith("."):
            continue
        sp, warn = guess_space(str(f))
        out.append({"path": style_ref(str(f)), "name": f.stem, "group": USER_GROUP, "kind": "cube",
                    "space": sp, "warn": bool(warn), "user": True, "group_label": t("edit.lib.group.user")})
    return out


def _safe_lut_name(name: str) -> str:
    stem = Path(str(name).replace("\\", "/")).name
    if stem.lower().endswith(".cube"):
        stem = stem[:-5]
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", stem).strip(" .")[:120]
    return stem or "LUT"


def add_user_lut(name: str, text: str) -> dict:
    """检查一个 .cube 的内容，没问题就存进 USER_LUT_DIR。重名时加 (2)、(3)…，不覆盖已有文件。"""
    if not str(name).lower().endswith(".cube"):
        raise ValueError(t("edit.err.cube_only"))
    data = str(text).encode("utf-8")
    if len(data) > USER_LUT_MAX:
        raise ValueError(t("edit.err.cube_too_big"))
    USER_LUT_DIR.mkdir(parents=True, exist_ok=True)
    stem = _safe_lut_name(name)
    tmp = USER_LUT_DIR / f".incoming-{os.getpid()}-{threading.get_ident()}.cube"
    tmp.write_bytes(data)
    try:
        c = load_cube(str(tmp))                      # 格式不对会在这里报错
        dest, n = USER_LUT_DIR / f"{stem}.cube", 2
        while dest.exists():
            dest, n = USER_LUT_DIR / f"{stem} ({n}).cube", n + 1
        os.replace(tmp, dest)
    finally:
        if tmp.exists():
            tmp.unlink()
    sp, warn = guess_space(str(dest))
    return {"path": style_ref(str(dest)), "name": dest.stem, "size": c["size"], "lut_kind": c["kind"],
            "space": sp, "warning": warn}


def remove_user_lut(ref: str) -> str:
    """只能移除「我的 LUT」里的文件（内置和外部素材库的文件不动）。"""
    if not str(ref).startswith(USER):
        raise ValueError(t("edit.err.remove_own"))
    p = (USER_LUT_DIR / ref[len(USER):]).resolve()
    if USER_LUT_DIR.resolve() not in p.parents or p.suffix.lower() != ".cube" or not p.is_file():
        raise ValueError(t("edit.err.lut_not_found"))
    p.unlink()
    return p.stem
