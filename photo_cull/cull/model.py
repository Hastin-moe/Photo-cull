from __future__ import annotations

from dataclasses import dataclass, field

# ───────────────────────── 数据结构 ─────────────────────────

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
    # 技术指标
    sharp_global: float = 0.0
    sharp_subject: float = 0.0
    sharp_face: float | None = None
    blur: float = 0.0              # 再模糊指标：0 很锐，越大越糊（与画面细节多少无关）
    mean_luma: float = 0.0
    clip_high: float = 0.0
    clip_low: float = 0.0
    faces: int = 0
    eyes_missing: int = 0          # 检测到人脸但找不到眼睛的数量（可能闭眼／侧脸）
    dhash: str = ""
    # 结果
    group: int = 0
    group_size: int = 1
    group_best: bool = True
    flags: list = field(default_factory=list)
    local_score: float = 0.0
    tier: str = ""                 # reject / alt / candidate
    ai: dict | None = None
    stars: int = 0                 # -1 = 拒绝
    label: str = ""
    thumb: str = ""
    error: str = ""
    manual: bool = False           # 星级经人工调整
    trashed: bool = False          # 已移到废纸篓
PHOTO_FIELDS = set(Photo.__dataclass_fields__)
