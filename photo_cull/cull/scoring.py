"""评分：问题标记、本地技术分（最高 6.0）、精彩帧权重（挑连拍瞬间）、最终分数和分类。

流程：score_local() → [AI 细评] → finalize()。
  · 本地技术分只看对焦、曝光、人脸／眼睛，最高 6.0；6 分以上只能由 AI 细评给出。
  · 连拍组（含同场景重拍）里按「精彩帧权重」挑一张作为连拍瞬间，其余为可用。
  · 单张照片分数达到精选线进 精选，否则进 可用。
"""
from __future__ import annotations

from types import SimpleNamespace

from .model import KEPT, LOCAL_MAX, Photo, label_for, xmp_stars

# 精彩帧权重：连拍组里挑哪一张。各项都是 0–1，在同一组里比较，加权求和。
HIGHLIGHT_WEIGHTS = {
    "sharp": 0.35,       # 主体清晰（同组里越锐越好）
    "eyes": 0.25,        # 睁眼：检测到的人脸里有眼睛的比例
    "smile": 0.10,       # 笑容：检测到笑容的人脸比例
    "exposure": 0.15,    # 曝光：亮度适中、不溢出、不死黑
    "subject": 0.15,     # 主体突出：最大一张脸占画面的比例（同组里比较）
}
PICK_AI = 7.0            # 精选线：AI 细评过的照片
PICK_LOCAL = 5.0         # 精选线：只有本地分的照片（本地最高 6.0）
ALT_CAP = 4.9            # 连拍里没被选中的帧最高分（XMP 2★），免得和连拍瞬间抢位置
SOFT_CAP = 4.0           # 「可能失焦／抖动」的照片本地分上限
HARD_FLAGS = {"blur", "under", "over"}

DEFAULTS = SimpleNamespace(blur_reject=0.75, blur_warn=0.58, clip_high=0.04, clip_low=0.30,
                           pick_ai=PICK_AI, pick_local=PICK_LOCAL, weights=HIGHLIGHT_WEIGHTS)


def _opt(args, name):
    return getattr(args, name, None) if getattr(args, name, None) is not None else getattr(DEFAULTS, name)


def parse_weights(text: str | None) -> dict:
    """命令行的 --weights sharp=0.4,eyes=0.3 → 完整的权重表（没写的项用默认值；全部为 0 时退回默认）。"""
    w = dict(HIGHLIGHT_WEIGHTS)
    for part in (text or "").replace("，", ",").split(","):
        if "=" in part:
            k, _, v = part.partition("=")
            k = k.strip()
            if k in w:
                w[k] = max(0.0, float(v))
    return w if sum(w.values()) > 0 else dict(HIGHLIGHT_WEIGHTS)


def pct_rank(values: list[float], v: float) -> float:
    if not values:
        return 0.5
    return sum(1 for x in values if x <= v) / len(values)


def exposure_quality(p: Photo) -> float:
    """0–1：平均亮度离中灰越远、高光溢出和死黑越多，分越低。"""
    q = 1 - min(1, abs(p.mean_luma - 118) / 118) * 0.6 - min(0.4, p.clip_high * 4) - min(0.3, max(0, p.clip_low - 0.05) * 2)
    return max(0.0, q)


def flags_for(p: Photo, args) -> list[str]:
    flags = []
    if p.blur >= _opt(args, "blur_reject"):
        flags.append("blur")
    elif p.blur >= _opt(args, "blur_warn"):
        flags.append("soft")
    if p.mean_luma < 18:
        flags.append("under")
    elif p.mean_luma > 238:
        flags.append("over")
    if p.clip_high > _opt(args, "clip_high"):
        flags.append(f"clip_high:{p.clip_high:.3f}")
    if p.clip_low > _opt(args, "clip_low"):
        flags.append(f"clip_low:{p.clip_low:.3f}")
    if p.eyes_missing:
        flags.append("eyes")
    return flags


def score_local(photos: list[Photo], args=None):
    """问题标记 + 本地技术分（1.0–6.0，0.1 精度）+ 精彩帧得分 + 每组的连拍瞬间。"""
    ok = [p for p in photos if not p.error]
    focus_vals = [-p.blur for p in ok]
    for p in ok:
        p.flags = flags_for(p, args)
        sharp_part = pct_rank(focus_vals, -p.blur)                   # 0–1，本批中越锐越高
        face_part = 1.0 if p.faces == 0 else (0.6 if p.eyes_missing else 1.0)
        tech = 0.6 * sharp_part + 0.3 * exposure_quality(p) + 0.1 * face_part
        p.local_score = round(1 + (LOCAL_MAX - 1) * tech, 1)
        if "soft" in p.flags:
            p.local_score = min(p.local_score, SOFT_CAP)
        if any(f in HARD_FLAGS for f in p.flags):
            p.local_score = 0.0
            p.category = "reject"
        else:
            p.category = ""
    for p in photos:
        if p.error:
            p.category = "error"
    highlight(photos, _opt(args, "weights"))
    choose_moments(photos)


def _groups(photos: list[Photo]) -> dict[int, list[Photo]]:
    g: dict[int, list[Photo]] = {}
    for p in photos:
        if not p.error:
            g.setdefault(p.group, []).append(p)
    return g


def highlight(photos: list[Photo], weights: dict | None = None):
    """精彩帧得分：各项在同一组里比较（锐度、主体大小用组内排名／比例），按权重加权，0–1。"""
    w = weights or HIGHLIGHT_WEIGHTS
    total = sum(w.values()) or 1.0
    for members in _groups(photos).values():
        sharp_vals = [-p.blur for p in members]
        max_area = max((p.face_area for p in members), default=0.0)
        for p in members:
            parts = {
                "sharp": pct_rank(sharp_vals, -p.blur) if len(members) > 1 else 1.0,
                "eyes": 0.5 if p.faces == 0 else 1 - p.eyes_missing / p.faces,
                "smile": 0.5 if p.faces == 0 else min(1.0, p.smiles / p.faces),
                "exposure": exposure_quality(p),
                "subject": 0.5 if max_area <= 0 else p.face_area / max_area,
            }
            p.highlight = round(sum(w.get(k, 0) * v for k, v in parts.items()) / total, 4)


def choose_moments(photos: list[Photo]):
    """每组挑一张：组里每张都有 AI 分时，AI 分占 60%、精彩帧得分占 40%；否则只看精彩帧得分。
    淘汰的照片不参加；单张照片自己就是「最佳」。"""
    for members in _groups(photos).values():
        cand = [p for p in members if p.category != "reject"]
        for p in members:
            p.group_best = False
        if not cand:
            continue
        all_ai = all(p.ai and "overall" in p.ai for p in cand)

        def key(p):
            base = 0.6 * float(p.ai["overall"]) / 10 + 0.4 * p.highlight if all_ai else p.highlight
            return (base, p.local_score, -p.time)
        max(cand, key=key).group_best = True


def ai_candidates(photos: list[Photo], include_alts: bool = False) -> list[Photo]:
    """送去 AI 细评的照片：每组选中的那张（和单张照片）；include_alts 时连拍里其余的帧也送。"""
    return [p for p in photos if p.category != "reject" and not p.error and (p.group_best or include_alts)]


def categorize(p: Photo, args=None):
    """按分数和分组决定 精选／连拍瞬间／可用（淘汰和读取失败不变）。"""
    if p.category in ("reject", "error"):
        return
    if p.group_size > 1:
        p.category = "moment" if p.group_best else "usable"
        return
    line = _opt(args, "pick_ai") if (p.ai and "overall" in p.ai) else _opt(args, "pick_local")
    p.category = "pick" if p.score >= line else "usable"


def finalize(photos: list[Photo], args=None):
    """最终分数、分类、XMP 星级和色标。手动调整过的照片保留手动分数（只重新算分类和星级）。"""
    choose_moments(photos)            # AI 分出来以后组里可能换一张
    for p in photos:
        if p.error:
            p.category, p.score, p.stars, p.label = "error", 0.0, 0, ""
            continue
        if p.manual:
            if p.category != "reject":
                p.category = ""
        elif p.category == "reject":
            p.score = 0.0
        else:
            p.score = round(float(p.ai["overall"]), 1) if p.ai and "overall" in p.ai else p.local_score
            if p.group_size > 1 and not p.group_best:
                p.score = min(p.score, ALT_CAP)
        categorize(p, args)
        p.stars = xmp_stars(p.score, p.category == "reject")
        p.label = label_for(p.stars)


def set_manual(p: Photo, score: float, args=None):
    """报告里手动打分：score 1–10；−1 为淘汰；0 为清除（回到未评分的可用）。"""
    p.manual = True
    if score < 0:
        p.category, p.score = "reject", 0.0
    else:
        if p.category == "reject":
            p.category = ""
        p.score = round(max(0.0, min(10.0, float(score))), 1)
        categorize(p, args)
    p.stars = xmp_stars(p.score, p.category == "reject")
    p.label = label_for(p.stars)


def counts(photos: list[Photo]) -> dict:
    live = [p for p in photos if not p.trashed]
    c = {k: 0 for k in KEPT + ("reject", "error")}
    for p in live:
        c[p.category] = c.get(p.category, 0) + 1
    return c
