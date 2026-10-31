from __future__ import annotations

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None

from pathlib import Path

import numpy as np
from PIL import Image

from ..i18n import t
from ..imaging.exif import _ratio, read_exif
from ..version import VERSION
from .decode import decode, resize_lin
from .params import STRIP_ROWS, normalize_params
from .render import WORKERS, Context, clarity_margin, render_parallel

# ───────────────────────── 导出 ─────────────────────────

def _exif_for(path: Path):
    exif = Image.Exif()
    try:
        e = read_exif(path)
    except Exception:
        return exif
    from PIL.TiffImagePlugin import IFDRational
    if e.get("model"):
        exif[0x0110] = e["model"]
    exif[0x0131] = f"photo-cull {VERSION}"
    ifd = exif.get_ifd(0x8769)
    if e.get("dt"):
        exif[0x0132] = e["dt"]
        ifd[0x9003] = e["dt"]
    try:
        if e.get("shutter"):
            s = e["shutter"]
            ifd[0x829A] = IFDRational(1, int(s.split("/")[1])) if "/" in s else IFDRational(float(s))
        if e.get("fnum"):
            ifd[0x829D] = IFDRational(float(_ratio(e["fnum"])))
        if e.get("iso"):
            ifd[0x8827] = int(float(e["iso"].split()[0]))
        if e.get("focal"):
            ifd[0x920A] = IFDRational(float(_ratio(e["focal"])))
        if e.get("lens"):
            ifd[0xA434] = e["lens"]
    except (ValueError, ZeroDivisionError, IndexError):
        pass
    return exif


def _srgb_icc():
    try:
        from PIL import ImageCms
        return ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    except Exception:
        return None


def export(path: str, P: dict, out_dir: str | None = None, fmt: str = "jpeg", quality: int = 95,
           long_edge: int = 0, progress=None) -> str:
    """全分辨率解码并分条渲染，避免大像素机身占满内存。"""
    src = Path(path)
    P = normalize_params(P)
    if progress:
        progress(t("edit.export.decoding"), 0.05)
    lin, info = decode(str(src), half=False, as_float=False)
    if long_edge and max(lin.shape[:2]) > long_edge:
        lin = resize_lin(lin, long_edge)
    H, W = lin.shape[:2]
    ctx = Context(info, P)
    out = np.empty((H, W, 3), np.uint16 if fmt == "tiff" else np.uint8)
    margin = clarity_margin(P, (H, W))
    # 清晰度的模糊半径按整张图计算，分条渲染时给每条留足边距，保证和预览一致；每条内部再多线程
    rows = list(range(0, H, STRIP_ROWS))
    for k, y0 in enumerate(rows):
        y1 = min(H, y0 + STRIP_ROWS)
        a, b = max(0, y0 - margin), min(H, y1 + margin)
        strip = render_parallel(lin[a:b], info, P, ctx, full_shape=(H, W), y_off=a, parts=min(WORKERS, 4))
        piece = strip[y0 - a:y0 - a + (y1 - y0)]
        out[y0:y1] = (piece * (65535 if fmt == "tiff" else 255) + 0.5).astype(out.dtype)
        if progress:
            progress(t("edit.export.strip", k=k + 1, n=len(rows)), 0.1 + 0.85 * (k + 1) / len(rows))
    od = Path(out_dir).expanduser() if out_dir else src.parent / "photo-cull-export"
    od.mkdir(parents=True, exist_ok=True)
    ext = ".tif" if fmt == "tiff" else ".jpg"
    dest = od / f"{src.stem}_edit{ext}"
    n = 2
    while dest.exists():
        dest = od / f"{src.stem}_edit-{n}{ext}"
        n += 1
    if fmt == "tiff":
        if cv2 is None or not cv2.imwrite(str(dest), out[..., ::-1]):
            raise RuntimeError(t("edit.err.tiff_write"))
    else:
        img = Image.fromarray(out)
        kw = {"quality": int(quality), "subsampling": 0 if quality >= 90 else 2, "exif": _exif_for(src)}
        icc = _srgb_icc()
        if icc:
            kw["icc_profile"] = icc
        img.save(dest, "JPEG", **kw)
    if progress:
        progress(t("edit.export.finished"), 1.0)
    return str(dest)
