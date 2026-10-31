"""photo-cull：照片筛选与基础编辑的本地工具。

包结构（1.8-beta 起）：
  imaging/   读图与 EXIF（RAW 预览直读、HEIF、TIFF 结构 RAW），筛选和编辑共用
  cull/      照片筛选：分析 → 分组 → 评分 → AI 细评 → XMP → 整理 → 报告
  edit/      照片编辑：色彩、LUT、预设、渲染、自动调整、导出
  server/    本地网页服务（界面和 /api 接口）
  i18n.py    多语言；paths.py 固定位置；version.py 版本号
"""
from .version import VERSION

__all__ = ["VERSION"]
