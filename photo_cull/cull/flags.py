from __future__ import annotations

import re

from ..i18n import t

# 问题标记在 results.json 里保存为代码（blur、clip_high:0.052…），显示时按当前语言翻译。
# 1.5 及以前保存的是中文句子，载入旧结果时转换成代码。
FLAG_LEGACY = [(r"^失焦或模糊$", "blur"), (r"^可能失焦／抖动$", "soft"), (r"^严重欠曝$", "under"),
               (r"^严重过曝$", "over"), (r"^高光溢出 (\d+)%$", "clip_high"), (r"^暗部死黑 (\d+)%$", "clip_low"),
               (r"^可能闭眼／侧脸$", "eyes"), (r"^星级未写入：(.*)$", "xmp_fail")]


def flag_code(f: str) -> str:
    for pat, code in FLAG_LEGACY:
        m = re.match(pat, f)
        if m:
            if code in ("clip_high", "clip_low"):
                return f"{code}:{int(m.group(1)) / 100:.3f}"
            return f"{code}:{m.group(1)}" if code == "xmp_fail" else code
    return f


def flag_text(code: str, lang: str | None = None) -> str:
    name, _, val = code.partition(":")
    if name in ("clip_high", "clip_low"):
        try:
            return t("flag." + name, lang, pct=f"{float(val):.0%}")
        except ValueError:
            pass
    if name == "xmp_fail":
        return t("flag.xmp_fail", lang, msg=val)
    key = "flag." + name
    text = t(key, lang)
    return code if text == key else text
