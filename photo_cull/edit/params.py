from __future__ import annotations

import json

from ..imaging.formats import RAW_EXT
from .logspace import ENABLE_LOG, LOG_SPACES

EDIT_EXT = RAW_EXT | {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".heic", ".heif", ".hif", ".webp"}
PREVIEW_SIDE = 2880          # 预览的最大清晰度（长边像素）；实际按界面显示大小和屏幕密度挑一档
PREVIEW_LEVELS = (1400, 1800, 2400, 2880)
FAST_RATIO = 0.45            # 拖动滑块时的预览：长边为当前档位的这个比例
STRIP_ROWS = 1024            # 导出时分条渲染，避免 6000 万像素一次性占满内存（每条内部再多线程）
EDIT_VERSION = 1

DEFAULT_PARAMS = {
    "version": EDIT_VERSION,
    "temp": 0, "tint": 0, "exposure": 0.0, "contrast": 0, "highlights": 0, "shadows": 0,
    "whites": 0, "blacks": 0, "clarity": 0, "vibrance": 0, "saturation": 0, "mono": False,
    "curve": {"rgb": [[0, 0], [1, 1]], "r": [[0, 0], [1, 1]], "g": [[0, 0], [1, 1]], "b": [[0, 0], [1, 1]]},
    "look": None,            # {"path": XMP, "amount": 0..2}
    "lut": None,             # {"path": .cube, "amount": 0..1, "space": "srgb"/"slog3"/...}
    "vignette": None,        # {"lens": "11874"/"11699"/"11141"/"11672", "level": "weak"/"mid"/"strong"}
}
SLIDERS = ["temp", "tint", "exposure", "contrast", "highlights", "shadows", "whites", "blacks",
           "clarity", "vibrance", "saturation"]


def normalize_params(p: dict | None) -> dict:
    out = json.loads(json.dumps(DEFAULT_PARAMS))
    if not isinstance(p, dict):
        return out
    for k in SLIDERS:
        try:
            v = float(p.get(k, out[k]))
            out[k] = max(-5.0, min(5.0, v)) if k == "exposure" else max(-100.0, min(100.0, v))
        except (TypeError, ValueError):
            pass
    out["mono"] = bool(p.get("mono", False))
    vg = p.get("vignette")
    if isinstance(vg, dict) and vg.get("lens") in LENSES:     # 1.3.1 的数字暗角不再沿用
        out["vignette"] = {"lens": vg["lens"], "level": vg.get("level") if vg.get("level") in VIG_LEVEL_IDS else "mid"}
    curve = p.get("curve") or {}
    for ch in ("rgb", "r", "g", "b"):
        pts = curve.get(ch)
        if isinstance(pts, list) and len(pts) >= 2:
            clean = []
            for pt in pts[:32]:
                try:
                    clean.append([min(1.0, max(0.0, float(pt[0]))), min(1.0, max(0.0, float(pt[1])))])
                except (TypeError, ValueError, IndexError):
                    pass
            if len(clean) >= 2:
                out["curve"][ch] = sorted(clean)
    for key, hi in (("look", 2.0), ("lut", 1.0)):
        v = p.get(key)
        if isinstance(v, dict) and v.get("path"):
            item = {"path": str(v["path"]), "amount": max(0.0, min(hi, float(v.get("amount", 1.0))))}
            if isinstance(v.get("name"), str):
                item["name"] = v["name"][:200]
            if key == "lut":
                item["space"] = v.get("space") if (ENABLE_LOG and v.get("space") in LOG_SPACES) else "srgb"
            out[key] = item
    return out


# 经典徕卡 M 镜头的暗角模拟（未经机身镜头校正的光学原貌）。镜头的显示名在语言包 edit.lens.<型号>。
# 徕卡数据表只以曲线图给出相对照度，没有公开数值，这里按各镜头的设计特点做近似：
#  · ev：四角比中心暗多少档；弱／中／强 分别对应 约 f/5.6、约 f/2.8、光圈全开 时的暗角
#  · p ：衰减曲线的形状（亮度损失 ∝ 距中心距离^p）；数值越小，暗角从越靠近中心的地方开始（大光圈、广角更明显）
LENSES = {
    "11874": {"stops": {"weak": "f/5.6", "mid": "f/2.8", "strong": "f/1.4"},
              "ev": {"weak": 0.6, "mid": 1.2, "strong": 2.2}, "p": 1.8},
    "11699": {"stops": {"weak": "f/5.6", "mid": "f/2.8", "strong": "f/2"},
              "ev": {"weak": 0.8, "mid": 1.3, "strong": 1.9}, "p": 2.0},
    "11141": {"stops": {"weak": "f/5.6", "mid": "f/2.8", "strong": "f/2"},
              "ev": {"weak": 0.5, "mid": 0.9, "strong": 1.4}, "p": 2.4},
    "11672": {"stops": {"weak": "f/5.6", "mid": "f/2.8", "strong": "f/2"},
              "ev": {"weak": 1.0, "mid": 1.6, "strong": 2.3}, "p": 1.9},
}
VIG_LEVEL_IDS = ("weak", "mid", "strong")
