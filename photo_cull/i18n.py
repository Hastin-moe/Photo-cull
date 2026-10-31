"""多语言（简体中文／English／日本語／한국어）。

文字都放在 locales/<语言>.json 里，按模块分组（common、cull、report、edit、server…），
程序里用 t("cull.run") 取当前语言的文字，网页用同一份语言包（gui.py 在页面里注入）。
缺少的条目依次回退到英文、简体中文，最后显示键名本身，方便发现漏翻。

当前语言的来源（优先级从高到低）：
  1. set_override()（命令行 --lang）
  2. 环境变量 PHOTO_CULL_LANG
  3. ~/.photo-cull/lang.json（界面右上角切换语言时保存，两个程序共用）
  4. 系统语言
"""
from __future__ import annotations

from .paths import LOCALE_DIR, LANG_FILE

import json
import locale
import os
import subprocess
import sys
import threading

LANGS = {"zh-CN": "简体中文", "en": "English", "ja": "日本語", "ko": "한국어"}
SOURCE = "zh-CN"                       # 原文语言：新文字先写进 zh-CN.json
CONFIG = LANG_FILE

_lock = threading.Lock()
_tables: dict = {}                     # 语言 → 扁平字典（已合并回退）
_override: str | None = None
_saved = (None, None)                  # (mtime, lang)
_system: str | None = None


def normalize(code) -> str | None:
    """各种写法（zh_CN.UTF-8、zh-Hans、ja-JP、en_US…）→ 支持的语言代码；不支持返回 None。"""
    c = str(code or "").strip().replace("_", "-").lower()
    if not c:
        return None
    if c.startswith("zh"):
        return "zh-CN"
    if c.startswith("ja"):
        return "ja"
    if c.startswith("ko"):
        return "ko"
    if c.startswith("en"):
        return "en"
    return None


def _flatten(d: dict, prefix: str = "", out: dict | None = None) -> dict:
    out = {} if out is None else out
    for k, v in d.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            _flatten(v, key, out)
        else:
            out[key] = v
    return out


def load_raw(lang: str) -> dict:
    """一个语言文件本身（扁平、不含回退），检查工具和测试用。"""
    f = LOCALE_DIR / f"{lang}.json"
    try:
        return _flatten(json.loads(f.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return {}


def strings(lang: str | None = None) -> dict:
    """lang 的完整字典：缺的条目用英文、再用简体中文补齐。"""
    lang = lang if lang in LANGS else current()
    with _lock:
        if lang not in _tables:
            merged = {}
            for code in [c for c in (SOURCE, "en") if c != lang] + [lang]:    # 后面的覆盖前面的
                merged.update(load_raw(code))
            _tables[lang] = merged
        return _tables[lang]


def reload():
    """语言文件改过之后（开发时）清掉缓存。"""
    with _lock:
        _tables.clear()


def t(key: str, lang: str | None = None, **kw) -> str:
    s = strings(lang).get(key, key)
    if kw:
        try:
            return s.format(**kw)
        except (KeyError, IndexError, ValueError):
            return s
    return s


def _detect_system() -> str:
    if sys.platform == "darwin":
        try:
            out = subprocess.run(["defaults", "read", "-g", "AppleLanguages"], capture_output=True,
                                 text=True, timeout=2).stdout
            for part in out.replace("(", " ").replace(")", " ").replace(",", " ").split():
                v = normalize(part.strip('"'))
                if v:
                    return v
        except Exception:
            pass
    for var in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        base = os.environ.get(var, "").split(":")[0].split(".")[0]
        if base in ("", "C", "POSIX"):
            continue
        return normalize(base) or "en"          # 其他语言的系统用英文
    if os.name == "nt":
        try:
            import ctypes
            lid = ctypes.windll.kernel32.GetUserDefaultUILanguage()   # type: ignore[attr-defined]
            v = normalize(locale.windows_locale.get(lid, ""))
            if v:
                return v
        except Exception:
            pass
    try:
        v = normalize((locale.getlocale()[0] or ""))
        if v:
            return v
    except Exception:
        pass
    return "en"


def system_lang() -> str:
    global _system
    if _system is None:
        _system = _detect_system()
    return _system


def saved_lang() -> str | None:
    """界面里选过的语言（文件改了就重新读，两个程序之间同步）。"""
    global _saved
    try:
        m = CONFIG.stat().st_mtime
    except OSError:
        return None
    if _saved[0] != m:
        try:
            v = normalize(json.loads(CONFIG.read_text(encoding="utf-8")).get("lang"))
        except (OSError, ValueError, AttributeError):
            v = None
        _saved = (m, v)
    return _saved[1]


def current() -> str:
    return _override or normalize(os.environ.get("PHOTO_CULL_LANG")) or saved_lang() or system_lang()


def set_override(code):
    global _override
    _override = normalize(code)


def save_lang(code) -> str:
    v = normalize(code)
    if not v:
        raise ValueError(t("server.bad_lang"))
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG.with_suffix(".tmp")
    tmp.write_text(json.dumps({"lang": v}), encoding="utf-8")
    tmp.replace(CONFIG)
    return v


def html_lang(lang: str | None = None) -> str:
    return {"zh-CN": "zh-CN", "en": "en", "ja": "ja", "ko": "ko"}[lang or current()]


def bundle(prefixes=None, lang: str | None = None) -> dict:
    """给网页的语言包：{"lang", "langs", "dict"}；prefixes 限定只带哪些分组（报告页用）。"""
    lang = lang if lang in LANGS else current()
    d = strings(lang)
    if prefixes:
        d = {k: v for k, v in d.items() if k.split(".", 1)[0] in prefixes}
    return {"lang": lang, "langs": LANGS, "dict": d}
