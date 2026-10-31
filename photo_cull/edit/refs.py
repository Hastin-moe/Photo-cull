from __future__ import annotations

from ..paths import LUT_DIR, USER_LUT_DIR, LUT_ALIASES, CONFIG_DIR

import json
from pathlib import Path

# 内置 LUT：工具文件夹里的 luts/（39 个，工作空间均为 sRGB：Fujifilm GFX 胶片模拟 20、Leica Look 19），拷到别的电脑也能直接用。
# 编辑记录里写成「builtin:相对路径」，不依赖这台电脑上的绝对路径。

BUILTIN = "builtin:"
# 用户自己添加的 LUT：放在设置文件夹里，升级／重装工具不会丢，也不会混进项目源码

USER = "user:"
_BUILTIN_INDEX: dict = {}


def _builtin_index() -> dict:
    if not _BUILTIN_INDEX and LUT_DIR.is_dir():
        for f in LUT_DIR.rglob("*.cube"):
            _BUILTIN_INDEX.setdefault(f.name.lower(), f)
    return _BUILTIN_INDEX


def style_ref(path: str) -> str:
    """素材的引用：内置 LUT 写成 builtin:相对路径，其他保持原路径。"""
    for base, prefix in ((LUT_DIR, BUILTIN), (USER_LUT_DIR, USER)):
        try:
            return prefix + Path(path).resolve().relative_to(base.resolve()).as_posix()
        except (ValueError, OSError):
            pass
    return str(path)


def resolve_style(ref: str) -> str:
    """引用 → 实际文件。旧编辑记录里桌面「预设与LUT」的路径找不到时，按文件名对应到内置的同名 LUT。"""
    if ref.startswith(USER):
        return str(USER_LUT_DIR / ref[len(USER):])
    if ref.startswith(BUILTIN):
        rel = ref[len(BUILTIN):]
        if (LUT_DIR / rel).is_file():
            return str(LUT_DIR / rel)
        hit = _alias_lookup(rel)
        return str(hit) if hit else str(LUT_DIR / rel)
    p = Path(ref)
    if not p.exists() and p.suffix.lower() == ".cube":
        hit = _alias_lookup(p.name, p.parent.name) or _builtin_index().get(p.name.lower())
        if hit:
            return str(hit)
    return ref


_ALIASES: dict | None = None


def _alias_lookup(name: str, parent: str = "") -> Path | None:
    """旧版本（改名前）的 LUT 引用 → 现在的内置文件。对照表放在工具文件夹或 ~/.photo-cull 里的 lut-aliases.json（可选，没有就跳过，不随项目发布）。
    格式：{"旧文件名.cube": "新文件夹/新文件名.cube", "旧文件夹/旧文件名.cube": "…"}，键用小写。"""
    global _ALIASES
    if _ALIASES is None:
        _ALIASES = {}
        for f in (LUT_ALIASES, CONFIG_DIR / "lut-aliases.json"):
            try:
                _ALIASES.update({k.lower(): v for k, v in json.loads(f.read_text(encoding="utf-8")).items()})
            except (OSError, ValueError, AttributeError):
                pass
    base = name.replace("\\", "/").split("/")[-1].lower()
    dirn = name.replace("\\", "/").rsplit("/", 1)[0].split("/")[-1].lower() if "/" in name.replace("\\", "/") else parent.lower()
    for k in (f"{dirn}/{base}", base):
        v = _ALIASES.get(k)
        if v and (LUT_DIR / v).is_file():
            return LUT_DIR / v
    return None
