from __future__ import annotations

import struct as _st
from pathlib import Path

from ..i18n import t

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
        for kind, tags in self.ifds:
            if 0x201 in tags and 0x202 in tags:
                off, n = tags[0x201], tags[0x202]
                if isinstance(off, int) and isinstance(n, int) and n > 1000:
                    cands.append((off, n))
            comp, photo = tags.get(0x103), tags.get(0x106)
            strips, counts = tags.get(0x111), tags.get(0x117)
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
