from __future__ import annotations

import math

import numpy as np

from ..i18n import t
from .color import REC709_Y, srgb_decode, srgb_encode
from .curves import tone_lut
from .decode import resize_lin
from .params import normalize_params
from .render import Context, render

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
METER_STYLES = {      # 各方案的显示名和说明在语言包 edit.meter.<id>.name／desc
    "global": {
        "weight": "zones", "target": 0.18, "comp": 0.0,
        "damping_up": 0.8, "max_up": 2.5, "damping_dn": 0.9, "max_dn": 2.5, "clip_limit": 0.01, "clip_back": 1.5,
        "tone": {"black": 0.020, "white": 0.965, "base_c": 0, "spread": 0.52, "c": (-20, 25), "b": (-40, 40), "w": (-40, 40), "strength": 0.75}},
    "leica_cw": {
        "weight": "center", "sigma": 0.5, "target": 0.15, "comp": 0.0,
        "damping_up": 0.6, "max_up": 1.6, "damping_dn": 0.85, "max_dn": 2.2, "clip_limit": 0.01, "clip_back": 1.5,
        "tone": {"black": 0.010, "white": 0.955, "base_c": 12, "spread": 0.55, "c": (0, 40), "b": (-55, 25), "w": (-40, 30), "strength": 0.85}},
    "leica_global": {
        "weight": "zones", "target": 0.15, "comp": 0.3,
        "damping_up": 0.6, "max_up": 1.6, "damping_dn": 0.85, "max_dn": 2.2, "clip_limit": 0.01, "clip_back": 1.5,
        "tone": {"black": 0.012, "white": 0.96, "base_c": 8, "spread": 0.55, "c": (0, 35), "b": (-50, 25), "w": (-40, 35), "strength": 0.85}},
    "fuji_cw": {
        "weight": "center", "sigma": 0.65, "target": 0.18, "comp": 0.0,
        "damping_up": 0.75, "max_up": 2.0, "damping_dn": 0.85, "max_dn": 2.2, "clip_limit": 0.005, "clip_back": 1.0,
        "tone": {"black": 0.022, "white": 0.97, "base_c": -5, "spread": 0.50, "c": (-20, 20), "b": (-35, 35), "w": (-35, 40), "strength": 0.75}},
}
# HDR 动态测光要配合 HDR 显示模式使用（计划中），在那之前不出现在菜单里
ENABLE_HDR = False
HDR_STYLES = {
    "hdr": {
        "weight": "zones", "target": 0.16, "comp": 0.0,
        "damping_up": 0.7, "max_up": 2.0, "damping_dn": 0.9, "max_dn": 2.5, "clip_limit": 0.002, "clip_back": 3.0,
        "hdr": True},
}
if ENABLE_HDR:
    METER_STYLES.update(HDR_STYLES)
DEFAULT_METER = "leica_cw"


def meter_list() -> list:
    return [{"id": k, "name": t(f"edit.meter.{k}.name"), "desc": t(f"edit.meter.{k}.desc")} for k in METER_STYLES]


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
    note = t("edit.auto.exposure", v=f"{out['exposure']:+.2f}") + (t("edit.auto.protected") if protected else "")
    tone_stats = None
    if st.get("tone") and not st.get("hdr"):
        Yenc = srgb_encode(np.clip(srgb_decode(shot(out["exposure"])) @ REC709_Y, 0, 1))
        tone, tone_stats = auto_tone(Yenc, st["tone"])
        out.update(tone)
        note += " · " + t("edit.auto.tone", c=f"{tone['contrast']:+d}", b=f"{tone['blacks']:+d}", w=f"{tone['whites']:+d}")

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
        note = t("edit.auto.hdr", v=f"{out['exposure']:+.2f}", s=f"{shadows:+d}", h=f"{highlights:+d}", dr=f"{dr:.1f}")
    if st["comp"]:
        note += " · " + t("edit.auto.comp", v=f"{st['comp']:+.1f}")
    sid = style if style in METER_STYLES or style in HDR_STYLES else DEFAULT_METER
    return {"set": out, "style": t(f"edit.meter.{sid}.name"), "style_id": style if style in METER_STYLES else DEFAULT_METER,
            "note": note, "meter_ev": round(ev_meter, 2), "highlight_limited": bool(protected), "tone": tone_stats}
