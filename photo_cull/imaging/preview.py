from __future__ import annotations

import io
import struct as _st
from pathlib import Path

from PIL import Image, ImageOps

from ..i18n import t
from .formats import RAW_EXT, _ensure_heif
from .tiffraw import TiffRaw, raf_jpeg


def _fit(img: Image.Image, side: int) -> Image.Image:
    w, h = img.size
    s = side / max(w, h)
    if s < 1:
        img = img.resize((max(1, round(w * s)), max(1, round(h * s))), Image.LANCZOS)
    return img


_ORIENT = {2: [Image.Transpose.FLIP_LEFT_RIGHT], 3: [Image.Transpose.ROTATE_180], 4: [Image.Transpose.FLIP_TOP_BOTTOM],
           5: [Image.Transpose.TRANSPOSE], 6: [Image.Transpose.ROTATE_270], 7: [Image.Transpose.TRANSVERSE],
           8: [Image.Transpose.ROTATE_90]}


def open_scaled(src, min_side: int | None = None) -> tuple[Image.Image, tuple]:
    """打开图片；JPEG 且只需要长边 min_side 时，按 1/2、1/4、1/8 直接缩小解码（DCT 域，快且不失真）。
    返回 (图片, (原宽, 原高, 解码宽, 解码高))，交给 _with_full 换算旋转后的原尺寸。"""
    img = Image.open(src)
    w0, h0 = img.size
    if min_side and img.format == "MPO" and getattr(img, "n_frames", 1) > 1:
        # 索尼等相机的 JPEG 是 MPO：除了主图，还带一张约 1616 像素的预览图，够用时直接用它（快十几倍）
        orient = img.getexif().get(0x0112, 1) or 1
        best = None
        for k in range(1, img.n_frames):
            try:
                img.seek(k)
            except EOFError:
                break
            w, h = img.size
            if max(w, h) >= min_side and abs(w / h - w0 / h0) < 0.02 and (best is None or w < best[1]):
                best = (k, w)
        if best:
            img.seek(best[0])
            img.load()
            fr = img.copy()
            w1, h1 = fr.size
            if (fr.getexif().get(0x0112) or 1) == 1:      # 预览帧不带方向时，按主图的方向转正
                for op in _ORIENT.get(int(orient), []):
                    fr = fr.transpose(op)
                fr.info.pop("exif", None)
            return fr, (w0, h0, w1, h1)
        img.seek(0)
    if min_side and img.format in ("JPEG", "MPO") and img.mode in ("RGB", "L", "CMYK"):
        w, h = img.size
        s = min_side / max(w, h)
        if s < 0.5:
            img.draft(img.mode, (max(1, int(w * s)), max(1, int(h * s))))
    img.load()
    return img, (w0, h0, img.size[0], img.size[1])


def _with_full(img: Image.Image, dims: tuple) -> Image.Image:
    """记录原始尺寸（按方向旋转后的宽高），缩小解码时报告里仍显示真实像素数。"""
    w0, h0, w1, h1 = dims
    img.info["full_size"] = (w0, h0) if (img.size == (w1, h1) or w1 == h1) else (h0, w0)
    return img


def tiff_preview(path: Path, min_side: int | None = None) -> Image.Image | None:
    with TiffRaw(path) as t:
        orient = t.tag(0x112, {"ifd0"}) or 1
        cands = t.previews()
        if min_side:
            # 只需要小图（缩略图等）时，挑长边够用的最小那张内嵌预览（ARW 里有 8640 和 1616 两张）
            sized = []
            for data in cands:
                try:
                    sized.append((max(Image.open(io.BytesIO(data)).size), data))
                except Exception:
                    continue
            ok = sorted((sz, d) for sz, d in sized if sz >= min_side)
            cands = [d for _, d in ok] + [d for sz, d in sorted(sized, key=lambda x: -x[0]) if sz < min_side]
        for data in cands:
            try:
                img, dims = open_scaled(io.BytesIO(data), min_side)
            except Exception:
                continue
            if max(dims[:2]) < 600:
                continue
            own = img.getexif().get(0x0112, 1)
            if own != 1:
                img = ImageOps.exif_transpose(img)
            else:
                for op in _ORIENT.get(int(orient) if isinstance(orient, int) else 1, []):
                    img = img.transpose(op)
            return _with_full(img, dims)
    return None


def load_preview(path: Path, min_side: int | None = None) -> Image.Image:
    """返回 RGB 预览图。RAW 优先用机内嵌入的 JPEG（快、颜色接近机内直出）。
    min_side：只需要长边至少这么多像素时传入，大 JPEG 会缩小解码；img.info["full_size"] 记录原始尺寸。"""
    ext = path.suffix.lower()
    if ext == ".raf":
        try:
            img, dims = open_scaled(io.BytesIO(raf_jpeg(path)), min_side)
            img = ImageOps.exif_transpose(img)
            if max(dims[:2]) >= 600:
                return _with_full(img.convert("RGB"), dims)
        except (ValueError, OSError, _st.error):
            pass
    if ext in RAW_EXT:
        # 1) TIFF 结构直读内嵌预览（DNG／ARW／NEF 等，最快、无需 rawpy）
        try:
            img = tiff_preview(path, min_side)
            if img is not None:
                full = img.info["full_size"]
                img = img.convert("RGB")
                img.info["full_size"] = full
                return img
        except (ValueError, OSError, _st.error):
            pass
        # 2) 交给 rawpy（CR3 等非 TIFF 结构，或没有可用预览）
        try:
            import rawpy
        except ImportError:
            raise RuntimeError(t("cull.msg.need_rawpy"))
        with rawpy.imread(str(path)) as raw:
            img = None
            try:
                th = raw.extract_thumb()
                if th.format == rawpy.ThumbFormat.JPEG:
                    img, _r = open_scaled(io.BytesIO(th.data), min_side)
                    # 嵌入预览自带方向时以它为准
                    if img.getexif().get(0x0112, 1) != 1:
                        img = ImageOps.exif_transpose(img)
                    else:
                        img = _apply_flip(img, raw.sizes.flip)
                elif th.format == rawpy.ThumbFormat.BITMAP:
                    img = _apply_flip(Image.fromarray(th.data), raw.sizes.flip)
            except Exception:
                img = None
            if img is None or max(img.size) < 600:
                rgb = raw.postprocess(half_size=True, use_camera_wb=True, no_auto_bright=False, output_bps=8)
                img = Image.fromarray(rgb)  # postprocess 已处理方向
        return img.convert("RGB")
    if ext in {".heic", ".heif", ".hif"} and not _ensure_heif():
        raise RuntimeError(t("cull.msg.need_heif"))
    img, dims = open_scaled(path, min_side)
    img = ImageOps.exif_transpose(img)
    return _with_full(img.convert("RGB"), dims)


def _apply_flip(img: Image.Image, flip: int) -> Image.Image:
    # LibRaw flip：3=180°，5=逆时针90°，6=顺时针90°
    if flip == 3:
        return img.rotate(180, expand=True)
    if flip == 5:
        return img.rotate(90, expand=True)
    if flip == 6:
        return img.rotate(-90, expand=True)
    return img
