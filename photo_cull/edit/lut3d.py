from __future__ import annotations

import threading
from pathlib import Path

import numpy as np

from ..i18n import t
from .color import _lookup
from .logspace import guess_space
from .refs import resolve_style

# ───────────────────────── 3D LUT（四面体插值） ─────────────────────────

_TIE = np.array([2e-7, 1e-7, 0.0], np.float32)


def apply_lut3d(img: np.ndarray, table: np.ndarray, chunk: int = 1 << 18) -> np.ndarray:
    """table: [r][g][b] → (n,n,n,3)，输入 0..1。四面体插值。
    六个四面体按 r/g/b 的大小顺序选择：最大、中间、最小分量直接用 max/min 求出，
    只剩 4 次取表，比按轴号逐像素索引快约一倍，多线程时也更少占用 GIL。"""
    n = table.shape[0]
    flat = np.ascontiguousarray(table.reshape(-1, 3), dtype=np.float32)
    src = img.reshape(-1, 3)
    out = np.empty(src.shape, np.float32)
    nn, diag = n * n, n * n + n + 1
    for a in range(0, src.shape[0], chunk):
        f = np.clip(src[a:a + chunk], 0, 1).astype(np.float32, copy=False) * np.float32(n - 1)
        i0 = np.minimum(f.astype(np.int32), n - 2)          # f ≥ 0，截断即取整
        t = f - i0
        r, g, b = t[:, 0], t[:, 1], t[:, 2]
        base = (i0[:, 0] * n + i0[:, 1]) * n + i0[:, 2]
        rg, gb, rb = r >= g, g >= b, r >= b
        s_hi = np.where(rg & rb, nn, np.where(gb, n, 1)).astype(np.int32)       # 最大分量所在轴的步长
        s_lo = np.where(gb & rb, 1, np.where(~rg & ~rb, nn, n)).astype(np.int32)  # 最小分量所在轴的步长
        hi_v = np.maximum(np.maximum(r, g), b)
        lo_v = np.minimum(np.minimum(r, g), b)
        md_v = r + g + b - hi_v - lo_v
        c0 = np.take(flat, base, axis=0)
        c1 = np.take(flat, base + s_hi, axis=0)
        c2 = np.take(flat, base + (diag - s_lo), axis=0)
        c3 = np.take(flat, base + diag, axis=0)
        o = c0 + hi_v[:, None] * (c1 - c0)
        o += md_v[:, None] * (c2 - c1)
        o += lo_v[:, None] * (c3 - c2)
        out[a:a + chunk] = o
    return out.reshape(img.shape)


def apply_lut1d(img: np.ndarray, table: np.ndarray) -> np.ndarray:
    xs = np.linspace(0, 1, 4096)
    out = np.empty_like(img, dtype=np.float32)
    for c in range(3):
        dense = np.interp(xs, np.linspace(0, 1, table.shape[0]), table[:, c]).astype(np.float32)
        out[..., c] = _lookup(img[..., c], dense)
    return out


_LUT_CACHE: dict = {}
_CACHE_LOCK = threading.Lock()


def load_cube(path: str) -> dict:
    p = Path(resolve_style(path))
    key = (str(p), p.stat().st_mtime)
    with _CACHE_LOCK:
        if key in _LUT_CACHE:
            return _LUT_CACHE[key]
    title, size3, size1 = "", 0, 0
    dmin, dmax = np.zeros(3, np.float32), np.ones(3, np.float32)
    nums = []
    with open(p, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            c = s[0]
            if c.isdigit() or c in "-+.":
                nums.append(s)
                continue
            parts = s.split()
            k = parts[0].upper()
            if k == "TITLE":
                title = s[5:].strip().strip('"')
            elif k == "LUT_3D_SIZE":
                size3 = int(parts[1])
                if not 2 <= size3 <= 129:
                    raise ValueError(t("edit.err.lut_size3", n=size3))
            elif k == "LUT_1D_SIZE":
                size1 = int(parts[1])
                if not 2 <= size1 <= 65536:
                    raise ValueError(t("edit.err.lut_size1", n=size1))
            elif k == "DOMAIN_MIN":
                dmin = np.array([float(v) for v in parts[1:4]], np.float32)
            elif k == "DOMAIN_MAX":
                dmax = np.array([float(v) for v in parts[1:4]], np.float32)
    data = np.array(" ".join(nums).split(), dtype=np.float32)
    if size3:
        need = size3 ** 3 * 3
        if data.size < need:
            raise ValueError(t("edit.err.cube_incomplete"))
        table = data[:need].reshape(size3, size3, size3, 3).transpose(2, 1, 0, 3).copy()   # 文件里 R 变化最快
        kind = "3d"
    elif size1:
        if data.size < size1 * 3:
            raise ValueError(t("edit.err.cube_incomplete"))
        table = data[:size1 * 3].reshape(size1, 3)
        kind = "1d"
    else:
        raise ValueError(t("edit.err.cube_invalid"))
    space, warn = guess_space(str(p))
    res = {"kind": kind, "table": table, "size": size3 or size1, "title": title or p.stem,
           "dmin": dmin, "dmax": dmax, "space": space, "warning": warn}
    with _CACHE_LOCK:
        if len(_LUT_CACHE) > 24:
            _LUT_CACHE.clear()
        _LUT_CACHE[key] = res
    return res


def apply_cube(img: np.ndarray, cube: dict) -> np.ndarray:
    x = (img - cube["dmin"]) / np.maximum(cube["dmax"] - cube["dmin"], 1e-6)
    return apply_lut3d(x, cube["table"]) if cube["kind"] == "3d" else apply_lut1d(x, cube["table"])
