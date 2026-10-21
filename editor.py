#!/usr/bin/env python3
"""照片筛选工具 · 编辑模块（基础版）

整张画面的调整：色温／色调、曝光、对比度、高光／阴影／白色／黑色、清晰度、自然饱和度／饱和度、
RGB 与分通道曲线；套用 .cube LUT（sRGB 或相机 Log）和 Lightroom／Photoshop XMP 预设
（解码其中的 RGBTable／LookTable 色彩表）；导出 JPEG／16 位 TIFF。

RAW 解码用 LibRaw（rawpy）：支持徕卡 DNG、松下 DNG／RW2、索尼全部 ARW（含压缩、无损压缩）。
原文件永远不会被修改；编辑记录保存在 照片文件夹/photo-cull-report/edits/。
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import os
import re
import struct
import threading
import time
import zlib
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

import cull

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None

RAW_EXT = cull.RAW_EXT
EDIT_EXT = RAW_EXT | {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".heic", ".heif", ".hif", ".webp"}
PREVIEW_SIDE = 2880          # 预览的最大清晰度（长边像素）；实际按界面显示大小和屏幕密度挑一档
PREVIEW_LEVELS = (1400, 1800, 2400, 2880)
FAST_RATIO = 0.45            # 拖动滑块时的预览：长边为当前档位的这个比例
STRIP_ROWS = 1024            # 导出时分条渲染，避免 6000 万像素一次性占满内存（每条内部再多线程）
EDIT_VERSION = 1

# LUT 使用范围（当前设定）：
#  · 输入空间统一为 sRGB，对应索尼「ST 标准」／徕卡「STD」的机内画面
#  · 素材库只列出下面这些子文件夹（相对素材库根目录）；根目录里没有这些文件夹时列出全部
#  · 相机 Log（S-Log3 等）转换暂不启用
ENABLE_LOG = False
LIBRARY_SCOPE = ()   # 非内置素材库：留空＝列出文件夹里全部 LUT／预设

# 内置 LUT：工具文件夹里的 luts/（39 个，工作空间均为 sRGB：Fujifilm GFX 胶片模拟 20、Leica Look 19），拷到别的电脑也能直接用。
# 编辑记录里写成「builtin:相对路径」，不依赖这台电脑上的绝对路径。
LUT_DIR = Path(__file__).resolve().parent / "luts"
BUILTIN = "builtin:"
# 用户自己添加的 LUT：放在设置文件夹里，升级／重装工具不会丢，也不会混进项目源码
USER_LUT_DIR = Path.home() / ".photo-cull" / "luts"
USER = "user:"
USER_GROUP = "我的 LUT"
USER_LUT_MAX = 64 * 1024 * 1024        # 单个 .cube 最大 64 MB（65³ 的 LUT 约 9 MB）
_BUILTIN_INDEX: dict = {}


def _builtin_index() -> dict:
    if not _BUILTIN_INDEX and LUT_DIR.is_dir():
        for f in LUT_DIR.rglob("*.cube"):
            _BUILTIN_INDEX.setdefault(f.name.lower(), f)
    return _BUILTIN_INDEX


def style_ref(path: str) -> str:
    """素材的引用：内置 LUT 写成 builtin:相对路径，其他保持原路径。"""
    for base, prefix in ((LUT_DIR, BUILTIN), (USER_LUT_DIR, USER)):
        try:
            return prefix + Path(path).resolve().relative_to(base.resolve()).as_posix()
        except (ValueError, OSError):
            pass
    return str(path)


def resolve_style(ref: str) -> str:
    """引用 → 实际文件。旧编辑记录里桌面「预设与LUT」的路径找不到时，按文件名对应到内置的同名 LUT。"""
    if ref.startswith(USER):
        return str(USER_LUT_DIR / ref[len(USER):])
    if ref.startswith(BUILTIN):
        rel = ref[len(BUILTIN):]
        if (LUT_DIR / rel).is_file():
            return str(LUT_DIR / rel)
        hit = _alias_lookup(rel)
        return str(hit) if hit else str(LUT_DIR / rel)
    p = Path(ref)
    if not p.exists() and p.suffix.lower() == ".cube":
        hit = _alias_lookup(p.name, p.parent.name) or _builtin_index().get(p.name.lower())
        if hit:
            return str(hit)
    return ref


_ALIASES: dict | None = None


def _alias_lookup(name: str, parent: str = "") -> Path | None:
    """旧版本（改名前）的 LUT 引用 → 现在的内置文件。对照表放在工具文件夹或 ~/.photo-cull 里的 lut-aliases.json（可选，没有就跳过，不随项目发布）。
    格式：{"旧文件名.cube": "新文件夹/新文件名.cube", "旧文件夹/旧文件名.cube": "…"}，键用小写。"""
    global _ALIASES
    if _ALIASES is None:
        _ALIASES = {}
        for f in (LUT_DIR.parent / "lut-aliases.json", Path.home() / ".photo-cull" / "lut-aliases.json"):
            try:
                _ALIASES.update({k.lower(): v for k, v in json.loads(f.read_text(encoding="utf-8")).items()})
            except (OSError, ValueError, AttributeError):
                pass
    base = name.replace("\\", "/").split("/")[-1].lower()
    dirn = name.replace("\\", "/").rsplit("/", 1)[0].split("/")[-1].lower() if "/" in name.replace("\\", "/") else parent.lower()
    for k in (f"{dirn}/{base}", base):
        v = _ALIASES.get(k)
        if v and (LUT_DIR / v).is_file():
            return LUT_DIR / v
    return None

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
        out["vignette"] = {"lens": vg["lens"], "level": vg.get("level") if vg.get("level") in VIG_LEVELS else "mid"}
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


# ───────────────────────── 色彩数学 ─────────────────────────

# LibRaw／dcraw 的 sRGB→ProPhoto 矩阵（已含 D65→D50 色适应）；RAW 以线性 ProPhoto 解码
SRGB_TO_PP = np.array([[0.529317, 0.330092, 0.140588],
                       [0.098368, 0.873465, 0.028169],
                       [0.016879, 0.117663, 0.865457]], np.float64)
PP_TO_SRGB = np.linalg.inv(SRGB_TO_PP)
PP_Y = np.array([0.2880402, 0.7118741, 0.0000857], np.float32)
REC709_Y = np.array([0.2126, 0.7152, 0.0722], np.float32)
D65 = (0.3127, 0.3290)
D50 = (0.3457, 0.3585)
PRIMARIES = {
    "srgb": ((0.640, 0.330), (0.300, 0.600), (0.150, 0.060), D65),
    "adobe": ((0.640, 0.330), (0.210, 0.710), (0.150, 0.060), D65),
    "prophoto": ((0.7347, 0.2653), (0.1596, 0.8404), (0.0366, 0.0001), D50),
    "p3": ((0.680, 0.320), (0.265, 0.690), (0.150, 0.060), D65),
    "rec2020": ((0.708, 0.292), (0.170, 0.797), (0.131, 0.046), D65),
    "sgamut3cine": ((0.766, 0.275), (0.225, 0.800), (0.089, -0.087), D65),
    "vgamut": ((0.730, 0.280), (0.165, 0.840), (0.100, -0.030), D65),
    "dgamut": ((0.71, 0.31), (0.21, 0.88), (0.09, -0.08), D65),
}


def _xyz(xy):
    x, y = xy
    return np.array([x / y, 1.0, (1 - x - y) / y])


def rgb_to_xyz(name: str) -> np.ndarray:
    r, g, b, w = PRIMARIES[name]
    P = np.stack([_xyz(r), _xyz(g), _xyz(b)], axis=1)
    S = np.linalg.solve(P, _xyz(w))
    return P * S


def bradford(src, dst) -> np.ndarray:
    M = np.array([[0.8951, 0.2664, -0.1614], [-0.7502, 1.7135, 0.0367], [0.0389, -0.0685, 1.0296]])
    s, d = M @ _xyz(src), M @ _xyz(dst)
    return np.linalg.inv(M) @ np.diag(d / s) @ M


def srgb_to(name: str) -> np.ndarray:
    """线性 sRGB → 线性目标色彩空间（D50 空间自动做 Bradford 色适应）。"""
    xyz = rgb_to_xyz("srgb")
    white = PRIMARIES[name][3]
    if white != D65:
        xyz = bradford(D65, white) @ xyz
    return np.linalg.inv(rgb_to_xyz(name)) @ xyz


_LUT_N = 65536      # 查表精度：65536 级，误差远小于 8 位显示的一级
_ENC_X = np.linspace(0, 1, _LUT_N, dtype=np.float64)
_ENC_Y = np.where(_ENC_X <= 0.0031308, 12.92 * _ENC_X, 1.055 * np.power(_ENC_X, 1 / 2.4) - 0.055).astype(np.float32)
_DEC_Y = np.where(_ENC_X <= 0.04045, _ENC_X / 12.92, np.power((_ENC_X + 0.055) / 1.055, 2.4)).astype(np.float32)


def _index(x, n: int) -> np.ndarray:
    f = np.multiply(x, np.float32(n), dtype=np.float32)
    np.clip(f, 0, n, out=f)
    f += np.float32(0.5)
    return f.astype(np.int32)


def _lookup(x, table):
    """0..1 → 查表（最近邻，表足够密，比 np.interp 快一个数量级）。用下标索引而不是 np.take：结果保持输入的内存布局。"""
    return table[_index(x, table.shape[0] - 1)]


def _chain(first: np.ndarray, then: np.ndarray) -> np.ndarray:
    """两张查找表合成一张：_lookup(_lookup(x, first), then) ＝ _lookup(x, _chain(first, then))，结果逐位相同、少遍历一次整图。"""
    return then[_index(first, then.shape[0] - 1)]


# 内存布局：(H, W, 3) 的图在内存里按「R 平面、G 平面、B 平面」存放（通道步长最大）。
# 逐通道运算、按通道求最大／最小值时，这种布局比逐像素交错快好几倍，整条管线都保持它。
def planar_empty(h: int, w: int) -> np.ndarray:
    return np.empty((3, h, w), np.float32).transpose(1, 2, 0)


def is_planar(a: np.ndarray) -> bool:
    return a.ndim == 3 and a.shape[2] == 3 and a.strides[2] == a.shape[0] * a.shape[1] * a.itemsize \
        and a.strides[1] == a.itemsize and a.strides[0] == a.shape[1] * a.itemsize


def as_planar(a: np.ndarray, scale: float | None = None) -> np.ndarray:
    """转成平面布局的 float32（已经是就直接返回）；scale 用于 uint16 → 0..1。"""
    if scale is None and a.dtype == np.float32 and is_planar(a):
        return a
    out = planar_empty(a.shape[0], a.shape[1])
    if scale is None:
        np.copyto(out, a, casting="unsafe")
    else:
        np.multiply(a, np.float32(scale), out=out, casting="unsafe")
    return out


def srgb_encode(x):
    return _lookup(x, _ENC_Y)


def srgb_decode(x):
    return _lookup(x, _DEC_Y)


def mat(img: np.ndarray, M: np.ndarray) -> np.ndarray:
    return np.einsum("...c,dc->...d", img, M.astype(np.float32), optimize=True).astype(np.float32, copy=False)


# ───────────────────────── 相机 Log 编码（套 Log LUT 用） ─────────────────────────

def _slog3(x):
    return np.where(x >= 0.01125, (420.0 + np.log10((np.maximum(x, 0) + 0.01) / 0.19) * 261.5) / 1023.0,
                    (x * (171.2102946929 - 95.0) / 0.01125 + 95.0) / 1023.0)


def _vlog(x):
    return np.where(x < 0.01, 5.6 * x + 0.125, 0.241514 * np.log10(np.maximum(x, 0) + 0.00873) + 0.598206)


def _flog2(x):
    return np.where(x >= 0.000889, 0.245281 * np.log10(5.555556 * np.maximum(x, 0) + 0.064829) + 0.384316,
                    8.799461 * x + 0.092864)


def _applelog(x):
    r0, rt, c, b, g, d = -0.05641088, 0.01, 47.28711236, 0.00964052, 0.08550479, 0.69336945
    return np.where(x >= rt, g * np.log2(np.maximum(x, 0) + b) + d,
                    np.where(x >= r0, c * (x - r0) ** 2, 0.0))


def _dlog(x):
    return np.where(x <= 0.0078, 6.025 * x + 0.0929, np.log10(np.maximum(x, 0) * 0.9892 + 0.0108) * 0.256663 + 0.584555)


LOG_SPACES = {
    "srgb": {"name": "sRGB（索尼 ST／徕卡 STD）"},
    "slog3": {"name": "Sony S-Log3／S-Gamut3.Cine", "gamut": "sgamut3cine", "f": _slog3},
    "vlog": {"name": "Panasonic V-Log／V-Gamut", "gamut": "vgamut", "f": _vlog},
    "flog2": {"name": "Fujifilm F-Log2／F-Gamut", "gamut": "rec2020", "f": _flog2},
    "applelog": {"name": "Apple Log／Rec.2020", "gamut": "rec2020", "f": _applelog},
    "dlog": {"name": "DJI D-Log／D-Gamut", "gamut": "dgamut", "f": _dlog},
}
SUPPORTED_LOG = [
    (r"s-?log3", "slog3"), (r"v-?log", "vlog"), (r"f-?log2(?!c)", "flog2"), (r"apple-?\s?log(?!2)", "applelog"),
    (r"(?<![a-z])d-?log(?!m|\s?m\b)", "dlog"),
]
OTHER_LOG = [r"s-?log2", r"s-?log(?!\d)", r"l-?log", r"n-?log", r"logc", r"log3g10", r"bmdfilm", r"i-?log",
             r"mi-?log", r"f-?log(?!2)", r"f-?log2c", r"canon\s?log", r"log\s?[23]\b", r"dlogm", r"d-?log\s?m",
             r"apple-?\s?log2"]


def active_spaces() -> dict:
    """界面里可选的 LUT 输入空间。"""
    return {k: v["name"] for k, v in LOG_SPACES.items() if ENABLE_LOG or k == "srgb"}


def guess_space(path: str) -> tuple[str, str]:
    """根据文件名／所在文件夹猜 LUT 的输入空间。返回 (space, 提示)。"""
    sp, warn = _guess_space(path)
    if not ENABLE_LOG and sp != "srgb":
        return "srgb", "这是相机 Log 素材用的 LUT，Log 转换暂未启用；按 sRGB 套用颜色会不对"
    return sp, warn


def _guess_space(path: str) -> tuple[str, str]:
    s = path.lower().replace("_", "-")
    name = Path(path).name.lower().replace("_", "-")
    fv = "fvpro" in s.replace(" ", "")
    if fv and re.search(r"/print/", s):
        return "srgb", "这是胶片印片 LUT，要接在负片 LUT 之后使用；单独套在照片上颜色会不对"
    sp = next((spc for pat, spc in SUPPORTED_LOG if re.search(pat, name)), None)
    if sp is None:   # 文件名没写，再看所在文件夹（例如 “某相机Log版/SLog3/xxx.cube”）
        parent = str(Path(s).parent)
        if not any(re.search(pat, name) for pat in OTHER_LOG):
            sp = next((spc for pat, spc in SUPPORTED_LOG if re.search(pat, parent)), None)
            if sp is None and any(re.search(pat, parent) for pat in OTHER_LOG):
                return "srgb", "这是其他相机 Log 素材用的 LUT，编辑器暂不支持这种 Log；套在照片上颜色会不对"
    if sp is None and any(re.search(pat, name) for pat in OTHER_LOG):
        return "srgb", "这是其他相机 Log 素材用的 LUT，编辑器暂不支持这种 Log；套在照片上颜色会不对"
    if sp and fv and re.search(r"/negative/", s):
        return sp, "这是胶片负片 LUT，输出的是负片底片效果，要再接印片 LUT 才是正常画面"
    return sp or "srgb", ""


def log_encode(lin_pp: np.ndarray, space: str) -> np.ndarray:
    info = LOG_SPACES[space]
    M = srgb_to(info["gamut"]) @ PP_TO_SRGB
    return np.clip(info["f"](mat(lin_pp, M)), 0, 1).astype(np.float32)


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
                    raise ValueError(f"LUT_3D_SIZE {size3} 不合理（应为 2–129）")
            elif k == "LUT_1D_SIZE":
                size1 = int(parts[1])
                if not 2 <= size1 <= 65536:
                    raise ValueError(f"LUT_1D_SIZE {size1} 不合理（应为 2–65536）")
            elif k == "DOMAIN_MIN":
                dmin = np.array([float(v) for v in parts[1:4]], np.float32)
            elif k == "DOMAIN_MAX":
                dmax = np.array([float(v) for v in parts[1:4]], np.float32)
    data = np.array(" ".join(nums).split(), dtype=np.float32)
    if size3:
        need = size3 ** 3 * 3
        if data.size < need:
            raise ValueError("cube 数据不完整")
        table = data[:need].reshape(size3, size3, size3, 3).transpose(2, 1, 0, 3).copy()   # 文件里 R 变化最快
        kind = "3d"
    elif size1:
        if data.size < size1 * 3:
            raise ValueError("cube 数据不完整")
        table = data[:size1 * 3].reshape(size1, 3)
        kind = "1d"
    else:
        raise ValueError("不是有效的 .cube 文件（缺少 LUT_3D_SIZE／LUT_1D_SIZE）")
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


# ───────────────────────── Adobe XMP 预设：RGBTable／LookTable ─────────────────────────

_B85 = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ.-:+=^!/*?`'|()[]{}@%$#"
_B85_MAP = {c: i for i, c in enumerate(_B85)}
RGB_PRIMARIES = {0: "srgb", 1: "adobe", 2: "prophoto", 3: "p3", 4: "rec2020"}


def decode_big_table(text: str) -> bytes:
    """Adobe DNG SDK dng_big_table 的字符串编码：85 进制（自定义字母表）→ 4 字节长度 + zlib。"""
    vals = [_B85_MAP[c] for c in text if c in _B85_MAP]
    out = bytearray()
    for k in range(0, len(vals), 5):
        grp = vals[k:k + 5]
        x = 0
        for j, v in enumerate(grp):
            x += v * 85 ** j
        out += (x & 0xFFFFFFFF).to_bytes(4, "little")[:len(grp) - 1 if len(grp) < 5 else 4]
    size = struct.unpack("<I", out[:4])[0]
    raw = zlib.decompress(bytes(out[4:]))
    if len(raw) != size:
        raise ValueError("色彩表长度不符")
    return raw


def parse_table(raw: bytes) -> dict:
    typ, ver = struct.unpack("<2I", raw[:8])
    if typ == 1:                                   # RGBTable
        dims, n = struct.unpack("<2I", raw[8:16])
        if dims != 3 or not 2 <= n <= 64:
            raise ValueError("暂不支持的 RGBTable 维度")
        cnt = n ** 3 * 3
        d = np.frombuffer(raw[16:16 + cnt * 2], dtype="<u2").reshape(n, n, n, 3).astype(np.int32)
        idv = (np.arange(n) * 0xFFFF + (n >> 1)) // (n - 1)
        ident = np.stack(np.meshgrid(idv, idv, idv, indexing="ij"), axis=-1)
        absolute = ((d + ident) & 0xFFFF).astype(np.float32) / 65535.0
        tail = raw[16 + cnt * 2:]
        prim, gamma, gamut = struct.unpack("<3I", tail[:12]) if len(tail) >= 12 else (0, 1, 0)
        mn, mx = struct.unpack("<2d", tail[12:28]) if len(tail) >= 28 else (0.0, 2.0)
        return {"type": "rgb", "table": absolute, "primaries": RGB_PRIMARIES.get(prim, "srgb"),
                "gamma": gamma, "min": mn, "max": mx}
    if typ == 0:                                   # LookTable（色相／饱和度／明度）
        h, s, v = struct.unpack("<3I", raw[8:20])
        cnt = h * s * v
        deltas = np.frombuffer(raw[20:20 + cnt * 12], dtype="<f4").reshape(v, h, s, 3).copy()
        enc = struct.unpack("<I", raw[20 + cnt * 12:24 + cnt * 12])[0] if len(raw) >= 24 + cnt * 12 else 0
        return {"type": "hsv", "table": deltas, "srgb_value": enc == 1}
    raise ValueError(f"未知的色彩表类型 {typ}")


def apply_rgbtable(img_srgb: np.ndarray, t: dict, amount: float) -> np.ndarray:
    if amount <= 0:
        return img_srgb
    prim, gamma = t["primaries"], t["gamma"]
    if prim == "srgb" and gamma == 1:
        x = img_srgb
        y = apply_lut3d(x, t["table"])
    else:
        lin = srgb_decode(img_srgb)
        if prim != "srgb":
            lin = mat(lin, srgb_to(prim))
        x = _gamma_encode(np.clip(lin, 0, 1), gamma)
        y = apply_lut3d(x, t["table"])
        y = _gamma_decode(np.clip(y, 0, 1), gamma)
        x = img_srgb
        if prim != "srgb":
            y = mat(y, np.linalg.inv(srgb_to(prim)))
        y = srgb_encode(y)
    return np.clip(x + amount * (y - x), 0, 1)


def _gamma_encode(x, g):
    if g == 0:
        return x
    if g == 1:
        return srgb_encode(x)
    return np.power(x, 1 / (1.8 if g == 2 else 2.2 if g == 3 else 2.4))


def _gamma_decode(x, g):
    if g == 0:
        return x
    if g == 1:
        return srgb_decode(x)
    return np.power(x, 1.8 if g == 2 else 2.2 if g == 3 else 2.4)


def apply_huesat(lin: np.ndarray, t: dict, amount: float, chunk: int = 1 << 20) -> np.ndarray:
    """DNG HueSatMap／LookTable：在线性 ProPhoto 的 HSV 上做色相偏移、饱和度和明度缩放。"""
    if amount <= 0:
        return lin
    tab = t["table"]
    V, Hn, S = tab.shape[:3]
    flat = tab.reshape(-1, 3)
    src = lin.reshape(-1, 3)
    out = np.empty_like(src, dtype=np.float32)
    for a in range(0, src.shape[0], chunk):
        px = src[a:a + chunk]
        r, g, b = px[:, 0], px[:, 1], px[:, 2]
        mx = px.max(axis=1)
        mn = px.min(axis=1)
        dl = mx - mn
        safe = np.where(dl > 1e-9, dl, 1.0)
        h = np.where(mx == r, (g - b) / safe, np.where(mx == g, 2 + (b - r) / safe, 4 + (r - g) / safe))
        h = np.where(dl > 1e-9, np.mod(h, 6.0), 0.0)
        s = np.where(mx > 1e-9, dl / np.where(mx > 1e-9, mx, 1.0), 0.0)
        vv = srgb_encode(mx) if t["srgb_value"] else np.clip(mx, 0, 1)
        hf = h * (Hn / 6.0)
        h0 = np.floor(hf).astype(np.int32) % Hn
        h1 = (h0 + 1) % Hn
        fh = (hf - np.floor(hf)).astype(np.float32)
        if S > 1:
            sf = s * (S - 1)
            s0 = np.minimum(np.floor(sf).astype(np.int32), S - 2)
            fs = (sf - s0).astype(np.float32)
        else:
            s0 = np.zeros_like(h0)
            fs = np.zeros_like(fh)
        if V > 1:
            vf = vv * (V - 1)
            v0 = np.minimum(np.floor(vf).astype(np.int32), V - 2)
            fv = (vf - v0).astype(np.float32)
        else:
            v0 = np.zeros_like(h0)
            fv = np.zeros_like(fh)
        s1 = np.minimum(s0 + 1, S - 1)
        v1 = np.minimum(v0 + 1, V - 1)

        def g_(vi, hi, si):
            return flat[(vi * Hn + hi) * S + si]

        def lerp(a_, b_, w):
            return a_ + (b_ - a_) * w[:, None]
        c00 = lerp(g_(v0, h0, s0), g_(v0, h0, s1), fs)
        c01 = lerp(g_(v0, h1, s0), g_(v0, h1, s1), fs)
        c10 = lerp(g_(v1, h0, s0), g_(v1, h0, s1), fs)
        c11 = lerp(g_(v1, h1, s0), g_(v1, h1, s1), fs)
        d = lerp(lerp(c00, c01, fh), lerp(c10, c11, fh), fv)
        hs = d[:, 0] * amount / 60.0
        ss = 1 + (d[:, 1] - 1) * amount
        vs = 1 + (d[:, 2] - 1) * amount
        h2 = np.mod(h + hs, 6.0)
        s2 = np.clip(s * ss, 0, 1)
        v2 = mx * vs
        # HSV → RGB（向量化公式：f(n) = v − v·s·clip(min(k, 4−k), 0, 1)，k = (n + h) mod 6）
        vs_ = v2 * s2
        res = np.empty((px.shape[0], 3), np.float32)
        for j, nn in enumerate((5.0, 3.0, 1.0)):
            k = np.mod(nn + h2, 6.0)
            res[:, j] = v2 - vs_ * np.clip(np.minimum(k, 4.0 - k), 0.0, 1.0)
        out[a:a + chunk] = np.where((dl > 1e-9)[:, None], res, px * vs[:, None])
    return out.reshape(lin.shape)


# ───────────────────────── XMP 预设解析 ─────────────────────────

SLIDER_MAP = {"Exposure2012": "exposure", "Contrast2012": "contrast", "Highlights2012": "highlights",
              "Shadows2012": "shadows", "Whites2012": "whites", "Blacks2012": "blacks", "Clarity2012": "clarity",
              "Vibrance": "vibrance", "Saturation": "saturation", "IncrementalTemperature": "temp",
              "IncrementalTint": "tint"}
UNSUPPORTED_NAMES = {
    "Texture": "纹理", "Dehaze": "去朦胧", "Sharpness": "锐化", "LuminanceSmoothing": "降噪", "ColorNoiseReduction": "颜色降噪",
    "GrainAmount": "颗粒", "PostCropVignetteAmount": "暗角", "Temperature": "绝对色温", "Tint": "绝对色调",
    "ParametricShadows": "参数曲线", "ParametricDarks": "参数曲线", "ParametricLights": "参数曲线",
    "ParametricHighlights": "参数曲线", "SplitToningShadowSaturation": "分离色调", "SplitToningHighlightSaturation": "分离色调",
    "ColorGradeMidtoneSat": "颜色分级", "ColorGradeShadowSat": "颜色分级", "ColorGradeHighlightSat": "颜色分级",
    "ColorGradeGlobalSat": "颜色分级", "LensProfileEnable": "镜头校正", "PerspectiveVertical": "透视校正",
}
HSL_PREFIX = ("HueAdjustment", "SaturationAdjustment", "LuminanceAdjustment")
_PRESET_CACHE: dict = {}
_LOOK_INDEX: dict = {}


def _attrs(text: str) -> dict:
    return {k: v for k, v in re.findall(r'\bcrs:([A-Za-z0-9_]+)="([^"]*)"', text)}


def _curve(text: str, name: str):
    m = re.search(rf"<crs:{name}>\s*<rdf:Seq>(.*?)</rdf:Seq>", text, re.S)
    if not m:
        return None
    pts = []
    for li in re.findall(r"<rdf:li>\s*([^<]*)</rdf:li>", m.group(1)):
        try:
            a, b = (float(v) for v in li.split(","))
            pts.append([a / 255.0, b / 255.0])
        except ValueError:
            pass
    return pts if len(pts) >= 2 else None


def _is_identity(pts) -> bool:
    return pts is None or all(abs(a - b) < 1e-6 for a, b in pts)


def _name(text: str) -> str:
    m = re.search(r"<crs:Name>.*?<rdf:li[^>]*>([^<]*)</rdf:li>", text, re.S)
    return m.group(1).strip() if m else ""


def _tables(text: str, attrs: dict) -> dict:
    out = {}
    for key in ("RGBTable", "LookTable"):
        md5 = attrs.get(key)
        if md5:
            m = re.search(rf'crs:Table_{md5}="([^"]+)"', text)
            if m:
                out[key] = parse_table(decode_big_table(m.group(1)))
    return out


def read_preset(path: str) -> dict:
    """解析 Lightroom／Camera Raw 的 XMP 预设或外观（Look）。结果会缓存。"""
    p = Path(path)
    key = (str(p), p.stat().st_mtime)
    with _CACHE_LOCK:
        if key in _PRESET_CACHE:
            return _PRESET_CACHE[key]
    text = p.read_text(encoding="utf-8", errors="replace")
    look_block = ""
    m = re.search(r"<crs:Look>(.*?)</crs:Look>", text, re.S)
    if m:
        look_block = m.group(1)
        text_main = text[:m.start()] + text[m.end():]
    else:
        text_main = text
    attrs = _attrs(text_main)
    kind = attrs.get("PresetType", "Normal")
    res = {"path": str(p), "name": _name(text_main) or p.stem, "type": kind, "uuid": attrs.get("UUID", ""),
           "set": {}, "curves": {}, "mono": attrs.get("ConvertToGrayscale") == "True",
           "tables": {}, "look_ref": None, "unsupported": [], "profile": attrs.get("CameraProfile", ""),
           "for_raw": attrs.get("SupportsSceneReferred", "True") != "False",
           "for_jpeg": attrs.get("SupportsOutputReferred", "True") != "False"}
    for k, field in SLIDER_MAP.items():
        if k in attrs:
            try:
                res["set"][field] = float(attrs[k])
            except ValueError:
                pass
    for ch, name in (("rgb", "ToneCurvePV2012"), ("r", "ToneCurvePV2012Red"), ("g", "ToneCurvePV2012Green"),
                     ("b", "ToneCurvePV2012Blue")):
        pts = _curve(text_main, name)
        if pts and not _is_identity(pts):
            res["curves"][ch] = pts
    unsup = set()
    for k, v in attrs.items():
        label = UNSUPPORTED_NAMES.get(k)
        if label is None and k.startswith(HSL_PREFIX):
            label = "HSL 颜色调整"
        if label and v not in ("0", "+0", "0.0", "", "False", "false"):
            if k in ("Temperature", "Tint") and attrs.get("WhiteBalance") in (None, "As Shot"):
                continue
            unsup.add(label)
    if "<crs:CorrectionMasks>" in text_main or "<crs:MaskGroupBasedCorrections>" in text_main:
        unsup.add("局部调整／蒙版")
    if "HDREditMode" in attrs and attrs["HDREditMode"] == "1":
        unsup.add("HDR 编辑")
    res["unsupported"] = sorted(unsup)
    res["tables"] = _tables(text_main, attrs)
    if look_block:
        la = _attrs(look_block)
        ref = {"name": la.get("Name", ""), "uuid": la.get("UUID", ""), "amount": float(la.get("Amount", "1") or 1)}
        if "Table_" in look_block:                      # 外观数据直接内嵌在预设里
            inner = _tables(look_block, la)
            if inner:
                ref["inline"] = {"tables": inner, "curves": {}, "mono": la.get("ConvertToGrayscale") == "True"}
        res["look_ref"] = ref
    with _CACHE_LOCK:
        if len(_PRESET_CACHE) > 64:
            _PRESET_CACHE.clear()
        _PRESET_CACHE[key] = res
    return res


def _scan_looks(folder: Path) -> dict:
    """读取文件夹里所有 Look 类 XMP 的 UUID 和名称（只读文件开头，速度快）。"""
    key = (str(folder), folder.stat().st_mtime)
    if key in _LOOK_INDEX:
        return _LOOK_INDEX[key]
    idx = {}
    for f in folder.iterdir():
        if f.suffix.lower() != ".xmp" or not f.is_file():
            continue
        try:
            with open(f, "rb") as fh:
                head = fh.read(6000).decode("utf-8", errors="replace")
        except OSError:
            continue
        if 'crs:PresetType="Look"' not in head:
            continue
        a = _attrs(head.split("<crs:Look>")[0])
        nm = _name(head)
        if a.get("UUID"):
            idx[a["UUID"]] = str(f)
        if nm:
            idx.setdefault("name:" + nm, str(f))
    _LOOK_INDEX[key] = idx
    return idx


def resolve_look(preset: dict, root: str | None = None) -> str | None:
    """预设里只写了外观的 UUID／名称时，在同一文件夹及上级（不超过素材库根目录）里找对应的 Look 文件。"""
    ref = preset.get("look_ref")
    if not ref:
        return None
    here = Path(preset["path"]).parent
    stop = Path(root).resolve() if root else None
    for _ in range(4):
        try:
            idx = _scan_looks(here)
        except OSError:
            idx = {}
        hit = idx.get(ref.get("uuid", "")) or idx.get("name:" + ref.get("name", ""))
        if hit:
            return hit
        if stop is not None and here.resolve() == stop or here.parent == here:
            break
        here = here.parent
    # 再看兄弟文件夹（例如 “配置文件” 子目录）
    for sub in Path(preset["path"]).parent.parent.glob("*/"):
        try:
            idx = _scan_looks(sub)
        except OSError:
            continue
        hit = idx.get(ref.get("uuid", "")) or idx.get("name:" + ref.get("name", ""))
        if hit:
            return hit
    return None


def describe_style(path: str, root: str | None = None) -> dict:
    """给界面用：选中一个 .cube 或 .xmp 后，返回要应用的参数和说明。"""
    p = Path(resolve_style(path))
    if p.suffix.lower() == ".cube":
        c = load_cube(str(p))
        return {"kind": "lut", "name": c["title"] or p.stem, "path": style_ref(str(p)), "size": c["size"], "lut_kind": c["kind"],
                "space": c["space"], "warning": c["warning"]}
    if p.suffix.lower() != ".xmp":
        raise ValueError("只支持 .cube 和 .xmp")
    pr = read_preset(path)
    out = {"kind": "look" if pr["type"] == "Look" else "preset", "name": pr["name"], "path": str(p),
           "set": pr["set"] if pr["type"] != "Look" else {}, "curves": pr["curves"] if pr["type"] != "Look" else {},
           "mono": pr["mono"], "unsupported": pr["unsupported"], "look": None, "warning": "",
           "has_rgbtable": "RGBTable" in pr["tables"], "has_looktable": "LookTable" in pr["tables"],
           "profile": pr["profile"]}
    target = pr
    if pr["type"] == "Look":
        out["look"] = {"path": str(p), "name": pr["name"]}
    elif pr["look_ref"]:
        if pr["look_ref"].get("inline"):
            out["look"] = {"path": str(p), "name": pr["look_ref"].get("name") or pr["name"]}
        else:
            hit = resolve_look(pr, root)
            if hit:
                out["look"] = {"path": hit, "name": pr["look_ref"].get("name") or Path(hit).stem}
                try:
                    target = read_preset(hit)
                except Exception:
                    pass
            else:
                out["warning"] = f"预设引用的外观「{pr['look_ref'].get('name')}」没找到（需要和预设放在同一套文件夹里）"
    out["for_raw"], out["for_jpeg"] = target.get("for_raw", True), target.get("for_jpeg", True)
    if pr["profile"] and pr["profile"] not in ("Adobe Standard", "Adobe Color", ""):
        out["unsupported"] = sorted(set(out["unsupported"]) | {f"相机配置文件 {pr['profile']}"})
    return out


def look_layers(path: str) -> dict:
    """把一个外观（Look 预设，或内嵌外观的普通预设）整理成渲染要用的表和曲线。"""
    pr = read_preset(path)
    if pr["type"] == "Look":
        return {"tables": pr["tables"], "curves": pr["curves"], "mono": pr["mono"]}
    ref = pr.get("look_ref") or {}
    if ref.get("inline"):
        return ref["inline"]
    return {"tables": {}, "curves": {}, "mono": False}


# ───────────────────────── 曲线 ─────────────────────────

def spline_lut(points, n: int = 4096) -> np.ndarray:
    """单调三次样条（Fritsch–Carlson），与界面里画的曲线一致。"""
    pts = sorted((min(1, max(0, float(a))), min(1, max(0, float(b)))) for a, b in points)
    xs, ys = [], []
    for a, b in pts:
        if xs and a - xs[-1] < 1e-4:
            ys[-1] = b
            continue
        xs.append(a)
        ys.append(b)
    X = np.linspace(0, 1, n)
    if len(xs) < 2:
        return X.astype(np.float32)
    xs, ys = np.array(xs), np.array(ys)
    h = np.diff(xs)
    d = np.diff(ys) / h
    m = np.zeros(len(xs))
    m[0], m[-1] = d[0], d[-1]
    for k in range(1, len(xs) - 1):
        m[k] = 0.0 if d[k - 1] * d[k] <= 0 else (d[k - 1] + d[k]) / 2
    for k in range(len(d)):
        if d[k] == 0:
            m[k] = m[k + 1] = 0.0
        else:
            a, b = m[k] / d[k], m[k + 1] / d[k]
            s = a * a + b * b
            if s > 9:
                t = 3 / math.sqrt(s)
                m[k], m[k + 1] = t * a * d[k], t * b * d[k]
    i = np.clip(np.searchsorted(xs, X) - 1, 0, len(xs) - 2)
    t = (X - xs[i]) / h[i]
    t2, t3 = t * t, t * t * t
    Y = ((2 * t3 - 3 * t2 + 1) * ys[i] + (t3 - 2 * t2 + t) * h[i] * m[i] +
         (-2 * t3 + 3 * t2) * ys[i + 1] + (t3 - t2) * h[i] * m[i + 1])
    Y = np.where(X < xs[0], ys[0], np.where(X > xs[-1], ys[-1], Y))
    return np.clip(Y, 0, 1).astype(np.float32)


def tone_lut(P: dict, n: int = 4096) -> np.ndarray:
    """对比度、高光、阴影、白色、黑色 → 显示域 1D 曲线（端点稳定、整体平滑）。"""
    x = np.linspace(0, 1, n)
    y = x.copy()
    hl, sh = P["highlights"] / 100, P["shadows"] / 100
    wh, bl, c = P["whites"] / 100, P["blacks"] / 100, P["contrast"] / 100
    y = y + 0.25 * hl * (y ** 2) * (1 - y) * 6.75 + 0.25 * sh * y * (1 - y) ** 2 * 6.75
    y = y + 0.15 * wh * y ** 3 + 0.15 * bl * (1 - y) ** 3
    y = np.clip(y, 0, 1)
    if abs(c) > 1e-6:
        g = 1 + 0.7 * c if c > 0 else 1 / (1 + 0.7 * -c)
        p = 0.46
        y = np.where(y < p, p * np.power(np.maximum(y, 0) / p, g), 1 - (1 - p) * np.power(np.maximum(1 - y, 0) / (1 - p), g))
    return np.clip(y, 0, 1).astype(np.float32)


def _apply_1d(img, luts):
    out = np.empty_like(img, dtype=np.float32)
    for c in range(3):
        out[..., c] = _lookup(img[..., c], luts[c])
    return out


def _compose(*luts):
    """把若干 1D 曲线（每个都是 0..1 → 0..1，n 点）依次复合成一条。"""
    n = luts[0].shape[0]
    xs = np.linspace(0, 1, n, dtype=np.float32)
    out = xs.copy()
    for l in luts:
        out = np.interp(out, xs, l).astype(np.float32)
    return out


# ───────────────────────── 解码 ─────────────────────────

def _baseline_exposure(path: Path) -> float:
    try:
        with cull.TiffRaw(path) as t:
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
            info["warning"] = "没有安装 rawpy，正在用 RAW 内嵌的预览图编辑（8 位，宽容度有限）。请运行 启动.command 自动安装。"
        except Exception as e:
            info["warning"] = f"RAW 解码失败（{type(e).__name__}: {e}），正在用内嵌预览图编辑，宽容度有限。"
        img = cull.load_preview(p, PREVIEW_SIDE if half else None)
        info["mode"] = "preview"
    else:
        # 预览只需要长边 2880：大 JPEG 直接按 1/2、1/4 缩小解码，快好几倍；导出（half=False）仍用全尺寸
        img = cull.load_preview(p, PREVIEW_SIDE if half else None)
    arr = np.asarray(img.convert("RGB"), dtype=np.float32) / 255.0
    lin = mat(srgb_decode(arr), SRGB_TO_PP)
    return lin, info


def resize_lin(lin: np.ndarray, side: int) -> np.ndarray:
    h, w = lin.shape[:2]
    s = side / max(h, w)
    if s >= 1:
        return lin
    return cv2.resize(np.ascontiguousarray(lin), (max(1, round(w * s)), max(1, round(h * s))), interpolation=cv2.INTER_AREA)


# ───────────────────────── 渲染管线 ─────────────────────────

class Context:
    """一次渲染需要的外部数据（外观、LUT），按参数里的路径加载并缓存。"""

    def __init__(self, info: dict, P: dict):
        self.info = info
        self.look = None
        self.lut = None
        self.notes = []
        if P.get("look"):
            try:
                self.look = look_layers(P["look"]["path"])
            except Exception as e:
                self.notes.append(f"外观读取失败：{e}")
        if P.get("lut"):
            try:
                self.lut = load_cube(P["lut"]["path"])
            except Exception as e:
                self.notes.append(f"LUT 读取失败：{e}")


def wb_gains(P: dict) -> np.ndarray:
    t, m = P["temp"] / 100.0, P["tint"] / 100.0
    g = np.array([2 ** (0.6 * t), 2 ** (-0.45 * m), 2 ** (-0.6 * t)], np.float32)
    return g / float(np.dot(PP_Y, g))


def base_tone(x: np.ndarray) -> np.ndarray:
    """RAW 的默认影调：中间调保持线性，0.55 以上柔和滚降到 1（约 2.5 档高光余量）。
    无分支写法：min(x,t) ＋ (1−t)(1−e^{−max(x−t,0)/(1−t)})，x ≤ t 时第二项为 0，结果与分段式相同。"""
    t = np.float32(0.55)
    over = np.maximum(x - t, np.float32(0))
    over *= np.float32(-1 / (1 - 0.55))
    np.exp(over, out=over)
    np.subtract(np.float32(1), over, out=over)
    over *= np.float32(1 - 0.55)
    over += np.minimum(x, t)
    return over


# 经典徕卡 M 镜头的暗角模拟（未经机身镜头校正的光学原貌）。
# 徕卡数据表只以曲线图给出相对照度，没有公开数值，这里按各镜头的设计特点做近似：
#  · ev：四角比中心暗多少档；弱／中／强 分别对应 约 f/5.6、约 f/2.8、光圈全开 时的暗角
#  · p ：衰减曲线的形状（亮度损失 ∝ 距中心距离^p）；数值越小，暗角从越靠近中心的地方开始（大光圈、广角更明显）
LENSES = {
    "11874": {"name": "徕卡 11874 · Summilux-M 35mm f/1.4 ASPH.（1994 版，非 FLE）",
              "stops": {"weak": "f/5.6", "mid": "f/2.8", "strong": "f/1.4"},
              "ev": {"weak": 0.6, "mid": 1.2, "strong": 2.2}, "p": 1.8},
    "11699": {"name": "徕卡 11699 · APO-Summicron-M 35mm f/2 ASPH.",
              "stops": {"weak": "f/5.6", "mid": "f/2.8", "strong": "f/2"},
              "ev": {"weak": 0.8, "mid": 1.3, "strong": 1.9}, "p": 2.0},
    "11141": {"name": "徕卡 11141 · APO-Summicron-M 50mm f/2 ASPH.",
              "stops": {"weak": "f/5.6", "mid": "f/2.8", "strong": "f/2"},
              "ev": {"weak": 0.5, "mid": 0.9, "strong": 1.4}, "p": 2.4},
    "11672": {"name": "徕卡 11672 · Summicron-M 28mm f/2 ASPH.（2016 第二代）",
              "stops": {"weak": "f/5.6", "mid": "f/2.8", "strong": "f/2"},
              "ev": {"weak": 1.0, "mid": 1.6, "strong": 2.3}, "p": 1.9},
}
VIG_LEVELS = {"weak": "弱", "mid": "中", "strong": "强"}


def lens_list() -> list:
    return [{"id": k, "name": v["name"], "stops": v["stops"], "ev": v["ev"]} for k, v in LENSES.items()]


def vignette_gain(h: int, w: int, ev: float, y_off: int = 0, full_hw=None, power: float = 2.3) -> np.ndarray:
    """经典镜头式暗角：以画面中心为圆心的正圆衰减（不是椭圆），线性光里乘上去，等于镜头本身的光量损失。
    分条导出时用 y_off／full_hw 按整张图的坐标计算，和预览一致。"""
    H, W = full_hw or (h, w)
    ys = np.arange(h, dtype=np.float64) + (y_off + 0.5 - H / 2)       # float64：分条／多线程时结果更稳定
    xs = np.arange(w, dtype=np.float64) + (0.5 - W / 2)
    r2 = (ys[:, None] ** 2 + xs[None, :] ** 2) / (0.25 * (H * H + W * W))     # 四角 ＝ 1
    return np.exp2(-ev * np.power(r2, power / 2)).astype(np.float32)[..., None]


def render(lin: np.ndarray, info: dict, P: dict, ctx: Context | None = None, full_shape=None,
           y_off: int = 0) -> np.ndarray:
    """线性 ProPhoto → 显示用 sRGB（0..1，float32）。预览和导出共用同一条管线：
    逐像素的前段（render_display）→ 清晰度（要用到邻近像素）→ 逐像素的收尾（finish）。
    full_shape：分条导出时传入整张图的尺寸，清晰度的模糊半径、暗角都按整图计算，与预览一致；
    y_off：这一条在整图中的起始行。"""
    ctx = ctx or Context(info, P)
    D = render_display(lin, info, P, ctx, full_shape, y_off)
    return finish(apply_clarity(D, P, full_shape), P, ctx)


def render_display(lin: np.ndarray, info: dict, P: dict, ctx: Context, full_shape=None, y_off: int = 0) -> np.ndarray:
    """管线前段：白平衡、曝光、镜头暗角、外观、影调曲线、sRGB 编码、外观 RGBTable。全是逐像素运算。"""
    lin = as_planar(lin, None if lin.dtype == np.float32 else 1 / 65535.0)
    scene = info["mode"] == "raw"
    x = lin * (wb_gains(P) * (2.0 ** (P["exposure"] + (info["base_ev"] if scene else 0.0))))
    vg = P.get("vignette")
    if vg:
        prof = LENSES[vg["lens"]]
        x = x * vignette_gain(x.shape[0], x.shape[1], prof["ev"][vg["level"]], y_off, full_shape, prof["p"])
    look = ctx.look or {}
    tables = look.get("tables", {})
    la = (P.get("look") or {}).get("amount", 1.0)
    if "LookTable" in tables:
        x = apply_huesat(x, tables["LookTable"], la)

    # 影调滑块 → 外观曲线（1D 曲线，先准备好）
    luts = None if all(abs(P[k]) < 0.5 for k in ("contrast", "highlights", "shadows", "whites", "blacks")) else [tone_lut(P)] * 3
    if look.get("curves"):
        lc = look["curves"]
        ident = np.linspace(0, 1, 4096, dtype=np.float32)
        m = spline_lut(lc["rgb"]) if "rgb" in lc else ident
        chans = []
        for ch in ("r", "g", "b"):
            c = _compose(m, spline_lut(lc[ch])) if ch in lc else m
            chans.append(ident + (c - ident) * min(la, 1.0))
        luts = [_compose(luts[i] if luts else ident, chans[i]) for i in range(3)]

    # 场景 → 显示（sRGB 编码）；没有 Log LUT 时，sRGB 编码和上面的 1D 曲线合成一张表，只遍历一次
    lin_disp = mat(base_tone(np.maximum(x, 0)) if scene else np.maximum(x, 0), PP_TO_SRGB)
    lut = ctx.lut
    lp = P.get("lut") or {}
    if lut is not None and lp.get("space", "srgb") != "srgb":
        std = srgb_encode(lin_disp)
        enc = log_encode(np.maximum(x, 0) if scene else x, lp["space"])
        L = np.clip(apply_cube(enc, lut), 0, 1)
        D = std + (L - std) * lp.get("amount", 1.0)
        if luts:
            D = _apply_1d(D, luts)
    elif luts:
        D = _apply_1d(lin_disp, [_chain(_ENC_Y, l) for l in luts])
    else:
        D = srgb_encode(lin_disp)
    if "RGBTable" in tables:
        D = apply_rgbtable(D, tables["RGBTable"], la)
    return as_planar(D)


def apply_clarity(D: np.ndarray, P: dict, full_shape=None) -> np.ndarray:
    """清晰度（局部对比）：模糊半径按整图尺寸计算。OpenCV 的模糊本身是多线程的，整块做一次最快。"""
    if abs(P["clarity"]) > 0.5 and cv2 is not None:
        Y = D @ REC709_Y
        sigma = 0.008 * max(full_shape or D.shape[:2])
        det = Y - cv2.GaussianBlur(Y, (0, 0), sigma)
        D = D + ((P["clarity"] / 100) * 0.8 * det * np.clip(4 * Y * (1 - Y), 0, 1))[..., None]
    return D


# ───────────────────────── 自动调整：五种测光方案 ─────────────────────────
#
# 都是按各家相机的测光思路和成片观感做的经验设定，不是机内算法的复刻。
# 测光直接在编辑器的真实渲染结果上做（含 RAW 起始提亮、高光肩部、当前色温色调和镜头暗角），
# 所以 RAW 和 JPEG 都能得到一致的判断。
#  · weight："zones" 全局（6×4 分区，去掉最亮、最暗的 15% 分区再平均，近似评价／多区测光）；
#            "center" 中央重点（高斯权重，画面边缘＝1，sigma 越大中央区域越宽）
#  · target：测光目标亮度（显示用线性值，18% 灰＝0.18）；comp：曝光补偿（档）
#  · damping／max：偏离越大纠正得越少，保留原始氛围；提亮（up）和压暗（dn）分开设
#  · clip_limit：允许的高光溢出比例；clip_back：为收高光最多往回收几档
METER_STYLES = {
    "global": {
        "name": "全局评价", "desc": "整幅画面分区评价，目标 18% 灰；影调中性：黑位、白位适中，对比不加不减",
        "weight": "zones", "target": 0.18, "comp": 0.0,
        "damping_up": 0.8, "max_up": 2.5, "damping_dn": 0.9, "max_dn": 2.5, "clip_limit": 0.01, "clip_back": 1.5,
        "tone": {"black": 0.020, "white": 0.965, "base_c": 0, "spread": 0.52, "c": (-20, 25), "b": (-40, 40), "w": (-40, 40), "strength": 0.75}},
    "leica_cw": {
        "name": "徕卡经典中央重点", "desc": "M 机身式中央重点测光，目标比 18% 灰低约 1/4 档；影调深沉：黑位压得深、对比偏强，暗景只补一部分",
        "weight": "center", "sigma": 0.5, "target": 0.15, "comp": 0.0,
        "damping_up": 0.6, "max_up": 1.6, "damping_dn": 0.85, "max_dn": 2.2, "clip_limit": 0.01, "clip_back": 1.5,
        "tone": {"black": 0.010, "white": 0.955, "base_c": 12, "spread": 0.55, "c": (0, 40), "b": (-55, 25), "w": (-40, 30), "strength": 0.85}},
    "leica_global": {
        "name": "徕卡全局测光 +0.3EV", "desc": "徕卡多区（全局）测光，再加 +0.3 档补偿；影调同徕卡，但更通透",
        "weight": "zones", "target": 0.15, "comp": 0.3,
        "damping_up": 0.6, "max_up": 1.6, "damping_dn": 0.85, "max_dn": 2.2, "clip_limit": 0.01, "clip_back": 1.5,
        "tone": {"black": 0.012, "white": 0.96, "base_c": 8, "spread": 0.55, "c": (0, 35), "b": (-50, 25), "w": (-40, 35), "strength": 0.85}},
    "fuji_cw": {
        "name": "富士中央重点", "desc": "中央区域比徕卡更宽，目标 18% 灰；影调柔和：黑位留一点、过渡平缓、中间调明亮，高光保护更严",
        "weight": "center", "sigma": 0.65, "target": 0.18, "comp": 0.0,
        "damping_up": 0.75, "max_up": 2.0, "damping_dn": 0.85, "max_dn": 2.2, "clip_limit": 0.005, "clip_back": 1.0,
        "tone": {"black": 0.022, "white": 0.97, "base_c": -5, "spread": 0.50, "c": (-20, 20), "b": (-35, 35), "w": (-35, 40), "strength": 0.75}},
}
# HDR 动态测光要配合 HDR 显示模式使用（计划中），在那之前不出现在菜单里
ENABLE_HDR = False
HDR_STYLES = {
    "hdr": {
        "name": "HDR 动态测光", "desc": "先按高光定曝光（几乎不溢出），再用「阴影」提亮暗部、「高光」压住亮部，适合大光比场景",
        "weight": "zones", "target": 0.16, "comp": 0.0,
        "damping_up": 0.7, "max_up": 2.0, "damping_dn": 0.9, "max_dn": 2.5, "clip_limit": 0.002, "clip_back": 3.0,
        "hdr": True},
}
if ENABLE_HDR:
    METER_STYLES.update(HDR_STYLES)
DEFAULT_METER = "leica_cw"


def meter_list() -> list:
    return [{"id": k, "name": v["name"], "desc": v["desc"]} for k, v in METER_STYLES.items()]


def _tone_eval(vals: np.ndarray, c: float, b: float, w: float) -> np.ndarray:
    t = tone_lut({"contrast": c, "highlights": 0, "shadows": 0, "whites": w, "blacks": b})
    return t[np.clip((vals * 4095 + 0.5).astype(np.int32), 0, 4095)]


def _solve(fn, target: float, lo: float, hi: float, iters: int = 14) -> float:
    """fn 单调递增：在 [lo, hi] 里找 fn(x) ≈ target。"""
    if fn(lo) >= target:
        return lo
    if fn(hi) <= target:
        return hi
    for _ in range(iters):
        mid = (lo + hi) / 2
        if fn(mid) < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def auto_tone(Yenc: np.ndarray, tone: dict) -> tuple[dict, dict]:
    """按风格设定整体影调，只改「对比度／黑色／白色」三个滑块。Yenc：曝光定好后画面的亮度（sRGB 编码值 0..1）。
    · 对比度 ＝ 风格的基础对比（徕卡偏强、富士偏柔）＋ 按画面主体影调的跨度微调：平淡的加一点，已经很硬的减一点。
      跨度只看去掉纯黑、纯白之后的“有内容”的部分，大面积黑底的低调照片不会被误判成“对比太强”。
    · 黑色／白色：灰蒙的暗部压到风格的黑位、发闷的亮部推到风格的白位（只压不抬、只推不压）；
      低调照片不硬拉白，高调照片不硬压黑。"""
    q = np.percentile(Yenc, [0.5, 5, 50, 95, 99.5]).astype(np.float32)
    lo_, hi_ = float(q[0]), float(q[4])
    content = Yenc[(Yenc > 0.05) & (Yenc < 0.97)]
    if content.size > 0.15 * Yenc.size:
        c10, c90 = (float(v) for v in np.percentile(content, [10, 90]))
        adapt = max(-15.0, min(15.0, 40.0 * (tone["spread"] - (c90 - c10))))
    else:
        c10 = c90 = float("nan")
        adapt = 0.0
    c = max(tone["c"][0], min(tone["c"][1], tone["base_c"] + adapt))
    k = tone["strength"]
    w_hi = tone["w"][1] if hi_ > 0.6 else min(tone["w"][1], 10)
    b_lo = tone["b"][0] if lo_ < 0.3 else max(tone["b"][0], -15)
    # 黑色只往深压（已经是纯黑的不抬成灰黑），白色只往亮推（已经到顶的纯白不压成灰白）
    b_hi = 0.0
    w_lo = 0.0
    b = w = 0.0
    for _ in range(2):
        b = _solve(lambda x: float(_tone_eval(np.array([lo_], np.float32), c, x, w)[0]), tone["black"], -100, 100)
        b = max(b_lo, min(b_hi, b * k))
        w = _solve(lambda x: float(_tone_eval(np.array([hi_], np.float32), c, b, x)[0]), tone["white"], -100, 100)
        w = max(w_lo, min(w_hi, w * k))
    out = {"contrast": int(round(c)), "blacks": int(round(b)), "whites": int(round(w))}
    after = _tone_eval(q, out["contrast"], out["blacks"], out["whites"])
    stats = {"before": [round(float(v), 3) for v in q], "after": [round(float(v), 3) for v in after],
             "content_spread": None if c10 != c10 else round(c90 - c10, 3)}
    return out, stats


def damp_ev(ev: float, st: dict) -> float:
    """把测光算出的“要补多少档”收一收：偏离越大，保留的原始氛围越多。"""
    k, m = (st["damping_up"], st["max_up"]) if ev > 0 else (st["damping_dn"], st["max_dn"])
    return m * math.tanh(k * ev / m)


def _bisect(fn, lo: float, hi: float, iters: int = 12) -> float:
    """fn 随 ev 单调递增；返回最大的 ev 使 fn(ev) <= 0（fn 已减去目标）。"""
    if fn(lo) > 0:
        return lo
    if fn(hi) <= 0:
        return hi
    for _ in range(iters):
        mid = (lo + hi) / 2
        if fn(mid) <= 0:
            lo = mid
        else:
            hi = mid
    return lo


def _meter_fn(st: dict, h: int, w: int):
    """返回 f(Y) → 测光值（对数亮度）。"""
    if st["weight"] == "center":
        u = (np.arange(w, dtype=np.float32) + 0.5) / w * 2 - 1
        v = (np.arange(h, dtype=np.float32) + 0.5) / h * 2 - 1
        wgt = np.exp(-(v[:, None] ** 2 + u[None, :] ** 2) / (2 * st["sigma"] ** 2)).astype(np.float32)
        tot = float(wgt.sum())
        return lambda Y: float((wgt * np.log(Y)).sum() / tot)
    ys = np.linspace(0, h, 5).astype(int)
    xs = np.linspace(0, w, 7).astype(int)

    def zones(Y):
        L = np.log(Y)
        z = np.sort([float(L[ys[i]:ys[i + 1], xs[j]:xs[j + 1]].mean()) for i in range(4) for j in range(6)])
        k = round(len(z) * 0.15)
        return float(z[k:len(z) - k].mean())
    return zones


def auto_adjust(lin: np.ndarray, info: dict, P: dict, style: str = DEFAULT_METER) -> dict:
    """按所选测光方案计算曝光（HDR 方案另外给出阴影／高光）。返回 {"set": {...}, "note", "style", ...}。"""
    st = METER_STYLES.get(style) or METER_STYLES[DEFAULT_METER]
    small = resize_lin(lin, 512)
    h, w = small.shape[:2]
    meter = _meter_fn(st, h, w)
    base = normalize_params({"temp": P.get("temp", 0), "tint": P.get("tint", 0), "vignette": P.get("vignette")})

    def shot(ev, extra=None):
        Q = dict(base, exposure=float(ev), **(extra or {}))
        return render(small, info, Q, Context(info, Q))

    def luma(img):
        return np.maximum(srgb_decode(img) @ REC709_Y, 1e-4)

    def clipped(ev, extra=None):
        return float((shot(ev, extra).max(axis=-1) >= 0.99).mean())

    ev_meter = _bisect(lambda e: meter(luma(shot(e))) - math.log(st["target"]), -5.0, 5.0)
    ev_d = damp_ev(ev_meter, st) + st["comp"]
    ev_hi = _bisect(lambda e: clipped(e) - st["clip_limit"], -5.0, 5.0)
    protected = ev_hi < ev_d
    ev = max(min(ev_d, ev_hi), ev_d - st["clip_back"]) if protected else ev_d
    out = {"exposure": round(max(-5.0, min(5.0, ev)), 2)}
    note = f"曝光 {out['exposure']:+.2f}" + ("（已收高光）" if protected else "")
    tone_stats = None
    if st.get("tone") and not st.get("hdr"):
        Yenc = srgb_encode(np.clip(srgb_decode(shot(out["exposure"])) @ REC709_Y, 0, 1))
        tone, tone_stats = auto_tone(Yenc, st["tone"])
        out.update(tone)
        note += f" · 对比 {tone['contrast']:+d} · 黑色 {tone['blacks']:+d} · 白色 {tone['whites']:+d}"

    if st.get("hdr"):
        # 曝光已按高光定好；看暗部有多暗、整体光比多大，决定阴影提亮和高光压缩的力度
        Y = luma(shot(out["exposure"]))
        p05, p995 = float(np.percentile(Y, 5)), float(np.percentile(Y, 99.5))
        dr = math.log2(max(p995, 1e-4) / max(p05, 1e-4))
        shadows = int(round(min(70.0, max(0.0, 30 * math.log2(0.05 / p05))))) if p05 < 0.05 else 0
        highlights = -int(round(min(60.0, max(0.0, 12 * (dr - 5))))) if dr > 5 else 0
        extra = {"shadows": shadows, "highlights": highlights}
        # 阴影提亮后整体会变亮：再测一次，太亮就把曝光往回收一点（只收不加，保持高光安全）
        m2 = math.exp(meter(luma(shot(out["exposure"], extra))))
        if m2 > st["target"] * 1.3:
            out["exposure"] = round(max(-5.0, out["exposure"] - 0.5 * math.log2(m2 / (st["target"] * 1.3))), 2)
        out.update(extra)
        note = f"曝光 {out['exposure']:+.2f} · 阴影 {shadows:+d} · 高光 {highlights:+d}（光比约 {dr:.1f} 档）"
    if st["comp"]:
        note += f" · 含补偿 {st['comp']:+.1f}"
    return {"set": out, "style": st["name"], "style_id": style if style in METER_STYLES else DEFAULT_METER,
            "note": note, "meter_ev": round(ev_meter, 2), "highlight_limited": bool(protected), "tone": tone_stats}


# ───────────────────────── 多线程渲染 ─────────────────────────
#
# 渲染管线除「清晰度」外都是逐像素运算：前段、收尾各自切成几条并行算，中间的清晰度对整块做一次
# （OpenCV 自己会多线程），结果与单线程渲染一致。numpy 的大块运算会释放 GIL，所以线程就能用满多核。
_POOL = None
_POOL_LOCK = threading.Lock()
WORKERS = max(1, min(8, (os.cpu_count() or 2)))


def _pool():
    global _POOL
    with _POOL_LOCK:
        if _POOL is None:
            from concurrent.futures import ThreadPoolExecutor
            _POOL = ThreadPoolExecutor(WORKERS, thread_name_prefix="render")
        return _POOL


def clarity_margin(P: dict, full_hw) -> int:
    # OpenCV 对浮点图的高斯核半径约 4σ：边距留足 4σ，分条结果才与整图逐像素一致
    return int(math.ceil(4 * 0.008 * max(full_hw))) + 2 if abs(P["clarity"]) > 0.5 else 0


def render_parallel(lin: np.ndarray, info: dict, P: dict, ctx: "Context", full_shape=None, y_off: int = 0,
                    parts: int | None = None) -> np.ndarray:
    """与 render() 结果相同，按行切成几条并行渲染。lin 可以是整图，也可以是整图中从 y_off 开始的一段。"""
    H = lin.shape[0]
    full = full_shape or lin.shape[:2]
    parts = parts or WORKERS
    if parts <= 1 or H < 64 * parts or lin.shape[0] * lin.shape[1] < 400_000:
        return render(lin, info, P, ctx, full_shape=full, y_off=y_off)
    cuts = np.linspace(0, H, parts + 1).astype(int)
    pool = _pool()
    W = lin.shape[1]
    D = planar_empty(H, W)                 # 各条直接写进同一块平面布局的缓冲区（np.concatenate 会变回交错布局）

    def front(k):
        D[cuts[k]:cuts[k + 1]] = render_display(lin[cuts[k]:cuts[k + 1]], info, P, ctx, full, y_off + cuts[k])
    list(pool.map(front, range(parts)))
    D = as_planar(apply_clarity(D, P, full))
    out = planar_empty(H, W)

    def back(k):
        out[cuts[k]:cuts[k + 1]] = finish(D[cuts[k]:cuts[k + 1]], P, ctx)
    list(pool.map(back, range(parts)))
    return out


# ───────────────────────── 编辑会话（界面用） ─────────────────────────

class Session:
    def __init__(self):
        self.lock = threading.Lock()
        self.render_lock = threading.Lock()
        self.path = None
        self.info = None
        self.base = None
        self.exif = {}
        self.scaled = {}                # 按档位缓存缩小后的预览，换照片时清空
        self.last = None                # 上一次渲染的 (键, JPEG)：同样的参数（如松开对比原图、窗口微调）直接返回
        self.latest = {}                # 每个浏览器页面各自的最新请求编号
        self.export = {"running": False}

    def open(self, path: str) -> dict:
        p = Path(path).expanduser()
        if not p.is_file() or p.suffix.lower() not in EDIT_EXT:
            raise ValueError("不支持的文件")
        t0 = time.time()
        lin, info = decode(str(p), half=True)
        base = as_planar(resize_lin(lin, PREVIEW_SIDE))
        try:
            exif = cull.read_exif(p)
        except Exception:
            exif = {}
        with self.lock:
            self.path, self.info, self.base, self.exif, self.scaled, self.last = str(p), info, base, exif, {}, None
        info = dict(info)
        info["width"], info["height"] = base.shape[1], base.shape[0]
        info["decode_ms"] = int((time.time() - t0) * 1000)
        info["params"] = load_edit(str(p))
        info["exif"] = _exif_text(p)
        return info

    def _level(self, side: int) -> int:
        """界面需要的长边像素 → 最接近且不小于它的一档（上限 PREVIEW_SIDE）；没给就用 1800。"""
        if not side or side <= 0:
            return 1800
        return next((v for v in PREVIEW_LEVELS if v >= side), PREVIEW_LEVELS[-1])

    def _pick(self, level: int, fast: bool) -> np.ndarray:
        """取某一档的预览图（带缓存）；调用时已持有 self.lock。"""
        long_side = max(400, int(level * FAST_RATIO) // 100 * 100) if fast else level
        if long_side >= max(self.base.shape[:2]):
            return self.base
        if long_side not in self.scaled:
            if len(self.scaled) >= 6:
                self.scaled.pop(next(iter(self.scaled)))
            self.scaled[long_side] = as_planar(resize_lin(self.base, long_side))
        return self.scaled[long_side]

    def render_jpeg(self, P: dict, quality: str, seq: int, client: str = "", side: int = 0) -> tuple[bytes | None, dict]:
        with self.lock:
            self.latest[client] = max(self.latest.get(client, 0), seq)
            if len(self.latest) > 64:
                self.latest = {client: self.latest[client]}
        with self.render_lock:
            if seq < self.latest.get(client, 0):       # 同一页面有更新的请求在排队，跳过这次
                return None, {}
            with self.lock:
                if self.base is None:
                    raise ValueError("还没有打开照片")
                lin = self._pick(self._level(side), quality == "fast")
                info = self.info
            t0 = time.time()
            P = normalize_params(P)
            key = (self.path, lin.shape, json.dumps(P, sort_keys=True))
            if self.last and self.last[0] == key:
                return self.last[1], {"ms": 0, "notes": self.last[2]}
            ctx = Context(info, P)
            out = render_parallel(lin, info, P, ctx)
            out *= np.float32(255)
            out += np.float32(0.5)
            img = Image.fromarray(out.astype(np.uint8))
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=82 if quality == "fast" else 92)
            data = buf.getvalue()
            self.last = (key, data, ctx.notes)
            return data, {"ms": int((time.time() - t0) * 1000), "notes": ctx.notes}

    def start_export(self, path: str, P: dict, out_dir: str | None, fmt: str, quality: int, long_edge: int):
        if self.export.get("running"):
            raise ValueError("已有导出在进行")
        self.export = {"running": True, "msg": "准备…", "pct": 0.0, "file": None, "error": None, "name": Path(path).name}

        def prog(msg, pct):
            self.export.update(msg=msg, pct=round(pct, 3))

        def run():
            try:
                f = export(path, P, out_dir, fmt, quality, long_edge, prog)
                self.export.update(file=f, msg="完成", pct=1.0)
            except Exception as e:
                self.export.update(error=f"{type(e).__name__}: {e}")
            finally:
                self.export["running"] = False
        threading.Thread(target=run, daemon=True).start()
        return self.export

    def auto(self, P: dict, style: str = DEFAULT_METER) -> dict:
        with self.lock:
            if self.base is None:
                raise ValueError("还没有打开照片")
            base, info = self.base, self.info
        return auto_adjust(base, info, normalize_params(P), style)


SESSION = Session()


# ───────────────────────── 编辑记录 ─────────────────────────

def edit_path(photo: str) -> Path:
    p = Path(photo)
    return p.parent / "photo-cull-report" / "edits" / (p.name + ".json")


def load_edit(photo: str) -> dict:
    try:
        return normalize_params(json.loads(edit_path(photo).read_text(encoding="utf-8")))
    except Exception:
        return normalize_params(None)


def save_edit(photo: str, P: dict) -> str:
    f = edit_path(photo)
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(normalize_params(P), ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(f)
    return str(f)


def has_edit(photo: str) -> bool:
    return edit_path(photo).is_file()


# ───────────────────────── 文件列表与素材库 ─────────────────────────

def list_folder(folder: str) -> list[dict]:
    d = Path(folder).expanduser()
    if not d.is_dir():
        raise ValueError("找不到这个文件夹")
    groups = cull.collect(d, False)
    items = []
    for g in groups:
        primary = g[0]
        if primary.suffix.lower() not in EDIT_EXT:
            continue
        items.append({"path": str(primary), "name": primary.name,
                      "pair": [m.suffix.upper().lstrip(".") for m in g] if len(g) > 1 else [],
                      "raw": primary.suffix.lower() in RAW_EXT, "edited": has_edit(str(primary))})
    return items


def default_library() -> str:
    if LUT_DIR.is_dir():
        return "builtin"
    for c in (Path.home() / "Desktop" / "预设与LUT", Path.home() / "Desktop"):
        if c.is_dir():
            return str(c)
    return str(Path.home())


def scan_library(root: str, limit: int = 8000) -> dict:
    """root ＝ "builtin"（内置 LUT）或一个文件夹。"""
    builtin = root in ("builtin", "", "（内置）") or Path(root).expanduser().resolve() == LUT_DIR
    r = LUT_DIR if builtin else Path(root).expanduser()
    if not r.is_dir():
        raise ValueError("找不到素材库文件夹")
    scope = [] if builtin else [s for s in LIBRARY_SCOPE if (r / s).is_dir()]
    starts = [r / s for s in scope] if scope else [r]
    items = []
    walk = (w for st in starts for w in os.walk(st))
    for dirpath, dirnames, filenames in walk:
        dirnames[:] = sorted(d for d in dirnames if not d.startswith(".") and d != "__MACOSX")
        for fn in sorted(filenames):
            low = fn.lower()
            if fn.startswith(".") or not (low.endswith(".cube") or low.endswith(".xmp")):
                continue
            full = Path(dirpath) / fn
            rel = full.relative_to(r)
            item = {"path": style_ref(str(full)) if builtin else str(full), "name": full.stem.replace(".cube", ""),
                    "group": rel.parent.as_posix(), "kind": "cube" if low.endswith(".cube") else "xmp"}
            if item["kind"] == "cube":
                sp, warn = guess_space(str(full))
                item["space"] = sp
                item["warn"] = bool(warn)
            items.append(item)
            if len(items) >= limit:
                return {"root": "builtin" if builtin else str(r), "items": items, "truncated": True, "scope": scope, "builtin": builtin}
    if builtin:
        items.extend(user_lut_items())
    return {"root": "builtin" if builtin else str(r), "items": items, "truncated": False, "scope": scope, "builtin": builtin}


# ───── 用户添加的 LUT
def user_lut_items() -> list:
    if not USER_LUT_DIR.is_dir():
        return []
    out = []
    for f in sorted(USER_LUT_DIR.rglob("*.cube"), key=lambda x: x.name.lower()):
        if f.name.startswith("."):
            continue
        sp, warn = guess_space(str(f))
        out.append({"path": style_ref(str(f)), "name": f.stem, "group": USER_GROUP, "kind": "cube",
                    "space": sp, "warn": bool(warn), "user": True})
    return out


def _safe_lut_name(name: str) -> str:
    stem = Path(str(name).replace("\\", "/")).name
    if stem.lower().endswith(".cube"):
        stem = stem[:-5]
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", stem).strip(" .")[:120]
    return stem or "LUT"


def add_user_lut(name: str, text: str) -> dict:
    """检查一个 .cube 的内容，没问题就存进 USER_LUT_DIR。重名时加 (2)、(3)…，不覆盖已有文件。"""
    if not str(name).lower().endswith(".cube"):
        raise ValueError("只支持 .cube 文件")
    data = str(text).encode("utf-8")
    if len(data) > USER_LUT_MAX:
        raise ValueError("文件太大（超过 64 MB）")
    USER_LUT_DIR.mkdir(parents=True, exist_ok=True)
    stem = _safe_lut_name(name)
    tmp = USER_LUT_DIR / f".incoming-{os.getpid()}-{threading.get_ident()}.cube"
    tmp.write_bytes(data)
    try:
        c = load_cube(str(tmp))                      # 格式不对会在这里报错
        dest, n = USER_LUT_DIR / f"{stem}.cube", 2
        while dest.exists():
            dest, n = USER_LUT_DIR / f"{stem} ({n}).cube", n + 1
        os.replace(tmp, dest)
    finally:
        if tmp.exists():
            tmp.unlink()
    sp, warn = guess_space(str(dest))
    return {"path": style_ref(str(dest)), "name": dest.stem, "size": c["size"], "lut_kind": c["kind"],
            "space": sp, "warning": warn}


def remove_user_lut(ref: str) -> str:
    """只能移除「我的 LUT」里的文件（内置和外部素材库的文件不动）。"""
    if not str(ref).startswith(USER):
        raise ValueError("只能移除自己添加的 LUT")
    p = (USER_LUT_DIR / ref[len(USER):]).resolve()
    if USER_LUT_DIR.resolve() not in p.parents or p.suffix.lower() != ".cube" or not p.is_file():
        raise ValueError("找不到这个 LUT")
    p.unlink()
    return p.stem


# ───────────────────────── 缩略图 ─────────────────────────

THUMB_DIR = Path.home() / ".photo-cull" / "thumbs"


def thumbnail(path: str, side: int = 360) -> bytes:
    p = Path(path)
    st = p.stat()
    key = hashlib.sha1(f"{p}|{st.st_mtime}|{st.st_size}|{side}".encode()).hexdigest()
    cached = THUMB_DIR / (key + ".jpg")
    if cached.is_file():
        return cached.read_bytes()
    img = cull.load_preview(p, side * 2)
    img.thumbnail((side, side), Image.LANCZOS)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=82)
    data = buf.getvalue()
    try:
        THUMB_DIR.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(data)
    except OSError:
        pass
    return data


def _exif_text(p: Path) -> str:
    try:
        e = cull.read_exif(p)
        return " · ".join(x for x in (e.get("model", ""), e.get("lens", ""), cull.exposure_text(e)) if x)
    except Exception:
        return ""


# ───────────────────────── 导出 ─────────────────────────

def _exif_for(path: Path):
    exif = Image.Exif()
    try:
        e = cull.read_exif(path)
    except Exception:
        return exif
    from PIL.TiffImagePlugin import IFDRational
    if e.get("model"):
        exif[0x0110] = e["model"]
    exif[0x0131] = f"photo-cull {cull.VERSION}"
    ifd = exif.get_ifd(0x8769)
    if e.get("dt"):
        exif[0x0132] = e["dt"]
        ifd[0x9003] = e["dt"]
    try:
        if e.get("shutter"):
            s = e["shutter"]
            ifd[0x829A] = IFDRational(1, int(s.split("/")[1])) if "/" in s else IFDRational(float(s))
        if e.get("fnum"):
            ifd[0x829D] = IFDRational(float(cull._ratio(e["fnum"])))
        if e.get("iso"):
            ifd[0x8827] = int(float(e["iso"].split()[0]))
        if e.get("focal"):
            ifd[0x920A] = IFDRational(float(cull._ratio(e["focal"])))
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
        progress("解码 RAW…", 0.05)
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
            progress(f"渲染 {k + 1}/{len(rows)}", 0.1 + 0.85 * (k + 1) / len(rows))
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
            raise RuntimeError("16 位 TIFF 写入失败")
    else:
        img = Image.fromarray(out)
        kw = {"quality": int(quality), "subsampling": 0 if quality >= 90 else 2, "exif": _exif_for(src)}
        icc = _srgb_icc()
        if icc:
            kw["icc_profile"] = icc
        img.save(dest, "JPEG", **kw)
    if progress:
        progress("完成", 1.0)
    return str(dest)


def finish(D, P, ctx):
    """清晰度之后的步骤：饱和度 → 用户曲线 → 普通 LUT → 黑白。与 render 的尾段一致。"""
    if abs(P["saturation"]) > 0.5 or abs(P["vibrance"]) > 0.5:
        Y = (D @ REC709_Y)[..., None]
        C = D - Y
        sp = (D.max(axis=-1, keepdims=True) - D.min(axis=-1, keepdims=True))
        f = (1 + P["saturation"] / 100) * (1 + (P["vibrance"] / 100) * (1 - np.clip(sp * 1.5, 0, 1)))
        D = Y + C * f
    cv = P["curve"]
    if any(not _is_identity(cv[ch]) for ch in ("rgb", "r", "g", "b")):
        m = spline_lut(cv["rgb"])
        D = _apply_1d(D, [_compose(m, spline_lut(cv[ch])) for ch in ("r", "g", "b")])
    lut, lp = ctx.lut, P.get("lut") or {}
    if lut is not None and lp.get("space", "srgb") == "srgb":
        L = as_planar(np.clip(apply_cube(np.clip(D, 0, 1), lut), 0, 1))
        D = D + (L - D) * lp.get("amount", 1.0)
    look = ctx.look or {}
    if P.get("mono") or look.get("mono"):
        Y = srgb_decode(D) @ REC709_Y
        D = np.repeat(srgb_encode(Y)[..., None], 3, axis=-1)
    return np.clip(D, 0, 1).astype(np.float32)
