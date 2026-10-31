from __future__ import annotations

import re
from pathlib import Path

import numpy as np

from ..i18n import t
from .color import PP_TO_SRGB, mat, srgb_to

# LUT 使用范围（当前设定）：
#  · 输入空间统一为 sRGB，对应索尼「ST 标准」／徕卡「STD」的机内画面
#  · 素材库只列出下面这些子文件夹（相对素材库根目录）；根目录里没有这些文件夹时列出全部
#  · 相机 Log（S-Log3 等）转换暂不启用
ENABLE_LOG = False


# ───────────────────────── 相机 Log 编码（套 Log LUT 用） ─────────────────────────

def _slog3(x):
    return np.where(x >= 0.01125, (420.0 + np.log10((np.maximum(x, 0) + 0.01) / 0.19) * 261.5) / 1023.0,
                    (x * (171.2102946929 - 95.0) / 0.01125 + 95.0) / 1023.0)


def _vlog(x):
    return np.where(x < 0.01, 5.6 * x + 0.125, 0.241514 * np.log10(np.maximum(x, 0) + 0.00873) + 0.598206)


def _flog2(x):
    return np.where(x >= 0.000889, 0.245281 * np.log10(5.555556 * np.maximum(x, 0) + 0.064829) + 0.384316,
                    8.799461 * x + 0.092864)


def _applelog(x):
    r0, rt, c, b, g, d = -0.05641088, 0.01, 47.28711236, 0.00964052, 0.08550479, 0.69336945
    return np.where(x >= rt, g * np.log2(np.maximum(x, 0) + b) + d,
                    np.where(x >= r0, c * (x - r0) ** 2, 0.0))


def _dlog(x):
    return np.where(x <= 0.0078, 6.025 * x + 0.0929, np.log10(np.maximum(x, 0) * 0.9892 + 0.0108) * 0.256663 + 0.584555)


LOG_SPACES = {
    "srgb": {"name": "sRGB"},          # 显示名见语言包 edit.space.srgb
    "slog3": {"name": "Sony S-Log3／S-Gamut3.Cine", "gamut": "sgamut3cine", "f": _slog3},
    "vlog": {"name": "Panasonic V-Log／V-Gamut", "gamut": "vgamut", "f": _vlog},
    "flog2": {"name": "Fujifilm F-Log2／F-Gamut", "gamut": "rec2020", "f": _flog2},
    "applelog": {"name": "Apple Log／Rec.2020", "gamut": "rec2020", "f": _applelog},
    "dlog": {"name": "DJI D-Log／D-Gamut", "gamut": "dgamut", "f": _dlog},
}
SUPPORTED_LOG = [
    (r"s-?log3", "slog3"), (r"v-?log", "vlog"), (r"f-?log2(?!c)", "flog2"), (r"apple-?\s?log(?!2)", "applelog"),
    (r"(?<![a-z])d-?log(?!m|\s?m\b)", "dlog"),
]
OTHER_LOG = [r"s-?log2", r"s-?log(?!\d)", r"l-?log", r"n-?log", r"logc", r"log3g10", r"bmdfilm", r"i-?log",
             r"mi-?log", r"f-?log(?!2)", r"f-?log2c", r"canon\s?log", r"log\s?[23]\b", r"dlogm", r"d-?log\s?m",
             r"apple-?\s?log2"]


def active_spaces() -> dict:
    """界面里可选的 LUT 输入空间。"""
    return {k: (t("edit.space.srgb") if k == "srgb" else v["name"]) for k, v in LOG_SPACES.items() if ENABLE_LOG or k == "srgb"}


def guess_space(path: str) -> tuple[str, str]:
    """根据文件名／所在文件夹猜 LUT 的输入空间。返回 (space, 提示)。"""
    sp, warn = _guess_space(path)
    if not ENABLE_LOG and sp != "srgb":
        return "srgb", t("edit.warn.log_disabled")
    return sp, warn


def _guess_space(path: str) -> tuple[str, str]:
    s = path.lower().replace("_", "-")
    name = Path(path).name.lower().replace("_", "-")
    fv = "fvpro" in s.replace(" ", "")
    if fv and re.search(r"/print/", s):
        return "srgb", t("edit.warn.print_lut")
    sp = next((spc for pat, spc in SUPPORTED_LOG if re.search(pat, name)), None)
    if sp is None:   # 文件名没写，再看所在文件夹（例如 “某相机Log版/SLog3/xxx.cube”）
        parent = str(Path(s).parent)
        if not any(re.search(pat, name) for pat in OTHER_LOG):
            sp = next((spc for pat, spc in SUPPORTED_LOG if re.search(pat, parent)), None)
            if sp is None and any(re.search(pat, parent) for pat in OTHER_LOG):
                return "srgb", t("edit.warn.other_log")
    if sp is None and any(re.search(pat, name) for pat in OTHER_LOG):
        return "srgb", t("edit.warn.other_log")
    if sp and fv and re.search(r"/negative/", s):
        return sp, t("edit.warn.negative_lut")
    return sp or "srgb", ""


def log_encode(lin_pp: np.ndarray, space: str) -> np.ndarray:
    info = LOG_SPACES[space]
    M = srgb_to(info["gamut"]) @ PP_TO_SRGB
    return np.clip(info["f"](mat(lin_pp, M)), 0, 1).astype(np.float32)
