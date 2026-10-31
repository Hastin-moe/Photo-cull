from __future__ import annotations

import os
import threading

import cv2
import numpy as np
from PIL import Image

from ..imaging.preview import _fit
from .model import Photo

WORK_SIDE = 1600   # 技术分析用的长边像素
FOCUS_SIDE = 2400  # 对焦检测用的长边像素（统一尺度，避免高像素机身在 1:1 下普遍“显软”）
SIGS: dict = {}    # 画面签名（用于同场景分组），不写入报告


# ───────────────────────── 技术分析 ─────────────────────────

_cascades = threading.local()

def _cascade(name: str):
    """OpenCV 4.x 自带 Haar 模型；不可用时返回 None（跳过人脸检测）。

    CascadeClassifier 不是线程安全的：多个线程同时用同一个对象做 detectMultiScale，
    会在 OpenCV 内部（HaarEvaluator 的积分图缓冲区）互相踩内存，整个程序直接段错误闪退
    （1.7-beta 约 2000 张、并行数 10 的测试中出现过）。所以每个线程各自加载一份。"""
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
    smile_model = _cascade("haarcascade_smile.xml")
    if face_model is None:
        return focus
    faces = face_model.detectMultiScale(
        cv2.equalizeHist(det), scaleFactor=1.1, minNeighbors=6, minSize=(m, m))
    p.faces = len(faces)
    face_sharp = []
    area = float(gray.shape[0] * gray.shape[1]) or 1.0
    for (x, y, w, h) in faces:
        X, Y, W, H = (int(v / scale) for v in (x, y, w, h))
        roi = gray[Y:Y + H, X:X + W]
        if roi.size == 0:
            continue
        p.face_area = max(p.face_area, round(W * H / area, 4))
        face_sharp.append(lap_var(roi))
        upper = roi[: H * 6 // 10]
        if W >= 90 and eye_model is not None:   # 脸太小时眼睛检测不可靠，不判断
            eyes = eye_model.detectMultiScale(
                upper, scaleFactor=1.1, minNeighbors=5, minSize=(max(8, W // 10), max(8, W // 10)))
            if len(eyes) == 0:
                p.eyes_missing += 1
        if W >= 90 and smile_model is not None:  # 笑容：脸的下半部分；minNeighbors 取大一些，宁可漏也不乱报
            lower = roi[H // 2:]
            sm = smile_model.detectMultiScale(lower, scaleFactor=1.7, minNeighbors=22, minSize=(max(12, W // 4), max(8, H // 8)))
            if len(sm):
                p.smiles += 1
    if face_sharp:
        p.sharp_face = float(max(face_sharp))
    return focus
