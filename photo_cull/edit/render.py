from __future__ import annotations

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None

import math
import os
import threading

import numpy as np

from ..i18n import t
from .color import (
    _ENC_Y,
    PP_TO_SRGB,
    PP_Y,
    REC709_Y,
    _chain,
    as_planar,
    mat,
    planar_empty,
    srgb_decode,
    srgb_encode,
)
from .curves import _apply_1d, _compose, spline_lut, tone_lut
from .logspace import log_encode
from .lut3d import apply_cube, load_cube
from .params import LENSES, VIG_LEVEL_IDS
from .presets import _is_identity, apply_huesat, apply_rgbtable, look_layers

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
                self.notes.append(t("edit.warn.look_read", err=e))
        if P.get("lut"):
            try:
                self.lut = load_cube(P["lut"]["path"])
            except Exception as e:
                self.notes.append(t("edit.warn.lut_read", err=e))


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


def vig_levels() -> dict:
    return {k: t("edit.vig." + k) for k in VIG_LEVEL_IDS}


def lens_list() -> list:
    return [{"id": k, "name": t("edit.lens." + k), "stops": v["stops"], "ev": v["ev"]} for k, v in LENSES.items()]


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
