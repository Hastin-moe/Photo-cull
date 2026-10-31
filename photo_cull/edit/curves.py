from __future__ import annotations

import math

import numpy as np

from .color import _lookup

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
