from __future__ import annotations

RAW_EXT = {".arw", ".srf", ".sr2", ".dng", ".cr2", ".cr3", ".nef", ".raf", ".orf", ".rw2", ".pef", ".3fr", ".iiq"}
IMG_EXT = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".heic", ".heif", ".hif", ".webp"}
JPEG_EXT = {".jpg", ".jpeg"}


# ───────────────────────── 读取 ─────────────────────────

_heif_ready = None

def _ensure_heif():
    global _heif_ready
    if _heif_ready is None:
        try:
            import pillow_heif
            pillow_heif.register_heif_opener()
            _heif_ready = True
        except ImportError:
            _heif_ready = False
    return _heif_ready
