from __future__ import annotations

from .analysis import SIGS, similarity
from .model import Photo

# ───────────────────────── 分组与评分 ─────────────────────────

def group_bursts(photos: list[Photo], burst_gap: float, scene_gap: float, sim: float):
    """连拍：间隔短且画面相近；同场景重拍：间隔稍长但画面很像（适合旁轴、手动上弦等慢节奏拍摄）。"""
    photos.sort(key=lambda x: (x.time, x.name))
    gid, last = 0, None
    for p in photos:
        same = False
        if last is not None:
            dt = p.time - last.time
            c = similarity(SIGS.get(p.path), SIGS.get(last.path))
            same = (dt <= burst_gap and c >= sim - 0.15) or (dt <= scene_gap and c >= sim)
        if not same:
            gid += 1
        p.group = gid
        last = p
    sizes = {}
    for p in photos:
        sizes[p.group] = sizes.get(p.group, 0) + 1
    for p in photos:
        p.group_size = sizes[p.group]
