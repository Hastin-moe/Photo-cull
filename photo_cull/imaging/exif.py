from __future__ import annotations

import io
import re
import struct as _st
from datetime import datetime
from pathlib import Path

from PIL import Image

from .formats import RAW_EXT, _ensure_heif
from .tiffraw import raf_jpeg, tiff_exif


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
