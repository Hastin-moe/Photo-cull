from __future__ import annotations

import io
import json
import threading
import time
from pathlib import Path

import numpy as np
from PIL import Image

from ..i18n import t
from ..imaging.exif import read_exif
from .auto import DEFAULT_METER, auto_adjust
from .color import as_planar
from .decode import decode, resize_lin
from .export import export
from .library import _exif_text
from .params import EDIT_EXT, FAST_RATIO, PREVIEW_LEVELS, PREVIEW_SIDE, normalize_params
from .records import load_edit
from .render import Context, render_parallel

# ───────────────────────── 编辑会话（界面用） ─────────────────────────

class Session:
    def __init__(self):
        self.lock = threading.Lock()
        self.render_lock = threading.Lock()
        self.path = None
        self.info = None
        self.base = None
        self.exif = {}
        self.scaled = {}                # 按档位缓存缩小后的预览，换照片时清空
        self.last = None                # 上一次渲染的 (键, JPEG)：同样的参数（如松开对比原图、窗口微调）直接返回
        self.latest = {}                # 每个浏览器页面各自的最新请求编号
        self.export = {"running": False}

    def open(self, path: str) -> dict:
        p = Path(path).expanduser()
        if not p.is_file() or p.suffix.lower() not in EDIT_EXT:
            raise ValueError(t("edit.err.unsupported_file"))
        t0 = time.time()
        lin, info = decode(str(p), half=True)
        base = as_planar(resize_lin(lin, PREVIEW_SIDE))
        try:
            exif = read_exif(p)
        except Exception:
            exif = {}
        with self.lock:
            self.path, self.info, self.base, self.exif, self.scaled, self.last = str(p), info, base, exif, {}, None
        info = dict(info)
        info["width"], info["height"] = base.shape[1], base.shape[0]
        info["decode_ms"] = int((time.time() - t0) * 1000)
        info["params"] = load_edit(str(p))
        info["exif"] = _exif_text(p)
        return info

    def _level(self, side: int) -> int:
        """界面需要的长边像素 → 最接近且不小于它的一档（上限 PREVIEW_SIDE）；没给就用 1800。"""
        if not side or side <= 0:
            return 1800
        return next((v for v in PREVIEW_LEVELS if v >= side), PREVIEW_LEVELS[-1])

    def _pick(self, level: int, fast: bool) -> np.ndarray:
        """取某一档的预览图（带缓存）；调用时已持有 self.lock。"""
        long_side = max(400, int(level * FAST_RATIO) // 100 * 100) if fast else level
        if long_side >= max(self.base.shape[:2]):
            return self.base
        if long_side not in self.scaled:
            if len(self.scaled) >= 6:
                self.scaled.pop(next(iter(self.scaled)))
            self.scaled[long_side] = as_planar(resize_lin(self.base, long_side))
        return self.scaled[long_side]

    def render_jpeg(self, P: dict, quality: str, seq: int, client: str = "", side: int = 0) -> tuple[bytes | None, dict]:
        with self.lock:
            self.latest[client] = max(self.latest.get(client, 0), seq)
            if len(self.latest) > 64:
                self.latest = {client: self.latest[client]}
        with self.render_lock:
            if seq < self.latest.get(client, 0):       # 同一页面有更新的请求在排队，跳过这次
                return None, {}
            with self.lock:
                if self.base is None:
                    raise ValueError(t("edit.err.no_photo"))
                lin = self._pick(self._level(side), quality == "fast")
                info = self.info
            t0 = time.time()
            P = normalize_params(P)
            key = (self.path, lin.shape, json.dumps(P, sort_keys=True))
            if self.last and self.last[0] == key:
                return self.last[1], {"ms": 0, "notes": self.last[2]}
            ctx = Context(info, P)
            out = render_parallel(lin, info, P, ctx)
            out *= np.float32(255)
            out += np.float32(0.5)
            img = Image.fromarray(out.astype(np.uint8))
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=82 if quality == "fast" else 92)
            data = buf.getvalue()
            self.last = (key, data, ctx.notes)
            return data, {"ms": int((time.time() - t0) * 1000), "notes": ctx.notes}

    def start_export(self, path: str, P: dict, out_dir: str | None, fmt: str, quality: int, long_edge: int):
        if self.export.get("running"):
            raise ValueError(t("edit.err.export_busy"))
        self.export = {"running": True, "msg": t("edit.export.preparing"), "pct": 0.0, "file": None, "error": None, "name": Path(path).name}

        def prog(msg, pct):
            self.export.update(msg=msg, pct=round(pct, 3))

        def run():
            try:
                f = export(path, P, out_dir, fmt, quality, long_edge, prog)
                self.export.update(file=f, msg=t("edit.export.finished"), pct=1.0)
            except Exception as e:
                self.export.update(error=f"{type(e).__name__}: {e}")
            finally:
                self.export["running"] = False
        threading.Thread(target=run, daemon=True).start()
        return self.export

    def auto(self, P: dict, style: str = DEFAULT_METER) -> dict:
        with self.lock:
            if self.base is None:
                raise ValueError(t("edit.err.no_photo"))
            base, info = self.base, self.info
        return auto_adjust(base, info, normalize_params(P), style)


SESSION = Session()
