from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import sys
import time
from pathlib import Path

from .. import i18n
from ..i18n import t
from ..version import VERSION
from .ai.providers import PROVIDERS
from .ai.review import ai_review
from .analysis import SIGS
from .grouping import group_bursts
from .organize import organize, result_dirs
from .pipeline import collect, process_one
from .report import load_results, summarize, write_report
from .scoring import assign_ratings, score_local
from .state import CANCEL, CUSTOM_BASE, Cancelled, _report
from .trash import trash_photo
from .xmp import apply_marks


def main(argv=None, confirm=None):
    """命令行入口（图形界面也在自己的进程里调用它）。--lang 只在这一次运行里生效。"""
    saved = i18n._override
    try:
        return _main(argv, confirm)
    finally:
        i18n.set_override(saved)


def _main(argv=None, confirm=None):
    ap = argparse.ArgumentParser(prog="cull.py", description="照片筛选：本地技术评分＋可选 AI 细评，RAW＋JPEG 同步标记，输出 XMP 和网页报告。")
    ap.add_argument("folder", type=Path, help="照片文件夹")
    ap.add_argument("-r", "--recursive", action="store_true", help="包含子文件夹")
    ap.add_argument("-o", "--out", type=Path, help="报告输出目录（默认：照片文件夹/photo-cull-report）")
    ap.add_argument("--ai", action="store_true", help="对入围照片调用 AI 细评")
    ap.add_argument("--provider", choices=list(PROVIDERS), default="claude",
                    help="细评用哪家：claude／openai（ChatGPT）／grok／gemini／deepseek／custom（OpenAI 兼容接口，配合 --base-url）")
    ap.add_argument("--model", help="细评模型（默认：" + "／".join(v["default"] for v in PROVIDERS.values() if v["default"]) + "）")
    ap.add_argument("--base-url", help="--provider custom 时的接口地址，例如 https://dashscope.aliyuncs.com/compatible-mode/v1")
    ap.add_argument("--lang", choices=list(i18n.LANGS), help="输出语言（报告、日志、AI 评语）：zh-CN／en／ja，默认跟随界面设置或系统语言")
    ap.add_argument("--ai-alts", action="store_true", help="连拍备选也送去细评（更贵）")
    ap.add_argument("--yes", action="store_true", help="不再询问，直接调用 API／执行删除")
    ap.add_argument("--no-xmp", action="store_true", help="只出报告，不写任何星级")
    ap.add_argument("--no-jpeg-embed", action="store_true", help="不把星级写进 JPEG 文件内嵌 XMP")
    ap.add_argument("--xmp-all", action="store_true", help="没有 RAW 的 JPEG／HEIC 也写边车 XMP（Capture One 会读）")
    ap.add_argument("--dry-run", action="store_true", help="演练：不写任何 XMP，只生成报告")
    ap.add_argument("--trash-rejects", action="store_true", help="把淘汰的照片（含配对文件）移到废纸篓")
    ap.add_argument("--organize", metavar="DIR", nargs="?", const="", help="评分后整理到输出文件夹（不写路径时为 照片文件夹/整理输出）")
    ap.add_argument("--by-result", action="store_true", help="整理时按 保留／淘汰 分文件夹")
    ap.add_argument("--by-format", action="store_true", help="整理时按 JPEG／RAW 分文件夹")
    ap.add_argument("--rename", action="store_true", help="整理时重命名为 星级_机型_原文件名（只改输出里的文件）")
    ap.add_argument("--move", action="store_true", help="整理时移动而不是复制（原文件夹里就没有了）")
    ap.add_argument("--burst-gap", type=float, default=15, help="连拍：间隔不超过几秒且画面相近（默认 15）")
    ap.add_argument("--scene-gap", type=float, default=60, help="同场景重拍：间隔不超过几秒且画面很像（默认 60）")
    ap.add_argument("--similarity", type=float, default=0.6, help="同场景相似度阈值 0–1，越大越严格（默认 0.6）")
    ap.add_argument("--blur-warn", type=float, default=0.58, help="模糊度超过此值提示“可能失焦／抖动”（默认 0.58）")
    ap.add_argument("--blur-reject", type=float, default=0.75, help="模糊度超过此值直接淘汰（默认 0.75）")
    ap.add_argument("--clip-high", type=float, default=0.04, help="高光溢出提示阈值（默认 4%%）")
    ap.add_argument("--clip-low", type=float, default=0.30, help="暗部死黑提示阈值（默认 30%%）")
    ap.add_argument("--workers", type=int, default=4, help="并行数（默认 4）")
    ap.add_argument("--version", action="version", version=VERSION)
    args = ap.parse_args(argv)
    args.confirm = confirm
    jpeg_embed = not args.no_jpeg_embed
    if args.lang:
        i18n.set_override(args.lang)
    if args.base_url:
        CUSTOM_BASE["custom"] = args.base_url.strip()

    src = args.folder.expanduser().resolve()
    if not src.is_dir():
        sys.exit(t("cull.msg.no_folder", path=src))
    out = (args.out.expanduser().resolve() if args.out else src / "photo-cull-report")
    thumbs = out / "thumbs"
    thumbs.mkdir(parents=True, exist_ok=True)

    groups = collect(src, args.recursive)
    if not groups:
        sys.exit(t("cull.msg.no_photos"))
    npairs = sum(1 for g in groups if len(g) > 1)
    print(t("cull.msg.start", n=len(groups), files=sum(len(g) for g in groups), pairs=npairs))
    t0 = time.time()
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
    group_bursts([p for p in photos if not p.error], args.burst_gap, args.scene_gap, args.similarity)
    score_local(photos, args)
    print(t("cull.msg.analyzed", s=f"{time.time()-t0:.0f}"))

    if args.ai:
        tiers = {"candidate", "alt"} if args.ai_alts else {"candidate"}
        items = [(p, previews[p.path]) for p in photos if p.tier in tiers and p.path in previews]
        cache_path = out / "ai_cache.json"
        cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
        ai_review(items, args, cache, cache_path)
        cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    previews.clear()
    SIGS.clear()

    # 重新筛选同一文件夹时，保留上次在报告里手动调整过的星级
    prev_org = None
    if (out / "results.json").is_file():
        try:
            prev, prev_meta = load_results(out)
            prev_org = (prev_meta or {}).get("organized")
            manual = {q.path: q for q in prev if q.manual and not q.trashed}
            for p in photos:
                q = manual.get(p.path)
                if q:
                    p.stars, p.label, p.manual = q.stars, q.label, True
            if manual:
                print(t("cull.msg.kept_manual", n=sum(1 for p in photos if p.manual)))
        except Exception:
            pass
    assign_ratings(photos)
    photos.sort(key=lambda p: (p.time, p.name))

    written = 0
    _report("xmp", 0, 1)
    if not args.no_xmp:
        for p in photos:
            if p.tier == "error":
                continue
            try:
                if apply_marks(p, args.dry_run, jpeg_embed, args.xmp_all):
                    written += 1
            except Exception as ex:
                p.flags.append(f"xmp_fail:{ex}")

    trashed_files = 0
    if args.trash_rejects and not args.dry_run:
        rejects = [p for p in photos if p.tier == "reject"]
        if rejects and (args.yes or input(t("cull.msg.trash_ask", n=len(rejects))).strip().lower() == "y"):
            for p in rejects:
                trashed_files += len(trash_photo(p, src))

    organized = None
    if args.organize is None and prev_org and not prev_org.get("dry_run") and Path(prev_org.get("out", "")).is_dir():
        # 这次没勾整理：沿用上次的整理记录，之后在报告里改星级、删除仍会同步到输出文件夹
        organized = {k: v for k, v in prev_org.items() if k != "plan"}
        print(t("cull.msg.org_kept_state", out=organized["out"]))
    if args.organize is not None:
        target = Path(args.organize).expanduser() if args.organize else src / t("cull.org.default_dir")
        if not target.is_absolute():
            target = src / target
        dirs = result_dirs(prev_org) if prev_org and Path(prev_org.get("out", "")) == target.resolve() else None
        organized = organize(photos, target, args.by_result, args.by_format, args.rename, args.move, args.dry_run, dirs)
        verb = t("cull.org.verb_move" if args.move else "cull.org.verb_copy")
        if args.dry_run:
            print(t("cull.msg.org_dry", n=organized["photos"], files=len(organized["plan"]), verb=verb, out=target))
        else:
            print(t("cull.msg.org_done", n=organized["photos"], files=organized["files"], verb=verb, out=target,
                    kept=organized["kept"], rejected=organized["rejected"]))
        for e in organized["errors"][:10]:
            print("  " + t("cull.org.failed") + " " + e)

    meta = {"src": str(src), "version": VERSION, "dry_run": args.dry_run, "no_xmp": args.no_xmp,
            "jpeg_embed": jpeg_embed, "xmp_all": args.xmp_all, "xmp": 0 if (args.no_xmp or args.dry_run) else written,
            "organized": organized}
    write_report(photos, out, meta)
    res = summarize(photos, out, meta)

    print("\n" + t("cull.msg.result", **{k: res[k] for k in ("candidate", "alt", "reject", "error", "top", "pairs")}))
    if args.no_xmp:
        print(t("cull.msg.no_xmp"))
    elif args.dry_run:
        print(t("cull.msg.dry_xmp", n=written))
    else:
        print(t("cull.msg.xmp_done_embed" if jpeg_embed else "cull.msg.xmp_done", n=written))
    if trashed_files:
        print(t("cull.msg.trashed", n=trashed_files))
    print(t("cull.msg.report", path=out / "report.html"))
    _report("done", 1, 1)
    return res


if __name__ == "__main__":
    main()
