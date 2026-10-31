from __future__ import annotations

import numpy as np

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
