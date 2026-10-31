"""测试素材：全部用代码生成，不需要真实照片。

build(d)：清晰／模糊／过曝 JPEG、合成富士 RAF（带内嵌 JPEG＋EXIF）、RAF＋JPG 配对，拍摄时间相隔几分钟（各自成组）。
build_burst(d)：一组 4 张的连拍（1 秒间隔、同一画面、清晰度不同）＋ 两张单张。
"""
from __future__ import annotations

import io
import struct
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter


def exif_bytes(model, dt, make="SONY"):
    ex = Image.Exif()
    ex[0x010F] = make
    ex[0x0110] = model
    ex[0x0132] = dt
    sub = ex.get_ifd(0x8769)
    sub[0x9003] = dt
    sub[0x829A] = 1 / 250
    sub[0x829D] = 2.8
    sub[0x8827] = 400
    sub[0x920A] = 35.0
    sub[0xA434] = "TEST LENS 35mm"
    return ex.tobytes()


def img(kind, seed, blur=0.0, size=(2400, 1600)):
    w, h = size
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:h, 0:w]
    a = np.zeros((h, w, 3), np.float32)
    a += (np.sin(xx / (7 + seed)) * np.cos(yy / (9 + seed)))[..., None] * 60 + 120
    a += rng.normal(0, 25, a.shape)
    for _ in range(40):
        x, y = rng.integers(0, w - 100), rng.integers(0, h - 100)
        a[y:y + 80, x:x + 80] = rng.integers(0, 255, 3)
    im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    if kind == "blur":
        im = im.filter(ImageFilter.GaussianBlur(14))
    elif blur:
        im = im.filter(ImageFilter.GaussianBlur(blur))
    if kind == "white":
        im = Image.fromarray(np.clip(np.asarray(im).astype(np.float32) * 0.2 + 235, 0, 255).astype(np.uint8))
    return im


def jpeg(im, model, dt, make="SONY"):
    b = io.BytesIO()
    im.save(b, "JPEG", quality=90, exif=exif_bytes(model, dt, make))
    return b.getvalue()


def raf(jp: bytes) -> bytes:
    head = bytearray(b"FUJIFILMCCD-RAW 0201FF383501" + b"X-T5".ljust(32, b"\0"))
    head = head.ljust(100, b"\0")
    off = 160
    struct.pack_into(">II", head, 84, off, len(jp))
    return bytes(head).ljust(off, b"\0") + jp + b"\x00" * 50000   # 后面假装是 CFA 数据


def build(d: Path) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    t = lambda m: f"2026:10:01 10:{m:02d}:00"
    (d / "DSC01234.JPG").write_bytes(jpeg(img("sharp", 1), "ILCE-1M2", t(1)))
    (d / "DSC01235.JPG").write_bytes(jpeg(img("blur", 2), "ILCE-1M2", t(4)))
    (d / "L1003467.JPG").write_bytes(jpeg(img("sharp", 3), "LEICA M11-D", t(8), "Leica Camera AG"))
    (d / "L1003468.JPG").write_bytes(jpeg(img("white", 4), "LEICA M11-D", t(12), "Leica Camera AG"))
    (d / "DSCF0001.RAF").write_bytes(raf(jpeg(img("sharp", 5), "X-T5", t(16), "FUJIFILM")))
    (d / "DSCF0002.RAF").write_bytes(raf(jpeg(img("blur", 6), "X-T5", t(20), "FUJIFILM")))
    j = jpeg(img("sharp", 7), "X-T5", t(24), "FUJIFILM")
    (d / "DSCF0003.RAF").write_bytes(raf(j))
    (d / "DSCF0003.JPG").write_bytes(j)
    return d


def build_burst(d: Path) -> Path:
    """连拍 4 张（同一画面，第 3 张最清晰）＋ 单张 2 张（相隔几分钟、画面不同）。"""
    d.mkdir(parents=True, exist_ok=True)
    for i, b in enumerate((2.2, 1.2, 0.0, 1.6)):
        (d / f"DSC0200{i}.JPG").write_bytes(jpeg(img("sharp", 11, blur=b), "ILCE-1M2", f"2026:10:02 09:30:0{i}"))
    (d / "DSC02100.JPG").write_bytes(jpeg(img("sharp", 21), "ILCE-1M2", "2026:10:02 09:40:00"))
    (d / "DSC02200.JPG").write_bytes(jpeg(img("sharp", 33), "ILCE-1M2", "2026:10:02 09:50:00"))
    return d
