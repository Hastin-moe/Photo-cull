"""照片筛选的数据结构和结果文件格式。

结果文件格式（photo-cull-report/results.json）：
  1.8-beta 起是 {"schema": 2, "photos": [...]}；1.7.1 及以前是一个裸列表（schema 1），载入时自动转换。

评分（schema 2）：
  score     10 分制，精确到 0.1（界面只显示整数部分）。本地筛选最高 6.0，6 分以上只由 AI 细评给出。
  category  pick 精选／moment 连拍瞬间／usable 可用／reject 淘汰／error 读取失败
  stars     写进 XMP 的 1–5 星：score ÷ 2 向下取整（7.9 → 3★）；淘汰为 −1（拒绝），0 为不评星
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, fields

SCHEMA = 2
CATEGORIES = ("pick", "moment", "usable", "reject", "error")
KEPT = ("pick", "moment", "usable")
LOCAL_MAX = 6.0          # 本地筛选能给到的最高分
SCORE_MAX = 10.0


@dataclass
class Photo:
    path: str                      # 主文件（有 RAW 时为 RAW）
    name: str
    kind: str                      # raw / image
    members: list = field(default_factory=list)   # 同名配对的全部文件（RAW、JPEG、HIF…）
    source: str = ""               # 实际用于分析的文件（有 JPEG 时用 JPEG）
    time: float = 0.0
    time_text: str = ""
    camera: str = ""
    lens: str = ""
    exposure: str = ""
    width: int = 0
    height: int = 0
    # ── 技术指标（本地分析）
    sharp_global: float = 0.0
    sharp_subject: float = 0.0
    sharp_face: float | None = None
    blur: float = 0.0              # 再模糊指标：0 很锐，越大越糊（与画面细节多少无关）
    mean_luma: float = 0.0
    clip_high: float = 0.0
    clip_low: float = 0.0
    faces: int = 0
    eyes_missing: int = 0          # 检测到人脸但找不到眼睛的数量（可能闭眼／侧脸）
    smiles: int = 0                # 检测到笑容的人脸数（Haar，只作参考）
    face_area: float = 0.0         # 最大的一张脸占画面的比例（主体是否突出）
    dhash: str = ""
    # ── 分组
    group: int = 0
    group_size: int = 1
    group_best: bool = True        # 连拍组里按精彩帧权重选出的那一张（单张照片也为 True）
    highlight: float = 0.0         # 精彩帧得分 0–1（只在组内比较，用来挑连拍瞬间）
    # ── 评分结果
    flags: list = field(default_factory=list)
    local_score: float = 0.0       # 本地技术分 0–6.0
    ai: dict | None = None         # AI 细评：genre scores overall(1.0–10.0) keep comment issues lang provider model
    score: float = 0.0             # 最终 10 分制分数（0.1 精度）
    category: str = ""             # pick / moment / usable / reject / error
    stars: int = 0                 # XMP 星级（由 score 折算），−1 = 拒绝
    label: str = ""                # XMP 色标
    thumb: str = ""
    error: str = ""
    manual: bool = False           # 分数经人工调整
    trashed: bool = False          # 已移到废纸篓

    @property
    def rejected(self) -> bool:
        return self.category == "reject"

    @property
    def kept(self) -> bool:
        return self.category in KEPT


PHOTO_FIELDS = {f.name for f in fields(Photo)}


def xmp_stars(score: float, rejected: bool = False) -> int:
    """10 分制 → XMP 的 1–5 星：除以 2 向下取整（9.9 → 4★，10 → 5★）；淘汰 −1。"""
    if rejected:
        return -1
    return max(0, min(5, math.floor(round(score, 1) / 2 + 1e-9)))


def label_for(stars: int) -> str:
    """色标跟着 XMP 星级走：4–5★ 绿、3★ 黄、1★ 和拒绝 红。"""
    if stars < 0 or stars == 1:
        return "Red"
    if stars >= 4:
        return "Green"
    if stars == 3:
        return "Yellow"
    return ""


def shown(score: float) -> int:
    """界面上显示的分数：只显示整数部分（0.1 精度不显示）。"""
    return int(math.floor(round(score, 1) + 1e-9))


# ───────────────────────── 旧结果转换 ─────────────────────────

def _upgrade_v1(r: dict) -> dict:
    """1.7.1 及以前的一条记录 → schema 2。
    星级 1–5 → 分数 ×2；本地分 0–100 → 1–6；档位 candidate／alt／reject → 分类。"""
    r = dict(r)
    tier = r.pop("tier", "")
    stars = int(r.get("stars", 0) or 0)
    old_local = float(r.get("local_score", 0) or 0)
    r["local_score"] = round(1 + 5 * max(0.0, min(100.0, old_local)) / 100, 1) if tier not in ("reject", "error") else 0.0
    if tier == "error":
        r["category"], r["score"] = "error", 0.0
    elif tier == "reject" or stars < 0:
        r["category"], r["score"] = "reject", 0.0
    else:
        ai = r.get("ai") or None
        r["score"] = float(stars * 2) if stars > 0 else r["local_score"]
        if ai and "overall" in ai and not r.get("manual"):
            r["score"] = float(ai["overall"])
        if tier == "alt":
            r["category"] = "usable"
        elif int(r.get("group_size", 1) or 1) > 1:
            r["category"] = "moment"
        else:
            r["category"] = "pick" if r["score"] >= (7.0 if ai else 5.0) else "usable"
    r["stars"] = xmp_stars(r["score"], r["category"] == "reject") if r["category"] != "error" else 0
    return r


def photos_from_json(data) -> tuple[list[Photo], int]:
    """results.json 的内容 → Photo 列表；返回 (照片, 原来的 schema)。"""
    if isinstance(data, list):
        rows, schema = [_upgrade_v1(r) for r in data], 1
    else:
        rows, schema = data.get("photos", []), int(data.get("schema", SCHEMA))
    return [Photo(**{k: v for k, v in r.items() if k in PHOTO_FIELDS}) for r in rows], schema
