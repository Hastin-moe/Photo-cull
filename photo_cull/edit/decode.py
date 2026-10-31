from __future__ import annotations

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None

from pathlib import Path

import numpy as np

from ..i18n import t
from ..imaging.formats import RAW_EXT
from ..imaging.preview import load_preview
from ..imaging.tiffraw import TiffRaw
from .color import SRGB_TO_PP, mat, srgb_decode
from .params import PREVIEW_SIDE

# ───────────────────────── 解码 ─────────────────────────

def _baseline_exposure(path: Path) -> float:
    try:
        with TiffRaw(path) as t:
            v = t.tag(0xC62A, {"ifd0"})
            if isinstance(v, list):
                v = v[0]
            return float(v) if v is not None else 0.0
    except Exception:
        return 0.0


def decode(path: str, half: bool = True, as_float: bool = True) -> tuple[np.ndarray, dict]:
    """返回 (线性 ProPhoto 图像, 信息)。RAW 用 LibRaw；失败时退回机内预览并标注。
    as_float=False 时 RAW 以 uint16 返回（导出 6000 万像素时省一半以上内存），使用前按条转换。"""
    p = Path(path)
    ext = p.suffix.lower()
    info = {"path": str(p), "name": p.name, "mode": "image", "warning": "", "base_ev": 0.0}
    if ext in RAW_EXT:
        try:
            import rawpy
            with rawpy.imread(str(p)) as raw:
                rgb = raw.postprocess(gamma=(1, 1), no_auto_bright=True, output_bps=16, use_camera_wb=True,
                                      output_color=rawpy.ColorSpace.ProPhoto, half_size=half,
                                      highlight_mode=rawpy.HighlightMode.Blend)
                info["camera"] = f"{raw.color_desc.decode(errors='ignore')}"
            lin = rgb.astype(np.float32) / 65535.0 if as_float else rgb
            info["mode"] = "raw"
            # DNG 的 BaselineExposure ＋ 通用的 RAW 起始提亮（LibRaw 输出比相机直出暗约 0.7 档）
            info["base_ev"] = round(_baseline_exposure(p) + 0.7, 3)
            return lin, info
        except ImportError:
            info["warning"] = t("edit.warn.no_rawpy")
        except Exception as e:
            info["warning"] = t("edit.warn.raw_failed", err=f"{type(e).__name__}: {e}")
        img = load_preview(p, PREVIEW_SIDE if half else None)
        info["mode"] = "preview"
    else:
        # 预览只需要长边 2880：大 JPEG 直接按 1/2、1/4 缩小解码，快好几倍；导出（half=False）仍用全尺寸
        img = load_preview(p, PREVIEW_SIDE if half else None)
    arr = np.asarray(img.convert("RGB"), dtype=np.float32) / 255.0
    lin = mat(srgb_decode(arr), SRGB_TO_PP)
    return lin, info


def resize_lin(lin: np.ndarray, side: int) -> np.ndarray:
    h, w = lin.shape[:2]
    s = side / max(h, w)
    if s >= 1:
        return lin
    return cv2.resize(np.ascontiguousarray(lin), (max(1, round(w * s)), max(1, round(h * s))), interpolation=cv2.INTER_AREA)
