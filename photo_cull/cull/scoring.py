from __future__ import annotations

from .model import Photo


def pct_rank(values: list[float], v: float) -> float:
    if not values:
        return 0.5
    return sum(1 for x in values if x <= v) / len(values)


def score_local(photos: list[Photo], args):
    ok = [p for p in photos if not p.error]
    focus_vals = [-p.blur for p in ok]
    for p in ok:
        flags = []
        if p.blur >= args.blur_reject:
            flags.append("blur")
        elif p.blur >= args.blur_warn:
            flags.append("soft")
        if p.mean_luma < 18:
            flags.append("under")
        elif p.mean_luma > 238:
            flags.append("over")
        if p.clip_high > args.clip_high:
            flags.append(f"clip_high:{p.clip_high:.3f}")
        if p.clip_low > args.clip_low:
            flags.append(f"clip_low:{p.clip_low:.3f}")
        if p.eyes_missing:
            flags.append("eyes")
        p.flags = flags

        sharp_part = pct_rank(focus_vals, -p.blur)                   # 0..1，本批中越锐越高
        expo_part = 1 - min(1, abs(p.mean_luma - 118) / 118) * 0.6 - min(0.4, p.clip_high * 4) - min(0.3, max(0, p.clip_low - 0.05) * 2)
        face_part = 1.0 if p.faces == 0 else (0.6 if p.eyes_missing else 1.0)
        p.local_score = round(100 * (0.6 * sharp_part + 0.3 * max(0, expo_part) + 0.1 * face_part), 1)

    # 连拍组内只保留最高分为“主选”，其余为“同组备选”
    best = {}
    for p in ok:
        if p.group not in best or p.local_score > best[p.group].local_score:
            best[p.group] = p
    hard = {"blur", "under", "over"}
    for p in ok:
        p.group_best = best[p.group] is p
        if any(f in hard for f in p.flags):
            p.tier = "reject"
        elif not p.group_best:
            p.tier = "alt"
        else:
            p.tier = "candidate"
    for p in photos:
        if p.error:
            p.tier = "error"


# ───────────────────────── 星级与色标 ─────────────────────────

def label_for(stars: int) -> str:
    if stars < 0 or stars == 1:
        return "Red"
    if stars >= 4:
        return "Green"
    if stars == 3:
        return "Yellow"
    return ""


def assign_ratings(photos: list[Photo]):
    # 不开 AI 时只做技术判断：入围 3★、备选 2★、淘汰拒绝。4–5★ 只由审美细评给出。
    for p in photos:
        if p.manual:
            continue
        if p.tier == "reject":
            p.stars = -1
        elif p.tier == "error":
            p.stars = 0
        elif p.ai:
            p.stars = min(p.ai["stars"], 2) if p.tier == "alt" else p.ai["stars"]
        elif p.tier == "alt":
            p.stars = 2
        else:
            p.stars = 3
        p.label = label_for(p.stars) if p.tier != "error" else ""
