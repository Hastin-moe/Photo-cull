from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from ..i18n import t
from ..imaging.formats import RAW_EXT
from .model import Photo, shown
from .trash import trash_photo
from .xmp import sidecar_path

# ───────────────────────── 整理输出（分文件夹＋重命名） ─────────────────────────
#
# 输出文件夹的结构（全部选项打开时）：
#   保留/精选/JPEG|RAW/…                 单张照片里分数达到精选线的
#   保留/连拍瞬间/连拍012_103045/JPEG|RAW/…   每组连拍挑出的那一张，一组一个文件夹
#   保留/可用/JPEG|RAW/…                 其余保留的（含连拍里没被选中的帧）
#   淘汰/JPEG|RAW/…
# 文件夹名按整理时的界面语言取，并记在整理记录里（dirs），之后在报告里改分数、删除时沿用。

from ..paths import ORG_MANIFEST  # noqa: E402  记录上次整理到哪里，重新整理时原地挪动而不是再复制一份
RAW_DIR, JPEG_DIR = "RAW", "JPEG"
DIR_KEYS = ("keep", "reject", "pick", "moment", "usable", "group")


@dataclass
class Layout:
    by_result: bool = True         # 保留／淘汰
    by_category: bool = True       # 保留里再分 精选／连拍瞬间／可用
    by_format: bool = True         # 每个里面再分 JPEG／RAW
    rename: bool = True            # 分数_机型_原文件名
    dirs: dict = field(default_factory=dict)

    @classmethod
    def from_record(cls, org: dict | None, **override) -> "Layout":
        org = org or {}
        lay = cls(by_result=org.get("by_result", True), by_category=org.get("by_category", False),
                  by_format=org.get("by_format", True), rename=org.get("rename", True), dirs=dir_names(org))
        for k, v in override.items():
            setattr(lay, k, v)
        return lay


def dir_names(record: dict | None = None) -> dict:
    """各个文件夹的名字：沿用整理记录里的；没有记录时按当前语言。
    1.5 及以前的记录没有名字（当时是中文「保留」「淘汰」）；1.6–1.7 只记了 keep_dir／reject_dir。"""
    d = record or {}
    saved = dict(d.get("dirs") or {})
    if not saved and d.get("out"):
        saved = {"keep": d.get("keep_dir") or "保留", "reject": d.get("reject_dir") or "淘汰"}
    names = {k: t("cull.org.folder." + k) for k in DIR_KEYS}
    names.update({k: v for k, v in saved.items() if k in DIR_KEYS and v})
    return names


def _safe(text: str) -> str:
    return re.sub(r'[\\/:*?"<>|\s]+', "-", (text or "").strip()).strip("-.")[:40]


def group_dir(p: Photo, dirs: dict) -> str:
    """连拍瞬间里每组的文件夹名，例如 连拍012_103045（组号＋这张的拍摄时间）。"""
    hhmmss = (p.time_text or "")[-8:].replace(":", "") or "000000"
    try:
        return _safe(dirs["group"].format(n=f"{p.group:03d}", time=hhmmss))
    except (KeyError, IndexError, ValueError):
        return f"{p.group:03d}_{hhmmss}"


PREFIX = re.compile(r"^(?:X|\d{1,2})_")


def org_name(p: Photo, f: Path, rename: bool) -> str:
    """分数_机型_原文件名，例如 07_ILCE-1M2_DSC01234.ARW（两位数，按文件名排序就是按分数）；淘汰为 X_。"""
    model = _safe(p.camera)
    name = f.name
    if model:   # 已经整理过一次（移动模式再次整理）的文件，先去掉旧前缀，避免叠成 07_A_04_A_xxx
        name = re.sub(rf"^(?:X|\d{{1,2}})_{re.escape(model)}_", "", name)
    if not rename:
        return name
    head = "X" if p.category == "reject" else f"{shown(p.score):02d}"
    return f"{head}_{model}_{name}" if model else f"{head}_{name}"


def org_dest(p: Photo, f: Path, out_root: Path, lay: Layout) -> Path:
    d, dirs = out_root, lay.dirs or dir_names()
    rejected = p.category == "reject"
    if lay.by_result:
        d = d / (dirs["reject"] if rejected else dirs["keep"])
    if lay.by_category and not rejected:
        cat = p.category if p.category in ("pick", "moment", "usable") else "usable"
        d = d / dirs[cat]
        if cat == "moment":
            d = d / group_dir(p, dirs)
    if lay.by_format:
        d = d / (RAW_DIR if f.suffix.lower() in RAW_EXT else JPEG_DIR)
    return d / org_name(p, f, lay.rename)


def _same_file(a: Path, b: Path) -> bool:
    try:
        sa, sb = a.stat(), b.stat()
        return sa.st_size == sb.st_size and int(sa.st_mtime) == int(sb.st_mtime)
    except OSError:
        return False


def organize(photos: list[Photo], out_root, lay: Layout | None = None, move: bool = False, dry: bool = False) -> dict:
    """把评分后的照片整理到输出文件夹。
    复制：原文件不动；再次整理时，上一次的副本按新分数换位置／换名字，不会多出一份。
    移动：原文件夹里就没有了，结果里的路径同步更新，之后在报告里改分数、删除仍然有效。
    配对的 RAW／JPEG 一起处理并共用同一个防重名后缀；边车 XMP 跟着 RAW 走、一起改名。"""
    lay = lay or Layout()
    lay.dirs = lay.dirs or dir_names()
    out_root = Path(out_root).expanduser().resolve()
    man_path = out_root / ORG_MANIFEST
    try:
        manifest = json.loads(man_path.read_text(encoding="utf-8"))
    except Exception:
        manifest = {}
    stats = {"out": str(out_root), "photos": 0, "files": 0, "skipped": 0,
             "mode": "move" if move else "copy", "dry_run": dry, "plan": [], "errors": [],
             "by_result": lay.by_result, "by_category": lay.by_category, "by_format": lay.by_format,
             "rename": lay.rename, "dirs": dict(lay.dirs)}
    taken: set = set()
    for p in photos:
        if p.trashed or p.category == "error":
            stats["skipped"] += 1
            continue
        files = [Path(m).resolve() for m in (p.members or [p.path])]
        side_owner = next((f for f in files if f.suffix.lower() in RAW_EXT), files[0])
        mine = {str(f): Path(manifest[str(f)]) for f in files if not move and str(f) in manifest}
        base = {f: org_dest(p, f, out_root, lay) for f in files}

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
                if side is not None and side.exists() and not dry:   # 分数没变，只刷新一下 XMP
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
    org_count(photos, stats)
    if not dry and (manifest or man_path.exists()):
        out_root.mkdir(parents=True, exist_ok=True)
        man_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    _prune_empty(out_root, lay, dry)
    return stats


def _prune_empty(out_root: Path, lay: Layout, dry: bool):
    """改分数后照片换了文件夹，原来的空文件夹（比如某组连拍瞬间）顺手删掉。
    只在 保留／淘汰 这两个本工具建的文件夹里找，只删空的。"""
    if dry or not lay.by_result:
        return
    for top in (out_root / lay.dirs["keep"], out_root / lay.dirs["reject"]):
        if not top.is_dir():
            continue
        for d in sorted((x for x in top.rglob("*") if x.is_dir()), key=lambda x: len(x.parts), reverse=True):
            try:
                if not any(d.iterdir()):
                    d.rmdir()
            except OSError:
                pass


def org_count(photos: list[Photo], org: dict):
    """整理记录里的数量（报告里改分数、删除后重新统计）。"""
    live = [p for p in photos if not p.trashed and p.category != "error"]
    org["photos"] = len(live)
    for k in ("pick", "moment", "usable"):
        org[k] = sum(1 for p in live if p.category == k)
    org["rejected"] = sum(1 for p in live if p.category == "reject")
    org["kept"] = org["photos"] - org["rejected"]


def org_resync(p: Photo, photos: list[Photo], meta: dict) -> dict | None:
    """报告里改了分数后，按上次的整理设置把这张照片在输出文件夹里换到新位置／新名字。"""
    org = meta.get("organized")
    if not org or org.get("dry_run") or p.trashed:
        return None
    st = organize([p], org["out"], Layout.from_record(org), move=org.get("mode") == "move")
    org_count(photos, org)
    org["errors"] = st["errors"]
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
