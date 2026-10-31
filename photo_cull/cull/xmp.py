from __future__ import annotations

import io
import os
import re
import shutil
from pathlib import Path

from PIL import Image

from ..i18n import t
from ..imaging.formats import JPEG_EXT, RAW_EXT
from ..version import VERSION
from .model import Photo

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
