from __future__ import annotations

import argparse
from pathlib import Path

from .. import i18n
from ..version import VERSION
from .ai.providers import PROVIDERS
from .pipeline import run
from .scoring import PICK_AI, PICK_LOCAL, parse_weights
from .state import CUSTOM_BASE


def main(argv=None, confirm=None):
    """命令行入口（图形界面也在自己的进程里调用它）。--lang 只在这一次运行里生效。"""
    saved = i18n._override
    try:
        return _main(argv, confirm)
    finally:
        i18n.set_override(saved)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="cull.py", description="照片筛选：本地技术评分（最高 6 分）＋可选 AI 细评（6–10 分），"
                                 "RAW＋JPEG 同步标记，输出 XMP 和网页报告。")
    ap.add_argument("folder", type=Path, help="照片文件夹")
    ap.add_argument("-r", "--recursive", action="store_true", help="包含子文件夹")
    ap.add_argument("-o", "--out", type=Path, help="报告输出目录（默认：照片文件夹/photo-cull-report）")
    ap.add_argument("--ai", action="store_true", help="对入选照片调用 AI 细评（6 分以上只由 AI 给出）")
    ap.add_argument("--provider", choices=list(PROVIDERS), default="claude",
                    help="细评用哪家：claude／openai（ChatGPT）／grok／gemini／deepseek／custom（OpenAI 兼容接口，配合 --base-url）")
    ap.add_argument("--model", help="细评模型（默认：" + "／".join(v["default"] for v in PROVIDERS.values() if v["default"]) + "）")
    ap.add_argument("--base-url", help="--provider custom 时的接口地址，例如 https://dashscope.aliyuncs.com/compatible-mode/v1")
    ap.add_argument("--lang", choices=list(i18n.LANGS), help="输出语言（报告、日志、AI 评语）：" + "／".join(i18n.LANGS))
    ap.add_argument("--ai-alts", action="store_true", help="连拍里没被选中的帧也送去细评（更贵）")
    ap.add_argument("--yes", action="store_true", help="不再询问，直接调用 API／执行删除")
    ap.add_argument("--no-xmp", action="store_true", help="只出报告，不写任何星级")
    ap.add_argument("--no-jpeg-embed", action="store_true", help="不把星级写进 JPEG 文件内嵌 XMP")
    ap.add_argument("--xmp-all", action="store_true", help="没有 RAW 的 JPEG／HEIC 也写边车 XMP（Capture One 会读）")
    ap.add_argument("--dry-run", action="store_true", help="演练：不写任何 XMP，只生成报告")
    ap.add_argument("--trash-rejects", action="store_true", help="把淘汰的照片（含配对文件）移到废纸篓")
    ap.add_argument("--organize", metavar="DIR", nargs="?", const="", help="评分后整理到输出文件夹（不写路径时为 照片文件夹/整理输出）")
    ap.add_argument("--by-result", action="store_true", help="整理时按 保留／淘汰 分文件夹")
    ap.add_argument("--by-category", action="store_true", help="整理时 保留 里再分 精选／连拍瞬间／可用")
    ap.add_argument("--by-format", action="store_true", help="整理时按 JPEG／RAW 分文件夹")
    ap.add_argument("--rename", action="store_true", help="整理时重命名为 分数_机型_原文件名（只改输出里的文件）")
    ap.add_argument("--move", action="store_true", help="整理时移动而不是复制（原文件夹里就没有了）")
    ap.add_argument("--burst-gap", type=float, default=15, help="连拍：间隔不超过几秒且画面相近（默认 15）")
    ap.add_argument("--scene-gap", type=float, default=60, help="同场景重拍：间隔不超过几秒且画面很像（默认 60）")
    ap.add_argument("--similarity", type=float, default=0.6, help="同场景相似度阈值 0–1，越大越严格（默认 0.6）")
    ap.add_argument("--blur-warn", type=float, default=0.58, help="模糊度超过此值提示“可能失焦／抖动”（默认 0.58）")
    ap.add_argument("--blur-reject", type=float, default=0.75, help="模糊度超过此值直接淘汰（默认 0.75）")
    ap.add_argument("--clip-high", type=float, default=0.04, help="高光溢出提示阈值（默认 4%%）")
    ap.add_argument("--clip-low", type=float, default=0.30, help="暗部死黑提示阈值（默认 30%%）")
    ap.add_argument("--pick-ai", type=float, default=PICK_AI, help=f"精选线：AI 细评过的照片（10 分制，默认 {PICK_AI}）")
    ap.add_argument("--pick-local", type=float, default=PICK_LOCAL, help=f"精选线：只有本地分的照片（本地最高 6，默认 {PICK_LOCAL}）")
    ap.add_argument("--weights", help="精彩帧权重，例如 sharp=0.35,eyes=0.25,smile=0.1,exposure=0.15,subject=0.15（没写的项用默认）")
    ap.add_argument("--workers", type=int, default=4, help="并行数（默认 4）")
    ap.add_argument("--version", action="version", version=VERSION)
    return ap


def _main(argv=None, confirm=None):
    args = build_parser().parse_args(argv)
    args.confirm = confirm
    args.weights = parse_weights(args.weights)
    if args.lang:
        i18n.set_override(args.lang)
    if args.base_url:
        CUSTOM_BASE["custom"] = args.base_url.strip()
    return run(args)
