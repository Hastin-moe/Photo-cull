from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from ..i18n import t
from ..imaging.formats import RAW_EXT
from .model import Photo
from .trash import trash_photo
from .xmp import sidecar_path

# ───────────────────────── 整理输出（分文件夹＋重命名） ─────────────────────────

ORG_MANIFEST = ".photo-cull-organize.json"     # 记录上次整理到哪里，重新整理时原地挪动而不是再复制一份
RAW_DIR, JPEG_DIR = "RAW", "JPEG"


def result_dirs(meta_or_stats: dict | None = None) -> tuple[str, str]:
    """保留／淘汰 两个文件夹的名字：沿用上次整理记录里的；没有记录时按当前语言（中文为「保留」「淘汰」）。"""
    d = meta_or_stats or {}
    if d.get("out") and not d.get("keep_dir"):          # 1.5 及以前的整理记录：当时用的是中文名
        return "保留", "淘汰"
    return d.get("keep_dir") or t("cull.org.kept"), d.get("reject_dir") or t("cull.org.rejected")


def _safe(text: str) -> str:
    return re.sub(r'[\\/:*?"<>|\s]+', "-", (text or "").strip()).strip("-.")[:40]


def org_name(p: Photo, f: Path, rename: bool) -> str:
    """星级_机型_原文件名，例如 4_ILCE-1M2_DSC01234.ARW；淘汰为 X_，未评分为 0_。"""
    model = _safe(p.camera)
    name = f.name
    if model:   # 已经整理过一次（移动模式再次整理）的文件，先去掉旧前缀，避免叠成 3_A_4_A_xxx
        name = re.sub(rf"^(?:X|[0-5])_{re.escape(model)}_", "", name)
    if not rename:
        return name
    star = "X" if p.stars < 0 else str(max(0, int(p.stars)))
    return f"{star}_{model}_{name}" if model else f"{star}_{name}"


def org_dest(p: Photo, f: Path, out_root: Path, by_result: bool, by_format: bool, rename: bool,
             dirs: tuple[str, str] | None = None) -> Path:
    d = out_root
    if by_result:
        keep, reject = dirs or result_dirs()
        d = d / (reject if p.stars < 0 else keep)
    if by_format:
        d = d / (RAW_DIR if f.suffix.lower() in RAW_EXT else JPEG_DIR)
    return d / org_name(p, f, rename)


def _same_file(a: Path, b: Path) -> bool:
    try:
        sa, sb = a.stat(), b.stat()
        return sa.st_size == sb.st_size and int(sa.st_mtime) == int(sb.st_mtime)
    except OSError:
        return False


def organize(photos: list[Photo], out_root, by_result=True, by_format=True, rename=True, move=False,
             dry=False, dirs: tuple[str, str] | None = None) -> dict:
    """把评分后的照片整理到输出文件夹。
    复制：原文件不动；再次整理时，上一次的副本按新星级换位置／换名字，不会多出一份。
    移动：原文件夹里就没有了，结果里的路径同步更新，之后在报告里改星级、删除仍然有效。
    配对的 RAW／JPEG 一起处理并共用同一个防重名后缀；边车 XMP 跟着 RAW 走、一起改名。"""
    out_root = Path(out_root).expanduser().resolve()
    man_path = out_root / ORG_MANIFEST
    try:
        manifest = json.loads(man_path.read_text(encoding="utf-8"))
    except Exception:
        manifest = {}
    stats = {"out": str(out_root), "photos": 0, "files": 0, "kept": 0, "rejected": 0, "skipped": 0,
             "mode": "move" if move else "copy", "dry_run": dry, "plan": [], "errors": [],
             "by_result": bool(by_result), "by_format": bool(by_format), "rename": bool(rename)}
    dirs = dirs or result_dirs()
    stats["keep_dir"], stats["reject_dir"] = dirs
    taken: set = set()
    for p in photos:
        if p.trashed or p.tier == "error":
            stats["skipped"] += 1
            continue
        files = [Path(m).resolve() for m in (p.members or [p.path])]
        side_owner = next((f for f in files if f.suffix.lower() in RAW_EXT), files[0])
        mine = {str(f): Path(manifest[str(f)]) for f in files if not move and str(f) in manifest}
        base = {f: org_dest(p, f, out_root, by_result, by_format, rename, dirs) for f in files}

        def free(d: Path, f: Path) -> bool:
            if str(d) in taken:
                return False
            return d == f or not d.exists() or (not move and mine.get(str(f)) == d)

        dests, n = dict(base), 2
        while not all(free(d, f) for f, d in dests.items()):
            dests = {f: d.with_name(f"{d.stem}-{n}{d.suffix}") for f, d in base.items()}
            n += 1
        taken.update(str(d) for d in dests.values())

        new_members = [str(f) for f in files]
        for i, f in enumerate(files):
            dest = dests[f]
            side = sidecar_path(f) if f == side_owner else None
            dside = dest.with_suffix(".xmp")
            if dest == f:          # 输出文件夹就是原位置且名字不变
                continue
            prev = mine.get(str(f))
            if not move and prev == dest and _same_file(f, dest):
                if side is not None and side.exists() and not dry:   # 星级没变，只刷新一下 XMP
                    shutil.copy2(side, dside)
                continue
            stats["plan"].append([str(f), str(dest)])
            if dry:
                stats["files"] += 1
                continue
            try:
                _org_file(f, dest, side, dside, prev, move, out_root)
            except Exception as e:      # 单个文件出错（被占用、磁盘满等）不影响其余照片
                stats["errors"].append(f"{f.name}: {e}")
                continue
            stats["files"] += 1
            if move:
                new_members[i] = str(dest)
            manifest[str(f)] = str(dest)
        if move and not dry:
            p.members = new_members
            p.path = new_members[0]
        stats["photos"] += 1
        stats["rejected" if p.stars < 0 else "kept"] += 1
    if not dry and (manifest or man_path.exists()):
        out_root.mkdir(parents=True, exist_ok=True)
        man_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    return stats


def org_count(photos: list[Photo], org: dict):
    live = [p for p in photos if not p.trashed and p.tier != "error"]
    org["photos"] = len(live)
    org["rejected"] = sum(1 for p in live if p.stars < 0)
    org["kept"] = org["photos"] - org["rejected"]


def org_resync(p: Photo, photos: list[Photo], meta: dict) -> dict | None:
    """报告里改了星级后，按上次的整理设置把这张照片在输出文件夹里换到新位置／新名字。"""
    org = meta.get("organized")
    if not org or org.get("dry_run") or p.trashed:
        return None
    st = organize([p], org["out"], org.get("by_result", True), org.get("by_format", True),
                  org.get("rename", True), org.get("mode") == "move",
                  dirs=result_dirs(org))
    org_count(photos, org)
    return st


def org_trash_copies(p: Photo, meta: dict) -> list[str]:
    """复制模式下删除照片时，输出文件夹里的那份副本也一起删。"""
    org = meta.get("organized")
    if not org or org.get("mode") != "copy" or org.get("dry_run"):
        return []
    out_root = Path(org["out"])
    man_path = out_root / ORG_MANIFEST
    try:
        manifest = json.loads(man_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    copies = [manifest.pop(str(Path(m).resolve()), None) for m in (p.members or [p.path])]
    copies = [c for c in copies if c and Path(c).exists() and out_root in Path(c).parents]
    if not copies:
        return []
    copies.sort(key=lambda c: Path(c).suffix.lower() not in RAW_EXT)   # RAW 在前，边车 XMP 跟着它
    import dataclasses
    moved = trash_photo(dataclasses.replace(p, members=copies, path=copies[0], trashed=False), out_root)
    man_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    return moved


def _org_file(f: Path, dest: Path, side, dside: Path, prev, move: bool, out_root: Path):
    if not f.exists():
        raise RuntimeError(t("server.file_missing"))
    dest.parent.mkdir(parents=True, exist_ok=True)
    if move:
        shutil.move(str(f), str(dest))
        if side is not None and side.exists():
            shutil.move(str(side), str(dside))
            bak = side.with_suffix(".xmp.cull-bak")
            if bak.exists():
                shutil.move(str(bak), str(dest.with_suffix(".xmp.cull-bak")))
    else:
        if prev and prev != dest and prev.exists() and out_root in prev.parents:
            prev.unlink()                       # 上次整理出的旧副本（只删输出文件夹里自己放的）
            if side is not None and prev.with_suffix(".xmp").exists():
                prev.with_suffix(".xmp").unlink()
        shutil.copy2(str(f), str(dest))
        if side is not None and side.exists():
            shutil.copy2(str(side), str(dside))
