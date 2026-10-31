#!/usr/bin/env python3
"""照片筛选工具 photo-cull

本地技术评分（对焦／模糊／曝光／人脸与闭眼／连拍分组）＋可选 AI 审美细评
（Claude／ChatGPT／Grok／Gemini／DeepSeek／任意 OpenAI 兼容接口）。
同名 RAW＋JPEG 自动配对，一起评分、同步标记、同步删除。
星级／色标写成 XMP（RAW 用边车文件，JPEG 写入文件内嵌 XMP，只改元数据、不动画面数据），并生成网页报告。

画面数据永远不会被修改；删除只会移到废纸篓（或照片文件夹内的 _待删除）。
"""
from __future__ import annotations

import argparse
import base64
import concurrent.futures as cf
import csv
import hashlib
import html
import io
import json
import math
import os
import re
import shutil
import sys
import threading
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

sys.path.insert(0, str(Path(__file__).resolve().parent))
import i18n  # noqa: E402
from i18n import t  # noqa: E402

try:
    import cv2
except ImportError:  # pragma: no cover
    sys.exit(t("cull.msg.need_opencv"))

VERSION = "1.7-beta"
RAW_EXT = {".arw", ".srf", ".sr2", ".dng", ".cr2", ".cr3", ".nef", ".raf", ".orf", ".rw2", ".pef", ".3fr", ".iiq"}
IMG_EXT = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".heic", ".heif", ".hif", ".webp"}
JPEG_EXT = {".jpg", ".jpeg"}
TRASH_DIR = "_待删除"     # 没有 send2trash 时的退路文件夹（名字固定，不随界面语言变化）
WORK_SIDE = 1600   # 技术分析用的长边像素
FOCUS_SIDE = 2400  # 对焦检测用的长边像素（统一尺度，避免高像素机身在 1:1 下普遍“显软”）
SIGS: dict = {}    # 画面签名（用于同场景分组），不写入报告
AI_SIDE = 1024     # 发给 AI 的长边像素
THUMB_SIDE = 520   # 报告缩略图

# 供图形界面使用的钩子：进度回调与取消信号
PROGRESS = None            # callable(stage, done, total)
API_KEYS: dict = {}        # 图形界面传入的 API Key（优先于环境变量，不写入环境）
CANCEL = threading.Event()


class Cancelled(Exception):
    pass


def _report(stage, done, total):
    if PROGRESS:
        try:
            PROGRESS(stage, done, total)
        except Exception:
            pass
    if CANCEL.is_set():
        raise Cancelled()

# ───────────────────────── 数据结构 ─────────────────────────

@dataclass
class Photo:
    path: str                      # 主文件（有 RAW 时为 RAW）
    name: str
    kind: str                      # raw / image
    members: list = field(default_factory=list)   # 同名配对的全部文件（RAW、JPEG、HIF…）
    source: str = ""               # 实际用于分析的文件（有 JPEG 时用 JPEG）
    time: float = 0.0
    time_text: str = ""
    camera: str = ""
    lens: str = ""
    exposure: str = ""
    width: int = 0
    height: int = 0
    # 技术指标
    sharp_global: float = 0.0
    sharp_subject: float = 0.0
    sharp_face: float | None = None
    blur: float = 0.0              # 再模糊指标：0 很锐，越大越糊（与画面细节多少无关）
    mean_luma: float = 0.0
    clip_high: float = 0.0
    clip_low: float = 0.0
    faces: int = 0
    eyes_missing: int = 0          # 检测到人脸但找不到眼睛的数量（可能闭眼／侧脸）
    dhash: str = ""
    # 结果
    group: int = 0
    group_size: int = 1
    group_best: bool = True
    flags: list = field(default_factory=list)
    local_score: float = 0.0
    tier: str = ""                 # reject / alt / candidate
    ai: dict | None = None
    stars: int = 0                 # -1 = 拒绝
    label: str = ""
    thumb: str = ""
    error: str = ""
    manual: bool = False           # 星级经人工调整
    trashed: bool = False          # 已移到废纸篓


# ───────────────────────── 读取 ─────────────────────────

_heif_ready = None

def _ensure_heif():
    global _heif_ready
    if _heif_ready is None:
        try:
            import pillow_heif
            pillow_heif.register_heif_opener()
            _heif_ready = True
        except ImportError:
            _heif_ready = False
    return _heif_ready


def _fit(img: Image.Image, side: int) -> Image.Image:
    w, h = img.size
    s = side / max(w, h)
    if s < 1:
        img = img.resize((max(1, round(w * s)), max(1, round(h * s))), Image.LANCZOS)
    return img



# ───────────────────────── TIFF 结构 RAW（DNG／ARW 等）直读 ─────────────────────────
# 不依赖 rawpy：直接从 TIFF IFD 里找机内嵌入的 JPEG 预览，并读取基本 EXIF。

import struct as _st
_TSIZE = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8, 13: 4, 16: 8}
_TFMT = {1: "B", 3: "H", 4: "I", 6: "b", 8: "h", 9: "i", 13: "I", 16: "Q"}


class TiffRaw:
    def __init__(self, path: Path):
        self.f = open(path, "rb")
        head = self.f.read(8)
        if head[:2] == b"II":
            self.e = "<"
        elif head[:2] == b"MM":
            self.e = ">"
        else:
            raise ValueError(t("cull.parse.not_tiff"))
        magic, first = _st.unpack(self.e + "HI", head[2:8])
        if magic != 42:
            raise ValueError(t("cull.parse.tiff_variant"))
        self.size = path.stat().st_size
        self.ifds = []          # [(kind, {tag: value})]
        self._walk(first, "ifd0", set(), 0)

    def close(self):
        self.f.close()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    def _read(self, off, n):
        if off < 0 or off + n > self.size:
            raise ValueError(t("cull.parse.offset"))
        self.f.seek(off)
        return self.f.read(n)

    def _ifd(self, off):
        n = _st.unpack(self.e + "H", self._read(off, 2))[0]
        if n > 1000:
            raise ValueError(t("cull.parse.ifd"))
        raw = self._read(off + 2, n * 12 + 4)
        tags = {}
        for i in range(n):
            tag, typ, cnt = _st.unpack(self.e + "HHI", raw[i * 12:i * 12 + 8])
            val = raw[i * 12 + 8:i * 12 + 12]
            sz = _TSIZE.get(typ, 1) * cnt
            if sz > 4:
                if sz > 1 << 20:      # 大块数据只记偏移
                    tags[tag] = ("big", typ, cnt, _st.unpack(self.e + "I", val)[0])
                    continue
                try:
                    val = self._read(_st.unpack(self.e + "I", val)[0], sz)
                except ValueError:
                    continue
            tags[tag] = self._decode(typ, cnt, val[:sz] if sz <= 4 else val)
        nxt = _st.unpack(self.e + "I", raw[n * 12:n * 12 + 4])[0]
        return tags, nxt

    def _decode(self, typ, cnt, b):
        if typ == 2:
            return b.split(b"\0", 1)[0].decode("latin-1", "replace").strip()
        if typ in (5, 10):
            fmt = self.e + ("I" if typ == 5 else "i") * (2 * cnt)
            v = _st.unpack(fmt, b[:8 * cnt])
            r = [(v[i] / v[i + 1]) if v[i + 1] else 0.0 for i in range(0, len(v), 2)]
            return r[0] if cnt == 1 else r
        if typ in (11, 12):
            fmt = self.e + ("f" if typ == 11 else "d") * cnt
            v = _st.unpack(fmt, b[:_TSIZE[typ] * cnt])
            return v[0] if cnt == 1 else list(v)
        if typ in _TFMT:
            v = _st.unpack(self.e + _TFMT[typ] * cnt, b[:_TSIZE[typ] * cnt])
            return v[0] if cnt == 1 else list(v)
        return b

    def _walk(self, off, kind, seen, depth):
        while off and off not in seen and depth < 8 and len(self.ifds) < 64:
            seen.add(off)
            try:
                tags, nxt = self._ifd(off)
            except (ValueError, _st.error):
                return
            self.ifds.append((kind, tags))
            for sub_tag, sub_kind in ((0x14A, "sub"), (0x8769, "exif")):
                subs = tags.get(sub_tag)
                if isinstance(subs, int):
                    subs = [subs]
                if isinstance(subs, list):
                    for so in subs:
                        if isinstance(so, int):
                            self._walk(so, sub_kind, seen, depth + 1)
            off, kind = nxt, "ifd" + str(len(self.ifds))

    def tag(self, tag, kinds=None):
        for kind, tags in self.ifds:
            if (kinds is None or kind in kinds) and tag in tags and not isinstance(tags[tag], tuple):
                return tags[tag]
        return None

    def previews(self):
        """按大小降序返回候选 JPEG 字节串。"""
        cands = []
        for kind, t in self.ifds:
            if 0x201 in t and 0x202 in t:
                off, n = t[0x201], t[0x202]
                if isinstance(off, int) and isinstance(n, int) and n > 1000:
                    cands.append((off, n))
            comp, photo = t.get(0x103), t.get(0x106)
            strips, counts = t.get(0x111), t.get(0x117)
            # 预览：基线 JPEG（6/7）且不是 CFA／LinearRaw 原始数据
            if comp in (6, 7) and photo in (2, 6) and strips is not None and counts is not None:
                if isinstance(strips, int):
                    strips, counts = [strips], [counts]
                if len(strips) == 1 and counts[0] > 1000:
                    cands.append((strips[0], counts[0]))
        out = []
        for off, n in sorted(set(cands), key=lambda c: -c[1]):
            try:
                data = self._read(off, n)
            except ValueError:
                continue
            if data[:2] == b"\xff\xd8":
                out.append(data)
        return out


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


def tiff_exif(path: Path) -> dict:
    with TiffRaw(path) as t:
        def num(tag):
            v = t.tag(tag, {"exif", "ifd0"})
            return v[0] if isinstance(v, list) else v
        out = {"model": t.tag(0x110) or t.tag(0xC614) or "", "lens": t.tag(0xA434, {"exif", "ifd0"}) or "",
               "dt": t.tag(0x9003, {"exif"}) or t.tag(0x132) or "", "subsec": str(t.tag(0x9291, {"exif"}) or "")}
        et, fn, iso, fl = num(0x829A), num(0x829D), num(0x8827), num(0x920A)
        if et:
            out["shutter"] = f"1/{round(1/et)}" if 0 < et < 1 else f"{et:g}"
        if fn:
            out["fnum"] = f"{fn:g}"
        if iso:
            out["iso"] = str(iso)
        if fl:
            out["focal"] = f"{fl:g}"
        return {k: (v if isinstance(v, str) else str(v)) for k, v in out.items()}

def raf_jpeg(path: Path) -> bytes:
    """富士 RAF：文件头第 84／88 字节（大端）记录内嵌 JPEG 的偏移和长度，JPEG 里带完整 EXIF。"""
    with open(path, "rb") as f:
        head = f.read(100)
        if not head.startswith(b"FUJIFILMCCD-RAW"):
            raise ValueError(t("cull.parse.not_raf"))
        off, ln = _st.unpack(">II", head[84:92])
        size = path.stat().st_size
        if not (100 <= off < size and 1000 < ln <= size - off):
            raise ValueError(t("cull.parse.raf_preview_pos"))
        f.seek(off)
        data = f.read(ln)
    if data[:2] != b"\xff\xd8":
        raise ValueError(t("cull.parse.raf_preview_jpeg"))
    return data


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


def read_exif(path: Path) -> dict:
    out = {}
    if path.suffix.lower() == ".raf":
        try:
            out = _pil_exif(io.BytesIO(raf_jpeg(path)))
            if out.get("dt"):
                return out
        except (ValueError, OSError, _st.error):
            out = {}
    if path.suffix.lower() in RAW_EXT and path.suffix.lower() != ".raf":
        try:
            out = tiff_exif(path)
            if out.get("dt"):
                return out
        except (ValueError, OSError, _st.error):
            out = {}
    try:
        import exifread
        with open(path, "rb") as f:
            tags = exifread.process_file(f, details=False, stop_tag="EXIF MakerNote")
        g = lambda k: str(tags[k]).strip() if k in tags else ""
        out = {
            "dt": g("EXIF DateTimeOriginal") or g("Image DateTime"),
            "subsec": g("EXIF SubSecTimeOriginal"),
            "model": g("Image Model"),
            "lens": g("EXIF LensModel"),
            "shutter": g("EXIF ExposureTime"),
            "fnum": g("EXIF FNumber"),
            "iso": g("EXIF ISOSpeedRatings") or g("EXIF PhotographicSensitivity"),
            "focal": g("EXIF FocalLength"),
        }
    except Exception:
        pass
    if not out.get("dt") and path.suffix.lower() != ".raf":
        try:  # HEIC/PNG 等交给 Pillow
            if path.suffix.lower() in {".heic", ".heif", ".hif"}:
                _ensure_heif()
            got = _pil_exif(path)
            out = {**got, **{k: v for k, v in out.items() if v}}
        except Exception:
            pass
    return out


def _pil_exif(src) -> dict:
    out = {}
    with Image.open(src) as im:
        ex = im.getexif()
        sub = ex.get_ifd(0x8769)
        out["model"] = str(ex.get(0x0110, "")).strip()
        out["dt"] = str(sub.get(0x9003) or ex.get(0x0132) or "")
        out["subsec"] = str(sub.get(0x9291) or "")
        out["lens"] = str(sub.get(0xA434, "")).strip()
        et, fn, iso, fl = sub.get(0x829A), sub.get(0x829D), sub.get(0x8827), sub.get(0x920A)
        if et:
            et = float(et); out["shutter"] = f"1/{round(1/et)}" if 0 < et < 1 else f"{et:g}"
        if fn: out["fnum"] = f"{float(fn):g}"
        if iso: out["iso"] = str(iso[0] if isinstance(iso, tuple) else iso)
        if fl: out["focal"] = f"{float(fl):g}"
    return out


def _ratio(text: str) -> str:
    if "/" in text:
        a, b = text.split("/", 1)
        try:
            v = float(a) / float(b)
            return f"{v:g}" if v >= 1 else f"{v:.1f}".rstrip("0").rstrip(".")
        except (ValueError, ZeroDivisionError):
            return text
    return text


def exposure_text(e: dict) -> str:
    parts = []
    if e.get("focal"): parts.append(_ratio(e["focal"]) + "mm")
    if e.get("fnum"): parts.append("f/" + _ratio(e["fnum"]))
    if e.get("shutter"): parts.append(e["shutter"] + "s")
    if e.get("iso"): parts.append("ISO" + e["iso"])
    return " ".join(parts)


def capture_time(e: dict, path: Path) -> float:
    dt = e.get("dt", "")
    try:
        t = datetime.strptime(dt[:19], "%Y:%m:%d %H:%M:%S").timestamp()
        sub = re.sub(r"\D", "", e.get("subsec", ""))
        if sub:
            t += float("0." + sub)
        return t
    except ValueError:
        return path.stat().st_mtime


# ───────────────────────── 技术分析 ─────────────────────────

_cascades = threading.local()

def _cascade(name: str):
    """OpenCV 4.x 自带 Haar 模型；不可用时返回 None（跳过人脸检测）。

    CascadeClassifier 不是线程安全的：多个线程同时用同一个对象做 detectMultiScale，
    会在 OpenCV 内部（HaarEvaluator 的积分图缓冲区）互相踩内存，整个程序直接段错误闪退
    （1.7-beta 大批量测试时并行数 10 就出现过）。所以每个线程各自加载一份。"""
    cache = getattr(_cascades, "d", None)
    if cache is None:
        cache = _cascades.d = {}
    if name not in cache:
        c = None
        try:
            c = cv2.CascadeClassifier(os.path.join(cv2.data.haarcascades, name))
            if c.empty():
                c = None
        except AttributeError:
            c = None
        cache[name] = c
    return cache[name]


def lap_var(gray: np.ndarray) -> float:
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def subject_sharpness(gray: np.ndarray, grid: int = 8, top: int = 3) -> float:
    """浅景深照片背景是虚的，所以取最清晰的几块区域代表主体清晰度。"""
    h, w = gray.shape
    vals = []
    for i in range(grid):
        for j in range(grid):
            tile = gray[i * h // grid:(i + 1) * h // grid, j * w // grid:(j + 1) * w // grid]
            if tile.size and tile.std() > 4:      # 跳过纯色块（天空、墙）
                vals.append(lap_var(tile))
    if not vals:
        return lap_var(gray)
    vals.sort(reverse=True)
    return float(np.mean(vals[:top]))


def reblur(tile: np.ndarray) -> float:
    """Crété-Roffet 再模糊指标：把图再模糊一次，看边缘变化有多大。
    已经很糊的图再模糊几乎不变（接近 1），锐利的图变化大（接近 0）。与纹理多少基本无关。"""
    F = tile.astype(np.float32)
    total = kept = 0.0
    # 两个方向按梯度能量加权合并：竖条纹这类单一方向的纹理不会被误判
    for k, ax in (((1, 9), 1), ((9, 1), 0)):
        B = cv2.blur(F, k)
        dF = np.abs(np.diff(F, axis=ax))
        dB = np.abs(np.diff(B, axis=ax))
        total += float(dF.sum())
        kept += float(np.maximum(0, dF - dB).sum())
    return (total - kept) / total if total > 0 else 1.0


def focus_blur(gray_full: np.ndarray) -> float:
    """取画面中最锐利的两块区域代表主体（浅景深背景虚化不影响判断）。"""
    h, w = gray_full.shape
    s = min(1.0, FOCUS_SIDE / max(h, w))
    g = cv2.resize(gray_full, None, fx=s, fy=s, interpolation=cv2.INTER_AREA) if s < 1 else gray_full
    h, w = g.shape
    tiles = []
    for i in range(8):
        for j in range(8):
            t = g[i * h // 8:(i + 1) * h // 8, j * w // 8:(j + 1) * w // 8]
            if t.size:
                tiles.append((lap_var(t), t))
    # 只在边缘最丰富的 8 块里找（天空、纯色墙这类平坦区域噪点多，会让指标失真）
    tiles.sort(key=lambda x: -x[0])
    vals = sorted(reblur(t) for e, t in tiles[:8] if e > 20)
    if not vals:
        return reblur(g)
    return float(np.mean(vals[:2]))


def signature(gray: np.ndarray) -> np.ndarray:
    """32×24 归一化亮度缩略图：对曝光变化不敏感，用于判断是否同一场景。"""
    h, w = gray.shape
    sm = cv2.resize(gray, (32, 24) if w >= h else (24, 32), interpolation=cv2.INTER_AREA).astype(np.float32)
    return ((sm - sm.mean()) / (sm.std() + 1e-6)).flatten()


def similarity(a, b) -> float:
    if a is None or b is None or a.shape != b.shape:
        return -1.0
    return float(np.dot(a, b) / len(a))


def dhash(gray: np.ndarray) -> str:
    small = cv2.resize(gray, (9, 8), interpolation=cv2.INTER_AREA)
    bits = (small[:, 1:] > small[:, :-1]).flatten()
    return "%016x" % int("".join("1" if b else "0" for b in bits), 2)


def hamming(a: str, b: str) -> int:
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def analyze(img: Image.Image, p: Photo) -> Image.Image:
    """返回缩到 FOCUS_SIDE 的图，缩略图和发给 AI 的图都从它再缩，不必对全尺寸原图重复缩放。"""
    focus = _fit(img, FOCUS_SIDE)
    work = _fit(focus, WORK_SIDE)
    p.width, p.height = img.info.get("full_size", img.size)
    gray = cv2.cvtColor(np.asarray(work), cv2.COLOR_RGB2GRAY)
    p.sharp_global = lap_var(gray)
    p.sharp_subject = subject_sharpness(gray)
    p.mean_luma = float(gray.mean())
    p.clip_high = float((gray >= 250).mean())
    p.clip_low = float((gray <= 5).mean())
    p.dhash = dhash(gray)
    SIGS[p.path] = signature(gray)
    full = cv2.cvtColor(np.asarray(focus), cv2.COLOR_RGB2GRAY)
    p.blur = round(focus_blur(full), 3)

    # 人脸／眼睛（Haar：快但粗糙，只作参考）
    det = gray
    scale = 1.0
    if max(gray.shape) > 1000:
        scale = 1000 / max(gray.shape)
        det = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    m = max(24, int(min(det.shape) * 0.06))
    face_model, eye_model = _cascade("haarcascade_frontalface_default.xml"), _cascade("haarcascade_eye.xml")
    if face_model is None:
        return focus
    faces = face_model.detectMultiScale(
        cv2.equalizeHist(det), scaleFactor=1.1, minNeighbors=6, minSize=(m, m))
    p.faces = len(faces)
    face_sharp = []
    for (x, y, w, h) in faces:
        X, Y, W, H = (int(v / scale) for v in (x, y, w, h))
        roi = gray[Y:Y + H, X:X + W]
        if roi.size == 0:
            continue
        face_sharp.append(lap_var(roi))
        upper = roi[: H * 6 // 10]
        if W >= 90 and eye_model is not None:   # 脸太小时眼睛检测不可靠，不判断
            eyes = eye_model.detectMultiScale(
                upper, scaleFactor=1.1, minNeighbors=5, minSize=(max(8, W // 10), max(8, W // 10)))
            if len(eyes) == 0:
                p.eyes_missing += 1
    if face_sharp:
        p.sharp_face = float(max(face_sharp))
    return focus


# ───────────────────────── 分组与评分 ─────────────────────────

def group_bursts(photos: list[Photo], burst_gap: float, scene_gap: float, sim: float):
    """连拍：间隔短且画面相近；同场景重拍：间隔稍长但画面很像（适合旁轴、手动上弦等慢节奏拍摄）。"""
    photos.sort(key=lambda x: (x.time, x.name))
    gid, last = 0, None
    for p in photos:
        same = False
        if last is not None:
            dt = p.time - last.time
            c = similarity(SIGS.get(p.path), SIGS.get(last.path))
            same = (dt <= burst_gap and c >= sim - 0.15) or (dt <= scene_gap and c >= sim)
        if not same:
            gid += 1
        p.group = gid
        last = p
    sizes = {}
    for p in photos:
        sizes[p.group] = sizes.get(p.group, 0) + 1
    for p in photos:
        p.group_size = sizes[p.group]


def pct_rank(values: list[float], v: float) -> float:
    if not values:
        return 0.5
    return sum(1 for x in values if x <= v) / len(values)


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


def score_local(photos: list[Photo], args):
    ok = [p for p in photos if not p.error]
    focus_vals = [-p.blur for p in ok]
    for p in ok:
        flags = []
        if p.blur >= args.blur_reject:
            flags.append("blur")
        elif p.blur >= args.blur_warn:
            flags.append("soft")
        if p.mean_luma < 18:
            flags.append("under")
        elif p.mean_luma > 238:
            flags.append("over")
        if p.clip_high > args.clip_high:
            flags.append(f"clip_high:{p.clip_high:.3f}")
        if p.clip_low > args.clip_low:
            flags.append(f"clip_low:{p.clip_low:.3f}")
        if p.eyes_missing:
            flags.append("eyes")
        p.flags = flags

        sharp_part = pct_rank(focus_vals, -p.blur)                   # 0..1，本批中越锐越高
        expo_part = 1 - min(1, abs(p.mean_luma - 118) / 118) * 0.6 - min(0.4, p.clip_high * 4) - min(0.3, max(0, p.clip_low - 0.05) * 2)
        face_part = 1.0 if p.faces == 0 else (0.6 if p.eyes_missing else 1.0)
        p.local_score = round(100 * (0.6 * sharp_part + 0.3 * max(0, expo_part) + 0.1 * face_part), 1)

    # 连拍组内只保留最高分为“主选”，其余为“同组备选”
    best = {}
    for p in ok:
        if p.group not in best or p.local_score > best[p.group].local_score:
            best[p.group] = p
    hard = {"blur", "under", "over"}
    for p in ok:
        p.group_best = best[p.group] is p
        if any(f in hard for f in p.flags):
            p.tier = "reject"
        elif not p.group_best:
            p.tier = "alt"
        else:
            p.tier = "candidate"
    for p in photos:
        if p.error:
            p.tier = "error"


# ───────────────────────── AI 细评 ─────────────────────────
# 每家：显示名、环境变量、默认模型、可选模型（notes 是界面里的简短说明，对应语言包 cull.model_note.*）。
# api：messages＝Anthropic，responses＝OpenAI Responses API，chat＝OpenAI 兼容 Chat Completions，gemini＝Gemini REST。
# 模型列表核对于 2026-10：只列能看图的模型；用户也可以手动填写列表外的模型名称。
PROVIDERS = {
    "claude": {"name": "Claude", "env": "ANTHROPIC_API_KEY", "default": "claude-sonnet-5-5", "api": "messages",
               "models": ["claude-sonnet-5-5", "claude-haiku-5-5", "claude-opus-5-5", "claude-fable-5-1"],
               "notes": {"claude-sonnet-5-5": "recommended", "claude-haiku-5-5": "cheap", "claude-opus-5-5": "high",
                         "claude-fable-5-1": "top"},
               "console": "console.anthropic.com", "key_ph": "sk-ant-…"},
    "openai": {"name": "ChatGPT", "env": "OPENAI_API_KEY", "default": "gpt-6.1-sol", "api": "responses", "base_url": None,
               "models": ["gpt-6.1-sol", "gpt-6-luna", "gpt-6-astra", "gpt-5.5"],
               "notes": {"gpt-6.1-sol": "recommended", "gpt-6-luna": "cheap", "gpt-6-astra": "top", "gpt-5.5": "previous"},
               "console": "platform.openai.com", "key_ph": "sk-…"},
    "grok": {"name": "Grok", "env": "XAI_API_KEY", "default": "grok-4.7", "api": "responses", "base_url": "https://api.x.ai/v1",
             "models": ["grok-4.7"], "notes": {"grok-4.7": "recommended"}, "console": "console.x.ai", "key_ph": "xai-…"},
    "gemini": {"name": "Gemini", "env": "GEMINI_API_KEY", "alt_env": "GOOGLE_API_KEY", "default": "gemini-3.8-flash", "api": "gemini",
               "models": ["gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite", "gemini-4-argon"],
               "notes": {"gemini-3.8-flash": "recommended", "gemini-3.6-flash": "balanced", "gemini-3.5-flash-lite": "cheap",
                         "gemini-4-argon": "top"},
               "console": "aistudio.google.com", "key_ph": "AIza…"},
    # DeepSeek：只有 deepseek-flash 能看图（deepseek-v4-pro 只支持文字），见 api-docs.deepseek.com/guides/vision
    "deepseek": {"name": "DeepSeek", "env": "DEEPSEEK_API_KEY", "default": "deepseek-flash", "api": "chat",
                 "base_url": "https://api.deepseek.com", "models": ["deepseek-flash"], "notes": {"deepseek-flash": "ds_vision"},
                 "console": "platform.deepseek.com", "key_ph": "sk-…"},
    # 自定义：任意 OpenAI 兼容的视觉模型（通义千问、Kimi、豆包、OpenRouter、本地 Ollama／LM Studio 等），地址和模型名由用户填写
    "custom": {"name": "Custom", "env": "PHOTO_CULL_CUSTOM_API_KEY", "default": "", "api": "chat", "base_url": None,
               "models": [], "notes": {}, "console": "", "key_ph": "sk-…"},
}
GEMINI_BASE = os.environ.get("PHOTO_CULL_GEMINI_BASE", "https://generativelanguage.googleapis.com/v1beta")
CUSTOM_BASE: dict = {}      # 图形界面／命令行传入的自定义接口地址 {"custom": url}


def env_key(provider: str) -> str:
    info = PROVIDERS[provider]
    return os.environ.get(info["env"], "") or (os.environ.get(info["alt_env"], "") if info.get("alt_env") else "")


GENRES = ("portrait", "street", "landscape", "architecture", "event", "other")
GENRE_LEGACY = {"人像": "portrait", "扫街": "street", "风景": "landscape", "建筑": "architecture", "活动": "event", "其他": "other"}

# 细评提示词：按界面语言选择，评语和改进点用同一种语言写；题材统一用英文代码，界面再翻译。
# {exif}／{flags} 用 str.replace 填入（不用 format，免得要把 JSON 的花括号写两遍）。
AI_PROMPTS = {
    "zh-CN": """你是一位严格但公正的资深摄影编辑，正在帮摄影师从一批照片里挑选作品。
请评价这张照片，题材可能是人像、扫街人文、风景建筑或活动连拍，先自行判断题材，再用该题材的标准评价。

拍摄信息：{exif}
本地技术检测：{flags}

评分维度（1-10，整数）：
- composition 构图与画面秩序
- light 光线与色彩
- subject 主体与表达（人像看神态表情，扫街看瞬间与故事，风景看主体与氛围）
- moment 时机／决定性瞬间
- technical 技术质量（对焦、曝光、噪点、水平）

stars 给 1-5 星：5=作品级，4=精选，3=可用，2=一般，1=建议淘汰。
genre 只能是 portrait、street、landscape、architecture、event、other 之一。
只输出一个 JSON 对象，不要其他文字：
{"genre":"portrait","scores":{"composition":0,"light":0,"subject":0,"moment":0,"technical":0},"overall":0,"stars":0,"keep":true,"comment":"一句中文评语，指出最大优点","issues":["最多3条可改进点，用中文"]}""",
    "en": """You are a strict but fair senior photo editor helping a photographer pick the best frames from a shoot.
Evaluate this photo. It may be a portrait, street photography, landscape/architecture or an event/burst sequence: first decide the genre, then judge it by that genre's standards.

Capture info: {exif}
Local technical checks: {flags}

Score each dimension from 1 to 10 (integers):
- composition: composition and visual order
- light: light and color
- subject: subject and expression (portraits: expression and gesture; street: moment and story; landscape: subject and atmosphere)
- moment: timing / decisive moment
- technical: technical quality (focus, exposure, noise, level horizon)

stars from 1 to 5: 5 = portfolio, 4 = pick, 3 = usable, 2 = weak, 1 = reject.
genre must be one of portrait, street, landscape, architecture, event, other.
Output one JSON object only, no other text:
{"genre":"portrait","scores":{"composition":0,"light":0,"subject":0,"moment":0,"technical":0},"overall":0,"stars":0,"keep":true,"comment":"One sentence in English naming the photo's biggest strength","issues":["Up to 3 improvement points, in English"]}""",
    "ja": """あなたは厳しくも公正なベテランの写真編集者で、撮影した写真の中から作品を選ぶ手伝いをしています。
この写真を評価してください。ジャンルはポートレート、スナップ、風景・建築、イベント・連写などの可能性があります。まずジャンルを判断し、そのジャンルの基準で評価してください。

撮影情報：{exif}
ローカルの技術チェック：{flags}

評価項目（1〜10 の整数）：
- composition 構図と画面の秩序
- light 光と色
- subject 主題と表現（ポートレートは表情や仕草、スナップは瞬間と物語、風景は主題と雰囲気）
- moment タイミング／決定的瞬間
- technical 技術的な品質（ピント、露出、ノイズ、水平）

stars は 1〜5：5＝作品レベル、4＝セレクト、3＝使える、2＝いまひとつ、1＝不採用を推奨。
genre は portrait、street、landscape、architecture、event、other のいずれか。
JSON オブジェクトを 1 つだけ出力し、ほかの文章は書かないでください：
{"genre":"portrait","scores":{"composition":0,"light":0,"subject":0,"moment":0,"technical":0},"overall":0,"stars":0,"keep":true,"comment":"最大の長所を述べる日本語の一文","issues":["改善点を最大3つ、日本語で"]}""",
}


def ai_prompt(exif: str, flags: str, lang: str | None = None) -> str:
    return AI_PROMPTS.get(lang or i18n.current(), AI_PROMPTS["en"]).replace("{exif}", exif).replace("{flags}", flags)


def _jpeg_b64(img: Image.Image, side: int) -> tuple[str, str]:
    buf = io.BytesIO()
    _fit(img, side).save(buf, "JPEG", quality=85)
    data = buf.getvalue()
    return base64.b64encode(data).decode(), hashlib.sha1(data).hexdigest()


def _parse_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        raise ValueError(t("cull.msg.ai_no_json"))
    d = json.loads(m.group(0))
    stars = int(d.get("stars", 0))
    if not 1 <= stars <= 5:
        raise ValueError(t("cull.msg.ai_bad_stars"))
    d["stars"] = stars
    g = str(d.get("genre", "")).strip()
    d["genre"] = GENRE_LEGACY.get(g, g.lower() if g.lower() in GENRES else "other") if g else ""
    try:
        d["overall"] = int(round(float(d.get("overall", 0))))
    except (TypeError, ValueError):
        d["overall"] = 0
    return d


def make_caller(provider: str, model: str):
    """返回 call(b64_jpeg, prompt) -> 文本。各家统一接口。"""
    info = PROVIDERS[provider]
    key = API_KEYS.get(provider) or env_key(provider)
    if not key and provider == "custom":
        key = "none"           # 本地服务（Ollama、LM Studio 等）通常不需要 Key
    if not key:
        sys.exit(t("cull.msg.no_key", env=info["env"], name=info["name"]))
    api = info["api"]
    if api == "messages":
        try:
            import anthropic
        except ImportError:
            sys.exit(t("cull.msg.need_pkg", name=info["name"], pkg="anthropic"))
        client = anthropic.Anthropic(api_key=key, max_retries=4)

        def call(b64, prompt):
            msg = client.messages.create(model=model, max_tokens=800, messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
                {"type": "text", "text": prompt}]}])
            return "".join(getattr(b, "text", "") for b in msg.content)
        return call
    if api == "gemini":
        return _gemini_caller(key, model)
    base = CUSTOM_BASE.get(provider) or info.get("base_url")
    if api == "chat":
        if not base:
            sys.exit(t("cull.err.custom_incomplete"))
        return _chat_caller(key, base, model, info["name"])
    try:
        from openai import OpenAI
    except ImportError:
        sys.exit(t("cull.msg.need_pkg", name=info["name"], pkg="openai"))
    client = OpenAI(api_key=key, base_url=base, max_retries=4)
    if api == "responses":
        def call(b64, prompt):
            # OpenAI 与 xAI 都支持 Responses API；推理模型的思考也计入输出上限，所以给足余量
            r = client.responses.create(model=model, store=False, max_output_tokens=4000, input=[{
                "role": "user", "content": [
                    {"type": "input_image", "image_url": "data:image/jpeg;base64," + b64, "detail": "high"},
                    {"type": "input_text", "text": prompt}]}])
            return r.output_text
        return call
    raise ValueError(api)


def _post_json(url: str, body: dict, headers: dict, label: str) -> dict:
    """POST JSON，遇到限流／服务端错误时退避重试（最多 4 次）。只用标准库。"""
    import urllib.error
    import urllib.request
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    delay = 2.0
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")[:300]
            if e.code in (429, 500, 502, 503, 504) and attempt < 3:
                time.sleep(delay)
                delay *= 2
                continue
            raise RuntimeError(f"{label} HTTP {e.code}: {detail}") from None
        except urllib.error.URLError as e:
            if attempt < 3:
                time.sleep(delay)
                delay *= 2
                continue
            raise RuntimeError(f"{label}: {e.reason}") from None


def _chat_caller(key: str, base: str, model: str, label: str):
    """OpenAI 兼容的 Chat Completions（DeepSeek、通义千问、Kimi、豆包、OpenRouter、Ollama、LM Studio…）。
    直接走 REST，不需要安装 openai 包。"""
    url = base.rstrip("/") + "/chat/completions"

    def call(b64, prompt):
        body = {"model": model, "max_tokens": 4000, "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b64}},
            {"type": "text", "text": prompt}]}]}
        res = _post_json(url, body, {"Authorization": "Bearer " + key}, label)
        choices = res.get("choices") or []
        if not choices:
            raise RuntimeError(f"{label}: {str(res)[:200]}")
        content = (choices[0].get("message") or {}).get("content") or ""
        if isinstance(content, list):          # 少数服务返回分段内容
            content = "".join(c.get("text", "") for c in content if isinstance(c, dict))
        return content
    return call


def _gemini_caller(key: str, model: str):
    """Gemini：直接调用 REST 接口 generateContent（无需额外安装 SDK）。"""
    import urllib.error
    import urllib.request

    def post(url, body):
        req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                     headers={"Content-Type": "application/json", "x-goog-api-key": key})
        delay = 2.0
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    return json.loads(r.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", errors="replace")[:300]
                if e.code in (429, 500, 502, 503, 504) and attempt < 3:
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise RuntimeError(f"Gemini HTTP {e.code}: {detail}") from None

    def texts(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k == "text" and isinstance(v, str):
                    yield v
                else:
                    yield from texts(v)
        elif isinstance(obj, list):
            for v in obj:
                yield from texts(v)

    def call(b64, prompt):
        body = {"contents": [{"role": "user", "parts": [
                    {"inline_data": {"mime_type": "image/jpeg", "data": b64}}, {"text": prompt}]}],
                "generationConfig": {"maxOutputTokens": 4096, "responseMimeType": "application/json"}}
        res = post(f"{GEMINI_BASE}/models/{model}:generateContent", body)
        cands = res.get("candidates") or []
        if not cands:
            reason = (res.get("promptFeedback") or {}).get("blockReason", "no candidates")
            raise RuntimeError(t("cull.msg.gemini_empty", reason=reason))
        return "".join(texts(cands[0].get("content", {})))
    return call


def ai_review(items: list[tuple[Photo, Image.Image]], args, cache: dict, cache_path: Path):
    provider = args.provider
    info = PROVIDERS[provider]
    model = args.model or info["default"]
    if not model:
        sys.exit(t("cull.err.custom_incomplete"))
    lang = i18n.current()
    label = f"{info['name']} ({model})"
    jobs = []
    for p, img in items:
        b64, digest = _jpeg_b64(img, AI_SIDE)
        key = f"{provider}:{model}:{lang}:{digest}"     # 评语跟语言走：换语言会重新细评
        hit = cache.get(key) or (lang == "zh-CN" and (cache.get(f"{provider}:{model}:{digest}")
                                 or (cache.get(f"{model}:{digest}") if provider == "claude" else None))) or None   # 1.5 及以前的中文缓存
        if hit:
            p.ai = hit
        else:
            jobs.append((p, b64, key))
    if not jobs:
        print(t("cull.msg.ai_all_cached", n=len(items)))
        return
    call = make_caller(provider, model)
    est_in = len(jobs) * 1500
    est_out = len(jobs) * (250 if info["api"] in ("messages", "gemini") else 800)
    print(t("cull.msg.ai_jobs", n=len(jobs), label=label, cached=len(items) - len(jobs)))
    fm = lambda n: f"{n/1e6:.2f}M" if n >= 1e6 else f"{n/1e3:.0f}K"
    print("  " + t("cull.confirm.tokens", inp=fm(est_in), out=fm(est_out)))
    if not args.yes:
        confirm = getattr(args, "confirm", None)
        ok = confirm(len(jobs), est_in, est_out, label) if confirm else \
            input("  " + t("cull.msg.ai_ask")).strip().lower() == "y"
        if not ok:
            print("  " + t("cull.msg.ai_skipped"))
            return

    def run(job):
        p, b64, key = job
        exif = f"{p.camera} {p.lens} {p.exposure}".strip() or t("cull.msg.unknown", lang)
        flags = t("cull.msg.list_sep", lang).join(flag_text(f, lang) for f in p.flags) or t("cull.msg.no_issues", lang)
        d = _parse_json(call(b64, ai_prompt(exif, flags, lang)))
        d["lang"] = lang
        d["provider"], d["model"] = info["name"], model
        return p, key, d

    def save():
        cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")

    done = ok_count = 0
    _report("ai", 0, len(jobs))
    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(run, j) for j in jobs]
        for fut in cf.as_completed(futs):
            if CANCEL.is_set():
                for f in futs:
                    f.cancel()
                save()
                raise Cancelled()
            done += 1
            try:
                p, key, d = fut.result()
                p.ai = d
                cache[key] = d
                ok_count += 1
            except Exception as e:  # 单张失败不影响整体
                print("  " + t("cull.msg.ai_failed", err=f"{type(e).__name__}: {e}"))
                if ok_count == 0 and done >= 3:   # 开头连续失败：多半是 Key、模型名或余额问题，及时止损
                    for f in futs:
                        f.cancel()
                    save()
                    print("  " + t("cull.msg.ai_stop", n=done, env=info["env"]))
                    return
            _report("ai", done, len(jobs))
            if done % 10 == 0 or done == len(jobs):
                print(f"  {done}/{len(jobs)}")
                save()


# ───────────────────────── 星级与色标 ─────────────────────────

def label_for(stars: int) -> str:
    if stars < 0 or stars == 1:
        return "Red"
    if stars >= 4:
        return "Green"
    if stars == 3:
        return "Yellow"
    return ""


def assign_ratings(photos: list[Photo]):
    # 不开 AI 时只做技术判断：入围 3★、备选 2★、淘汰拒绝。4–5★ 只由审美细评给出。
    for p in photos:
        if p.manual:
            continue
        if p.tier == "reject":
            p.stars = -1
        elif p.tier == "error":
            p.stars = 0
        elif p.ai:
            p.stars = min(p.ai["stars"], 2) if p.tier == "alt" else p.ai["stars"]
        elif p.tier == "alt":
            p.stars = 2
        else:
            p.stars = 3
        p.label = label_for(p.stars) if p.tier != "error" else ""


# ───────────────────────── XMP：边车文件 ─────────────────────────

XMP_NS = "http://ns.adobe.com/xap/1.0/"
XMP_CORE = """<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="photo-cull {ver}">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
    xmlns:xmp="http://ns.adobe.com/xap/1.0/"
    xmp:Rating="{rating}"{label}/>
 </rdf:RDF>
</x:xmpmeta>"""
XPACKET_BEGIN = '<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>\n'
XPACKET_END = '<?xpacket end="w"?>'


def _new_core(rating: int, label: str) -> str:
    return XMP_CORE.format(ver=VERSION, rating=rating, label=f'\n    xmp:Label="{label}"' if label else "")


def sidecar_path(photo_path: Path) -> Path:
    # Lightroom 与 Capture One 默认都使用 “同名.xmp”；RAW＋JPEG 配对共用这一个
    return photo_path.with_suffix(".xmp")


def merge_xmp(text: str, rating: int, label: str) -> str:
    """在已有 XMP 中只改 xmp:Rating / xmp:Label，其余内容（调色、关键词等）原样保留。"""
    for tag in ("Rating", "Label"):
        text = re.sub(rf"\s*<xmp:{tag}>.*?</xmp:{tag}>", "", text, flags=re.S)
        text = re.sub(rf"\s*<xmp:{tag}\s*/>", "", text)
    m = re.search(r"<rdf:Description\b[^>]*?/?>", text, re.S)
    if not m:
        raise ValueError(t("cull.parse.xmp_struct"))
    tag = m.group(0)
    new = re.sub(r'\s+xmp:(Rating|Label)\s*=\s*"[^"]*"', "", tag)
    if 'xmlns:xmp="' not in text:
        new = new.replace("<rdf:Description", f'<rdf:Description xmlns:xmp="{XMP_NS}"', 1)
    attrs = f' xmp:Rating="{rating}"' + (f' xmp:Label="{label}"' if label else "")
    if new.endswith("/>"):
        new = new[:-2].rstrip() + attrs + "/>"
    else:
        new = new[:-1].rstrip() + attrs + ">"
    return text[:m.start()] + new + text[m.end():]


def write_sidecar(path: Path, rating: int, label: str, dry: bool) -> str:
    if path.exists():
        old = path.read_text(encoding="utf-8", errors="strict")
        content = merge_xmp(old, rating, label)
        if content == old:
            return "unchanged"
        if not dry and "photo-cull" not in old:   # 只备份别的软件写的 XMP
            bak = path.with_suffix(".xmp.cull-bak")
            if not bak.exists():
                shutil.copy2(path, bak)
    else:
        content = XPACKET_BEGIN + _new_core(rating, label) + "\n" + XPACKET_END + "\n"
    if not dry:
        tmp = path.with_suffix(".xmp.tmp")
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(path)
    return "written"


# ───────────────────────── XMP：写入 JPEG 内嵌（只改元数据段） ─────────────────────────

XMP_APP1_ID = b"http://ns.adobe.com/xap/1.0/\x00"
XMP_PAD = 2048   # 新写入的 XMP 预留空白，以后改星级可原地覆盖、文件长度不变


def jpeg_segments(data: bytes):
    """解析 JPEG 头部各段，返回 ([(段起点, 内容起点, 段终点, 标记)], 图像数据 SOS 起点)。"""
    if data[:2] != b"\xff\xd8":
        raise ValueError(t("cull.parse.not_jpeg"))
    segs, i, n = [], 2, len(data)
    while i < n:
        if data[i] != 0xFF:
            raise ValueError(t("cull.parse.jpeg_struct"))
        j = i + 1
        while j < n and data[j] == 0xFF:
            j += 1
        if j >= n:
            break
        m = data[j]
        if m == 0xDA:
            return segs, i
        if m == 0xD9:
            break
        if 0xD0 <= m <= 0xD7 or m == 0x01:
            segs.append((i, j + 1, j + 1, m))
            i = j + 1
            continue
        if j + 3 > n:
            break
        length = int.from_bytes(data[j + 1:j + 3], "big")
        if length < 2 or j + 1 + length > n:
            raise ValueError(t("cull.parse.jpeg_seg"))
        segs.append((i, j + 3, j + 1 + length, m))
        i = j + 1 + length
    raise ValueError(t("cull.parse.jpeg_no_scan"))


def _packet(core: str, total: int | None) -> bytes | None:
    """组装带 xpacket 包装和空白填充的 XMP；total 指定时必须正好凑到这个字节数。"""
    core = core.strip()
    if not core.startswith("<?xpacket begin"):
        core = XPACKET_BEGIN + core
    head = core.encode("utf-8") + b"\n"
    tail = XPACKET_END.encode()
    pad = XMP_PAD if total is None else total - len(head) - len(tail)
    if pad < 0:
        return None
    filler = bytearray(b" " * pad)
    for k in range(99, pad, 100):
        filler[k] = 0x0A
    return head + bytes(filler) + tail


def jpeg_set_rating(path: Path, rating: int, label: str, dry: bool) -> str:
    data = path.read_bytes()
    segs, sos = jpeg_segments(data)
    mpf_at = next((a for a, ps, b, m in segs if m == 0xE2 and data[ps:ps + 4] == b"MPF\x00"), None)
    xmp = next(((a, ps, b) for a, ps, b, m in segs if m == 0xE1 and data[ps:ps + len(XMP_APP1_ID)] == XMP_APP1_ID), None)

    if xmp:
        a, ps, b = xmp
        text = data[ps + len(XMP_APP1_ID):b].decode("utf-8", errors="strict")
        core = re.sub(r"\s*<\?xpacket end=.*?\?>\s*$", "", text, flags=re.S)
        merged = merge_xmp(core, rating, label)
        if merged == core:
            return "unchanged"
        pkt = _packet(merged, b - ps - len(XMP_APP1_ID))            # 优先原地覆盖：长度不变
        if pkt is not None:
            out = data[:ps + len(XMP_APP1_ID)] + pkt + data[b:]
        else:
            # 需要变长：只有当 XMP 段位于 MPF（多图索引）之前才安全，否则会打乱机内大预览的偏移
            if mpf_at is not None and mpf_at < a:
                raise ValueError(t("cull.parse.jpeg_mpf"))
            pkt = _packet(merged, None)
            out = data[:a] + _app1(pkt) + data[b:]
    else:
        pos = 2
        for a, ps, b, m in segs:                                    # 放在 JFIF／Exif 之后
            if m == 0xE0 or (m == 0xE1 and data[ps:ps + 6] == b"Exif\x00\x00"):
                pos = b
            else:
                break
        if mpf_at is not None:
            pos = min(pos, mpf_at)                                  # 必须在 MPF 之前插入
        out = data[:pos] + _app1(_packet(_new_core(rating, label), None)) + data[pos:]

    # 校验：图像数据（SOS 之后的全部字节，含机内附带的预览图）必须逐字节不变
    segs2, sos2 = jpeg_segments(out)
    if out[sos2:] != data[sos:]:
        raise ValueError(t("cull.parse.verify_changed"))
    try:
        with Image.open(io.BytesIO(out)) as im:
            im.verify()
    except Exception as e:
        raise ValueError(t("cull.parse.verify_decode", err=e))
    if not dry:
        tmp = path.with_name(path.name + ".cull-tmp")
        tmp.write_bytes(out)
        try:
            shutil.copymode(path, tmp)
        except OSError:
            pass
        os.replace(tmp, path)
    return "written"


def _app1(packet: bytes) -> bytes:
    payload = XMP_APP1_ID + packet
    if len(payload) + 2 > 0xFFFF:
        raise ValueError(t("cull.parse.xmp_too_big"))
    return b"\xff\xe1" + (len(payload) + 2).to_bytes(2, "big") + payload


def apply_marks(p: Photo, dry: bool, jpeg_embed: bool = True, xmp_all: bool = False) -> list[str]:
    """把同一张照片的星级／色标同步写到配对的每个文件。返回写入了哪些。"""
    files = [Path(m) for m in (p.members or [p.path])]
    raws = [f for f in files if f.suffix.lower() in RAW_EXT]
    jpgs = [f for f in files if f.suffix.lower() in JPEG_EXT]
    others = [f for f in files if f not in raws and f not in jpgs]
    done = []
    if raws or (xmp_all and (others or (jpgs and not jpeg_embed))):
        write_sidecar(sidecar_path(files[0]), p.stars, p.label, dry)
        done.append("XMP")
    if jpeg_embed:
        for j in jpgs:
            jpeg_set_rating(j, p.stars, p.label, dry)
            done.append(j.suffix.upper().lstrip("."))
    return done


# ───────────────────────── 同步删除（移到废纸篓） ─────────────────────────

def trash_photo(p: Photo, root: Path) -> list[str]:
    """把配对的所有文件及其 XMP 一起移到废纸篓；没有 send2trash 时移到 照片文件夹/_待删除。"""
    files = [Path(m) for m in (p.members or [p.path])]
    side = sidecar_path(files[0])
    targets = [f for f in files + [side, side.with_suffix(".xmp.cull-bak")] if f.exists()]
    try:
        from send2trash import send2trash
    except ImportError:
        send2trash = None
    moved = []
    for t in targets:
        if send2trash:
            send2trash(str(t))
        else:
            try:
                rel = t.resolve().relative_to(root.resolve())
            except ValueError:
                rel = Path(t.name)
            dest = root / TRASH_DIR / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(t), str(dest))
        moved.append(t.name)
    p.trashed = True
    return moved


# ───────────────────────── 整理输出（分文件夹＋重命名） ─────────────────────────

ORG_MANIFEST = ".photo-cull-organize.json"     # 记录上次整理到哪里，重新整理时原地挪动而不是再复制一份
RAW_DIR, JPEG_DIR = "RAW", "JPEG"


def result_dirs(meta_or_stats: dict | None = None) -> tuple[str, str]:
    """保留／淘汰 两个文件夹的名字：沿用上次整理记录里的；没有记录时按当前语言（中文为「保留」「淘汰」）。"""
    d = meta_or_stats or {}
    if d.get("out") and not d.get("keep_dir"):          # 1.5 及以前的整理记录：当时用的是中文名
        return "保留", "淘汰"
    return d.get("keep_dir") or t("cull.org.kept"), d.get("reject_dir") or t("cull.org.rejected")


def _safe(text: str) -> str:
    return re.sub(r'[\\/:*?"<>|\s]+', "-", (text or "").strip()).strip("-.")[:40]


def org_name(p: Photo, f: Path, rename: bool) -> str:
    """星级_机型_原文件名，例如 4_ILCE-1M2_DSC01234.ARW；淘汰为 X_，未评分为 0_。"""
    model = _safe(p.camera)
    name = f.name
    if model:   # 已经整理过一次（移动模式再次整理）的文件，先去掉旧前缀，避免叠成 3_A_4_A_xxx
        name = re.sub(rf"^(?:X|[0-5])_{re.escape(model)}_", "", name)
    if not rename:
        return name
    star = "X" if p.stars < 0 else str(max(0, int(p.stars)))
    return f"{star}_{model}_{name}" if model else f"{star}_{name}"


def org_dest(p: Photo, f: Path, out_root: Path, by_result: bool, by_format: bool, rename: bool,
             dirs: tuple[str, str] | None = None) -> Path:
    d = out_root
    if by_result:
        keep, reject = dirs or result_dirs()
        d = d / (reject if p.stars < 0 else keep)
    if by_format:
        d = d / (RAW_DIR if f.suffix.lower() in RAW_EXT else JPEG_DIR)
    return d / org_name(p, f, rename)


def _same_file(a: Path, b: Path) -> bool:
    try:
        sa, sb = a.stat(), b.stat()
        return sa.st_size == sb.st_size and int(sa.st_mtime) == int(sb.st_mtime)
    except OSError:
        return False


def organize(photos: list[Photo], out_root, by_result=True, by_format=True, rename=True, move=False,
             dry=False, dirs: tuple[str, str] | None = None) -> dict:
    """把评分后的照片整理到输出文件夹。
    复制：原文件不动；再次整理时，上一次的副本按新星级换位置／换名字，不会多出一份。
    移动：原文件夹里就没有了，结果里的路径同步更新，之后在报告里改星级、删除仍然有效。
    配对的 RAW／JPEG 一起处理并共用同一个防重名后缀；边车 XMP 跟着 RAW 走、一起改名。"""
    out_root = Path(out_root).expanduser().resolve()
    man_path = out_root / ORG_MANIFEST
    try:
        manifest = json.loads(man_path.read_text(encoding="utf-8"))
    except Exception:
        manifest = {}
    stats = {"out": str(out_root), "photos": 0, "files": 0, "kept": 0, "rejected": 0, "skipped": 0,
             "mode": "move" if move else "copy", "dry_run": dry, "plan": [], "errors": [],
             "by_result": bool(by_result), "by_format": bool(by_format), "rename": bool(rename)}
    dirs = dirs or result_dirs()
    stats["keep_dir"], stats["reject_dir"] = dirs
    taken: set = set()
    for p in photos:
        if p.trashed or p.tier == "error":
            stats["skipped"] += 1
            continue
        files = [Path(m).resolve() for m in (p.members or [p.path])]
        side_owner = next((f for f in files if f.suffix.lower() in RAW_EXT), files[0])
        mine = {str(f): Path(manifest[str(f)]) for f in files if not move and str(f) in manifest}
        base = {f: org_dest(p, f, out_root, by_result, by_format, rename, dirs) for f in files}

        def free(d: Path, f: Path) -> bool:
            if str(d) in taken:
                return False
            return d == f or not d.exists() or (not move and mine.get(str(f)) == d)

        dests, n = dict(base), 2
        while not all(free(d, f) for f, d in dests.items()):
            dests = {f: d.with_name(f"{d.stem}-{n}{d.suffix}") for f, d in base.items()}
            n += 1
        taken.update(str(d) for d in dests.values())

        new_members = [str(f) for f in files]
        for i, f in enumerate(files):
            dest = dests[f]
            side = sidecar_path(f) if f == side_owner else None
            dside = dest.with_suffix(".xmp")
            if dest == f:          # 输出文件夹就是原位置且名字不变
                continue
            prev = mine.get(str(f))
            if not move and prev == dest and _same_file(f, dest):
                if side is not None and side.exists() and not dry:   # 星级没变，只刷新一下 XMP
                    shutil.copy2(side, dside)
                continue
            stats["plan"].append([str(f), str(dest)])
            if dry:
                stats["files"] += 1
                continue
            try:
                _org_file(f, dest, side, dside, prev, move, out_root)
            except Exception as e:      # 单个文件出错（被占用、磁盘满等）不影响其余照片
                stats["errors"].append(f"{f.name}: {e}")
                continue
            stats["files"] += 1
            if move:
                new_members[i] = str(dest)
            manifest[str(f)] = str(dest)
        if move and not dry:
            p.members = new_members
            p.path = new_members[0]
        stats["photos"] += 1
        stats["rejected" if p.stars < 0 else "kept"] += 1
    if not dry and (manifest or man_path.exists()):
        out_root.mkdir(parents=True, exist_ok=True)
        man_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    return stats


def org_count(photos: list[Photo], org: dict):
    live = [p for p in photos if not p.trashed and p.tier != "error"]
    org["photos"] = len(live)
    org["rejected"] = sum(1 for p in live if p.stars < 0)
    org["kept"] = org["photos"] - org["rejected"]


def org_resync(p: Photo, photos: list[Photo], meta: dict) -> dict | None:
    """报告里改了星级后，按上次的整理设置把这张照片在输出文件夹里换到新位置／新名字。"""
    org = meta.get("organized")
    if not org or org.get("dry_run") or p.trashed:
        return None
    st = organize([p], org["out"], org.get("by_result", True), org.get("by_format", True),
                  org.get("rename", True), org.get("mode") == "move",
                  dirs=result_dirs(org))
    org_count(photos, org)
    return st


def org_trash_copies(p: Photo, meta: dict) -> list[str]:
    """复制模式下删除照片时，输出文件夹里的那份副本也一起删。"""
    org = meta.get("organized")
    if not org or org.get("mode") != "copy" or org.get("dry_run"):
        return []
    out_root = Path(org["out"])
    man_path = out_root / ORG_MANIFEST
    try:
        manifest = json.loads(man_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    copies = [manifest.pop(str(Path(m).resolve()), None) for m in (p.members or [p.path])]
    copies = [c for c in copies if c and Path(c).exists() and out_root in Path(c).parents]
    if not copies:
        return []
    copies.sort(key=lambda c: Path(c).suffix.lower() not in RAW_EXT)   # RAW 在前，边车 XMP 跟着它
    import dataclasses
    moved = trash_photo(dataclasses.replace(p, members=copies, path=copies[0], trashed=False), out_root)
    man_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    return moved


def _org_file(f: Path, dest: Path, side, dside: Path, prev, move: bool, out_root: Path):
    if not f.exists():
        raise RuntimeError(t("server.file_missing"))
    dest.parent.mkdir(parents=True, exist_ok=True)
    if move:
        shutil.move(str(f), str(dest))
        if side is not None and side.exists():
            shutil.move(str(side), str(dside))
            bak = side.with_suffix(".xmp.cull-bak")
            if bak.exists():
                shutil.move(str(bak), str(dest.with_suffix(".xmp.cull-bak")))
    else:
        if prev and prev != dest and prev.exists() and out_root in prev.parents:
            prev.unlink()                       # 上次整理出的旧副本（只删输出文件夹里自己放的）
            if side is not None and prev.with_suffix(".xmp").exists():
                prev.with_suffix(".xmp").unlink()
        shutil.copy2(str(f), str(dest))
        if side is not None and side.exists():
            shutil.copy2(str(side), str(dside))


# ───────────────────────── 报告与结果文件 ─────────────────────────

REPORT_PREFIXES = ("common", "report", "flag", "genre", "tier")


def tier_text(tier: str, lang: str | None = None) -> str:
    return t("tier." + tier, lang) if tier in ("candidate", "alt", "reject", "error") else tier
PHOTO_FIELDS = set(Photo.__dataclass_fields__)


def load_results(out: Path) -> tuple[list[Photo], dict]:
    rows = json.loads((out / "results.json").read_text(encoding="utf-8"))
    photos = [Photo(**{k: v for k, v in r.items() if k in PHOTO_FIELDS}) for r in rows]
    for p in photos:                       # 旧版本保存的中文问题标记／题材 → 代码
        p.flags = [flag_code(f) for f in p.flags]
        if p.ai and p.ai.get("genre") in GENRE_LEGACY:
            p.ai["genre"] = GENRE_LEGACY[p.ai["genre"]]
    meta_path = out / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    return photos, meta


def summarize(photos: list[Photo], out: Path, meta: dict) -> dict:
    live = [p for p in photos if not p.trashed]
    c = {}
    for p in live:
        c[p.tier] = c.get(p.tier, 0) + 1
    return {"out": str(out), "report": str(out / "report.html"), "total": len(live),
            "candidate": c.get("candidate", 0), "alt": c.get("alt", 0), "reject": c.get("reject", 0),
            "error": c.get("error", 0), "top": sum(1 for p in live if p.stars >= 4),
            "pairs": sum(1 for p in live if len(p.members) > 1),
            "trashed": sum(1 for p in photos if p.trashed),
            "xmp": meta.get("xmp", 0), "dry_run": meta.get("dry_run", False),
            "organized": {k: v for k, v in (meta.get("organized") or {}).items() if k != "plan"} or None}


def write_report(photos: list[Photo], out: Path, meta: dict, lang: str | None = None):
    """results.json／meta.json／results.csv，以及独立的 report.html。
    报告页由 web/report/ 的模板生成：样式、脚本和当前语言的语言包都内联进去，
    所以 report.html 单独拷走（或直接双击打开）也能看。"""
    lang = lang or i18n.current()
    rows = [asdict(p) for p in photos]
    tmp = out / "results.json.tmp"
    tmp.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(out / "results.json")
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    sep = t("cull.msg.list_sep", lang)
    with open(out / "results.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow([t("report.csv." + k, lang) for k in ("file", "pair", "result", "stars", "label", "local", "ai",
                                                       "ai_score", "blur", "faces", "burst", "issues", "comment", "deleted")])
        for p in photos:
            a = p.ai or {}
            w.writerow([p.name, " + ".join(Path(m).name for m in p.members), tier_text(p.tier, lang),
                        p.stars, p.label, p.local_score, a.get("provider", ""), a.get("overall", ""), p.blur,
                        p.faces, f"{p.group}/{p.group_size}", sep.join(flag_text(x, lang) for x in p.flags),
                        a.get("comment", ""), t("report.csv.yes", lang) if p.trashed else ""])
    web = Path(__file__).resolve().parent / "web"
    page = (web / "report" / "report.html").read_text(encoding="utf-8")
    css = (web / "common" / "tokens.css").read_text(encoding="utf-8") + "\n" + (web / "report" / "report.css").read_text(encoding="utf-8")
    js = (web / "common" / "i18n.js").read_text(encoding="utf-8") + "\n" + (web / "report" / "report.js").read_text(encoding="utf-8")
    b = i18n.bundle(None, lang)
    d = {k: v for k, v in b["dict"].items() if k.split(".", 1)[0] in REPORT_PREFIXES}
    d["common.trash"] = d.get("common.trash_win" if os.name == "nt" else "common.trash_mac", "")
    safe = lambda obj: json.dumps(obj, ensure_ascii=False).replace("</", "<\\/")
    info = {"src": meta.get("src", ""), "when": datetime.now().strftime("%Y-%m-%d %H:%M"), "ver": VERSION}
    for k, v in {"__LANG__": i18n.html_lang(lang), "__CSS__": css, "__I18N__": safe({"lang": lang, "langs": b["langs"], "dict": d}),
                 "__DATA__": safe(rows), "__INFO__": safe(info), "__JS__": js.replace("</script", "<\\/script")}.items():
        page = page.replace(k, v)
    (out / "report.html").write_text(page, encoding="utf-8")


# ───────────────────────── 主流程 ─────────────────────────

def collect(src: Path, recursive: bool) -> list[list[Path]]:
    """按 同一文件夹＋同名（不分大小写）分组：RAW 与 JPEG／HIF 自动配对。"""
    it = src.rglob("*") if recursive else src.iterdir()
    groups: dict = {}
    org_roots = {m.parent for m in src.rglob(ORG_MANIFEST) if m.parent != src} if recursive else set()
    for f in it:
        if (not f.is_file() or f.name.startswith(".") or f.suffix.lower() not in RAW_EXT | IMG_EXT
                or "photo-cull-report" in f.parts or TRASH_DIR in f.parts
                or any(r in f.parents for r in org_roots)):
            continue
        groups.setdefault((str(f.parent), f.stem.lower()), []).append(f)
    order = lambda f: (0 if f.suffix.lower() in RAW_EXT else 1 if f.suffix.lower() in JPEG_EXT else 2, f.name)
    return [sorted(g, key=order) for _, g in sorted(groups.items())]


def process_one(members: list[Path], thumbs: Path, keep_preview: bool):
    primary = members[0]
    p = Photo(path=str(primary), name=primary.name, kind="raw" if primary.suffix.lower() in RAW_EXT else "image",
              members=[str(m) for m in members])
    # 分析优先用相机直出 JPEG（全尺寸、颜色即机内效果）；失败再用 RAW 内嵌预览
    candidates = [m for m in members if m.suffix.lower() in JPEG_EXT] + [m for m in members if m.suffix.lower() not in JPEG_EXT]
    img, errors = None, []
    for src in candidates:
        try:
            e = read_exif(src)
            img = load_preview(src)       # 评分按全尺寸解码（模糊阈值据此调定），之后只缩放一次
            p.source = str(src)
            break
        except Exception as ex:
            errors.append(f"{src.name}: {type(ex).__name__}: {ex}")
    try:
        if img is None:
            raise RuntimeError("; ".join(errors) or t("cull.msg.unreadable"))
        if not e.get("dt") and p.kind == "raw":
            e = {**read_exif(primary), **{k: v for k, v in e.items() if v}}
        p.time = capture_time(e, primary)
        p.time_text = datetime.fromtimestamp(p.time).strftime("%Y-%m-%d %H:%M:%S")
        p.camera, p.lens, p.exposure = e.get("model", ""), e.get("lens", ""), exposure_text(e)
        img = analyze(img, p)          # 换成 2400 的那张，后面的缩略图、AI 用图都从它缩
        tname = hashlib.sha1(str(primary).encode()).hexdigest()[:16] + ".jpg"
        _fit(img, THUMB_SIDE).save(thumbs / tname, "JPEG", quality=82)
        p.thumb = "thumbs/" + tname
    except Exception as ex:
        p.error = f"{type(ex).__name__}: {ex}"
        img = None
    return p, (_fit(img, AI_SIDE) if (img is not None and keep_preview) else None)


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
