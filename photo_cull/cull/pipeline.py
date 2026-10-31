"""筛选的主流程，按阶段拆开：收集 → 本地分析 → 分组评分 → AI 细评 → 沿用手动分数 → 定分
→ 写 XMP → 删除淘汰 → 整理输出 → 报告。命令行（cli.py）和图形界面都调用 run()。"""
from __future__ import annotations

import concurrent.futures as cf
import hashlib
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from ..i18n import t
from ..imaging.exif import capture_time, exposure_text, read_exif
from ..imaging.files import collect
from ..imaging.formats import JPEG_EXT, RAW_EXT
from ..imaging.preview import _fit, load_preview
from ..paths import REPORT_DIR
from ..version import VERSION
from .ai.review import AI_SIDE, ai_review
from .analysis import SIGS, analyze
from .grouping import group_bursts
from .model import Photo
from .organize import Layout, organize
from .report import load_results, summarize, write_report
from .scoring import ai_candidates, finalize, score_local
from .state import CANCEL, Cancelled, _report
from .trash import trash_photo
from .xmp import apply_marks

THUMB_SIDE = 520   # 报告缩略图


# ───────────────────────── 主流程 ─────────────────────────

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


# ───────────────────────── 各阶段 ─────────────────────────

def analyze_all(groups: list[list[Path]], thumbs: Path, args) -> tuple[list[Photo], dict]:
    """并行读图＋技术分析。返回照片和（开 AI 时）发给 AI 用的小图。"""
    photos, previews = [], {}
    _report("analyze", 0, len(groups))
    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(process_one, g, thumbs, args.ai) for g in groups]
        for i, fut in enumerate(cf.as_completed(futs), 1):
            if CANCEL.is_set():
                for f in futs:
                    f.cancel()
                raise Cancelled()
            p, prev = fut.result()
            _report("analyze", i, len(groups))
            photos.append(p)
            if prev is not None:
                previews[p.path] = prev
            if i % 20 == 0 or i == len(groups):
                print(f"  {i}/{len(groups)}")
    return photos, previews


def review(photos: list[Photo], previews: dict, out: Path, args):
    """AI 细评：每组选中的那张和单张照片（--ai-alts 时连拍里其余的帧也评）。结果按图片缓存，重跑不重复收费。"""
    items = [(p, previews[p.path]) for p in ai_candidates(photos, args.ai_alts) if p.path in previews]
    cache_path = out / "ai_cache.json"
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    ai_review(items, args, cache, cache_path)
    cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")


def restore_manual(photos: list[Photo], out: Path) -> dict | None:
    """重新筛选同一文件夹时，沿用上次在报告里手动打的分数；返回上次的整理记录。"""
    if not (out / "results.json").is_file():
        return None
    try:
        prev, prev_meta = load_results(out)
    except Exception:
        return None
    manual = {q.path: q for q in prev if q.manual and not q.trashed}
    for p in photos:
        q = manual.get(p.path)
        if q:
            p.score, p.manual = q.score, True
            if q.category == "reject":
                p.category = "reject"
            elif p.category == "reject":
                p.category = ""
    if manual:
        print(t("cull.msg.kept_manual", n=sum(1 for p in photos if p.manual)))
    return (prev_meta or {}).get("organized")


def write_marks(photos: list[Photo], args) -> int:
    written = 0
    _report("xmp", 0, 1)
    if args.no_xmp:
        return 0
    for p in photos:
        if p.category == "error":
            continue
        try:
            if apply_marks(p, args.dry_run, not args.no_jpeg_embed, args.xmp_all):
                written += 1
        except Exception as ex:
            p.flags.append(f"xmp_fail:{ex}")
    return written


def trash_rejects(photos: list[Photo], src: Path, args) -> int:
    if not args.trash_rejects or args.dry_run:
        return 0
    rejects = [p for p in photos if p.category == "reject"]
    if not rejects or not (args.yes or input(t("cull.msg.trash_ask", n=len(rejects))).strip().lower() == "y"):
        return 0
    return sum(len(trash_photo(p, src)) for p in rejects)


def organize_step(photos: list[Photo], src: Path, prev_org: dict | None, args) -> dict | None:
    if args.organize is None:
        if prev_org and not prev_org.get("dry_run") and Path(prev_org.get("out", "")).is_dir():
            # 这次没勾整理：沿用上次的整理记录，之后在报告里改分数、删除仍会同步到输出文件夹
            print(t("cull.msg.org_kept_state", out=prev_org["out"]))
            return {k: v for k, v in prev_org.items() if k != "plan"}
        return None
    target = Path(args.organize).expanduser() if args.organize else src / t("cull.org.default_dir")
    if not target.is_absolute():
        target = src / target
    same = prev_org and Path(prev_org.get("out", "")) == target.resolve()
    lay = Layout.from_record(prev_org if same else None, by_result=args.by_result, by_category=args.by_category,
                             by_format=args.by_format, rename=args.rename)
    st = organize(photos, target, lay, args.move, args.dry_run)
    verb = t("cull.org.verb_move" if args.move else "cull.org.verb_copy")
    if args.dry_run:
        print(t("cull.msg.org_dry", n=st["photos"], files=len(st["plan"]), verb=verb, out=target))
    else:
        print(t("cull.msg.org_done", n=st["photos"], files=st["files"], verb=verb, out=target, **{k: st[k] for k in (
            "pick", "moment", "usable", "rejected")}))
    for e in st["errors"][:10]:
        print("  " + t("cull.org.failed") + " " + e)
    return st


def run(args) -> dict:
    src = args.folder.expanduser().resolve()
    if not src.is_dir():
        sys.exit(t("cull.msg.no_folder", path=src))
    out = args.out.expanduser().resolve() if args.out else src / REPORT_DIR
    thumbs = out / "thumbs"
    thumbs.mkdir(parents=True, exist_ok=True)

    groups = collect(src, args.recursive)
    if not groups:
        sys.exit(t("cull.msg.no_photos"))
    print(t("cull.msg.start", n=len(groups), files=sum(len(g) for g in groups), pairs=sum(1 for g in groups if len(g) > 1)))
    t0 = time.time()
    photos, previews = analyze_all(groups, thumbs, args)
    group_bursts([p for p in photos if not p.error], args.burst_gap, args.scene_gap, args.similarity)
    score_local(photos, args)
    print(t("cull.msg.analyzed", s=f"{time.time() - t0:.0f}"))
    if args.ai:
        review(photos, previews, out, args)
    previews.clear()
    SIGS.clear()

    prev_org = restore_manual(photos, out)
    finalize(photos, args)
    photos.sort(key=lambda p: (p.time, p.name))
    written = write_marks(photos, args)
    trashed_files = trash_rejects(photos, src, args)
    organized = organize_step(photos, src, prev_org, args)

    meta = {"src": str(src), "version": VERSION, "dry_run": args.dry_run, "no_xmp": args.no_xmp,
            "jpeg_embed": not args.no_jpeg_embed, "xmp_all": args.xmp_all,
            "xmp": 0 if (args.no_xmp or args.dry_run) else written, "organized": organized,
            "scoring": {"pick_ai": args.pick_ai, "pick_local": args.pick_local, "weights": args.weights}}
    write_report(photos, out, meta)
    res = summarize(photos, out, meta)

    print("\n" + t("cull.msg.result", **{k: res[k] for k in ("pick", "moment", "usable", "reject", "error", "bursts", "pairs")}))
    if args.no_xmp:
        print(t("cull.msg.no_xmp"))
    elif args.dry_run:
        print(t("cull.msg.dry_xmp", n=written))
    else:
        print(t("cull.msg.xmp_done_embed" if not args.no_jpeg_embed else "cull.msg.xmp_done", n=written))
    if trashed_files:
        print(t("cull.msg.trashed", n=trashed_files))
    print(t("cull.msg.report", path=out / "report.html"))
    _report("done", 1, 1)
    return res
