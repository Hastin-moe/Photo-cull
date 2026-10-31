"""检查语言包：三种语言的键是否一致、占位符是否一致、代码里用到的键是否都存在。

    python3 tools/check_i18n.py

新增或修改界面文字时请运行一次；有问题会列出来并以非零状态退出（适合放进 CI）。
添加新语言：复制 locales/en.json 为 locales/<代码>.json 翻译，再在 photo_cull/i18n.py 的 LANGS 里登记。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from photo_cull import i18n  # noqa: E402

PH = re.compile(r"\{(\w+)\}")
# 代码里直接写出的键：t("x.y")、T("x.y")、data-i18n*="x.y"
USES = [
    (re.compile(r"""\bt\(\s*["']([a-z_]+\.[\w.]+)["']"""), ("*.py",)),
    (re.compile(r"""\bT\(\s*["']([a-z_]+\.[\w.]+)["']"""), ("*.js", "*.html")),
    (re.compile(r"""data-i18n(?:-html|-title|-placeholder)?=["']([a-z_]+\.[\w.]+)["']"""), ("*.html",)),
]
# 由程序拼出来的键（前缀＋变量），在这里登记对应的取值，用于检查
DYNAMIC = {
    "flag.": ["blur", "soft", "under", "over", "clip_high", "clip_low", "eyes", "xmp_fail"],
    "cat.": ["pick", "moment", "usable", "reject", "error"],
    "cull.org.folder.": ["keep", "reject", "pick", "moment", "usable", "group"],
    "common.stat.": ["total", "pairs", "bursts", "pick", "moment", "usable", "reject", "error", "trashed"],
    "genre.": ["portrait", "street", "landscape", "architecture", "event", "other"],
}


def main() -> int:
    langs = list(i18n.LANGS)
    tables = {lang: {k: v for k, v in i18n.load_raw(lang).items() if not k.startswith("_meta.")} for lang in langs}
    src = tables[i18n.SOURCE]
    problems = []
    for lang, tab in tables.items():
        for k in sorted(set(src) - set(tab)):
            problems.append(f"[{lang}] 缺少：{k}")
        for k in sorted(set(tab) - set(src)):
            problems.append(f"[{lang}] 多余（{i18n.SOURCE} 里没有）：{k}")
        for k in set(src) & set(tab):
            if sorted(set(PH.findall(src[k]))) != sorted(set(PH.findall(tab[k]))):
                problems.append(f"[{lang}] 占位符不一致：{k}")
    used = set()
    for pat, globs in USES:
        for g in globs:
            for f in ROOT.rglob(g):
                if ".git" in f.parts or "dist" in f.parts or f.parent.name == "tools" and f.name == "check_i18n.py":
                    continue
                used.update(pat.findall(f.read_text(encoding="utf-8", errors="replace")))
    for prefix, names in DYNAMIC.items():
        used.update(prefix + n for n in names)
    used = {k for k in used if not k.endswith(".")}          # 「前缀 ＋ 变量」拼出的键，见 DYNAMIC
    used -= {"common.file_manager", "common.trash"}            # gui.py 按系统从 *_mac／*_win 里选一个
    for k in sorted(used - set(src)):
        problems.append(f"代码里用到但语言包里没有：{k}")
    for p in problems:
        print("✗", p)
    print(f"{len(src)} 条文字，{len(langs)} 种语言（{', '.join(langs)}），代码直接引用 {len(used)} 个键。")
    print("没有问题。" if not problems else f"{len(problems)} 个问题。")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
