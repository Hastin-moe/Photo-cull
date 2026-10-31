from __future__ import annotations

import re
import struct
import zlib
from pathlib import Path

import numpy as np

from ..i18n import t
from .color import mat, srgb_decode, srgb_encode, srgb_to
from .logspace import guess_space
from .lut3d import _CACHE_LOCK, apply_lut3d, load_cube
from .refs import resolve_style, style_ref

# ───────────────────────── Adobe XMP 预设：RGBTable／LookTable ─────────────────────────

_B85 = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ.-:+=^!/*?`'|()[]{}@%$#"
_B85_MAP = {c: i for i, c in enumerate(_B85)}
RGB_PRIMARIES = {0: "srgb", 1: "adobe", 2: "prophoto", 3: "p3", 4: "rec2020"}


def decode_big_table(text: str) -> bytes:
    """Adobe DNG SDK dng_big_table 的字符串编码：85 进制（自定义字母表）→ 4 字节长度 + zlib。"""
    vals = [_B85_MAP[c] for c in text if c in _B85_MAP]
    out = bytearray()
    for k in range(0, len(vals), 5):
        grp = vals[k:k + 5]
        x = 0
        for j, v in enumerate(grp):
            x += v * 85 ** j
        out += (x & 0xFFFFFFFF).to_bytes(4, "little")[:len(grp) - 1 if len(grp) < 5 else 4]
    size = struct.unpack("<I", out[:4])[0]
    raw = zlib.decompress(bytes(out[4:]))
    if len(raw) != size:
        raise ValueError("色彩表长度不符")
    return raw


def parse_table(raw: bytes) -> dict:
    typ, ver = struct.unpack("<2I", raw[:8])
    if typ == 1:                                   # RGBTable
        dims, n = struct.unpack("<2I", raw[8:16])
        if dims != 3 or not 2 <= n <= 64:
            raise ValueError("暂不支持的 RGBTable 维度")
        cnt = n ** 3 * 3
        d = np.frombuffer(raw[16:16 + cnt * 2], dtype="<u2").reshape(n, n, n, 3).astype(np.int32)
        idv = (np.arange(n) * 0xFFFF + (n >> 1)) // (n - 1)
        ident = np.stack(np.meshgrid(idv, idv, idv, indexing="ij"), axis=-1)
        absolute = ((d + ident) & 0xFFFF).astype(np.float32) / 65535.0
        tail = raw[16 + cnt * 2:]
        prim, gamma, gamut = struct.unpack("<3I", tail[:12]) if len(tail) >= 12 else (0, 1, 0)
        mn, mx = struct.unpack("<2d", tail[12:28]) if len(tail) >= 28 else (0.0, 2.0)
        return {"type": "rgb", "table": absolute, "primaries": RGB_PRIMARIES.get(prim, "srgb"),
                "gamma": gamma, "min": mn, "max": mx}
    if typ == 0:                                   # LookTable（色相／饱和度／明度）
        h, s, v = struct.unpack("<3I", raw[8:20])
        cnt = h * s * v
        deltas = np.frombuffer(raw[20:20 + cnt * 12], dtype="<f4").reshape(v, h, s, 3).copy()
        enc = struct.unpack("<I", raw[20 + cnt * 12:24 + cnt * 12])[0] if len(raw) >= 24 + cnt * 12 else 0
        return {"type": "hsv", "table": deltas, "srgb_value": enc == 1}
    raise ValueError(f"未知的色彩表类型 {typ}")


def apply_rgbtable(img_srgb: np.ndarray, t: dict, amount: float) -> np.ndarray:
    if amount <= 0:
        return img_srgb
    prim, gamma = t["primaries"], t["gamma"]
    if prim == "srgb" and gamma == 1:
        x = img_srgb
        y = apply_lut3d(x, t["table"])
    else:
        lin = srgb_decode(img_srgb)
        if prim != "srgb":
            lin = mat(lin, srgb_to(prim))
        x = _gamma_encode(np.clip(lin, 0, 1), gamma)
        y = apply_lut3d(x, t["table"])
        y = _gamma_decode(np.clip(y, 0, 1), gamma)
        x = img_srgb
        if prim != "srgb":
            y = mat(y, np.linalg.inv(srgb_to(prim)))
        y = srgb_encode(y)
    return np.clip(x + amount * (y - x), 0, 1)


def _gamma_encode(x, g):
    if g == 0:
        return x
    if g == 1:
        return srgb_encode(x)
    return np.power(x, 1 / (1.8 if g == 2 else 2.2 if g == 3 else 2.4))


def _gamma_decode(x, g):
    if g == 0:
        return x
    if g == 1:
        return srgb_decode(x)
    return np.power(x, 1.8 if g == 2 else 2.2 if g == 3 else 2.4)


def apply_huesat(lin: np.ndarray, t: dict, amount: float, chunk: int = 1 << 20) -> np.ndarray:
    """DNG HueSatMap／LookTable：在线性 ProPhoto 的 HSV 上做色相偏移、饱和度和明度缩放。"""
    if amount <= 0:
        return lin
    tab = t["table"]
    V, Hn, S = tab.shape[:3]
    flat = tab.reshape(-1, 3)
    src = lin.reshape(-1, 3)
    out = np.empty_like(src, dtype=np.float32)
    for a in range(0, src.shape[0], chunk):
        px = src[a:a + chunk]
        r, g, b = px[:, 0], px[:, 1], px[:, 2]
        mx = px.max(axis=1)
        mn = px.min(axis=1)
        dl = mx - mn
        safe = np.where(dl > 1e-9, dl, 1.0)
        h = np.where(mx == r, (g - b) / safe, np.where(mx == g, 2 + (b - r) / safe, 4 + (r - g) / safe))
        h = np.where(dl > 1e-9, np.mod(h, 6.0), 0.0)
        s = np.where(mx > 1e-9, dl / np.where(mx > 1e-9, mx, 1.0), 0.0)
        vv = srgb_encode(mx) if t["srgb_value"] else np.clip(mx, 0, 1)
        hf = h * (Hn / 6.0)
        h0 = np.floor(hf).astype(np.int32) % Hn
        h1 = (h0 + 1) % Hn
        fh = (hf - np.floor(hf)).astype(np.float32)
        if S > 1:
            sf = s * (S - 1)
            s0 = np.minimum(np.floor(sf).astype(np.int32), S - 2)
            fs = (sf - s0).astype(np.float32)
        else:
            s0 = np.zeros_like(h0)
            fs = np.zeros_like(fh)
        if V > 1:
            vf = vv * (V - 1)
            v0 = np.minimum(np.floor(vf).astype(np.int32), V - 2)
            fv = (vf - v0).astype(np.float32)
        else:
            v0 = np.zeros_like(h0)
            fv = np.zeros_like(fh)
        s1 = np.minimum(s0 + 1, S - 1)
        v1 = np.minimum(v0 + 1, V - 1)

        def g_(vi, hi, si):
            return flat[(vi * Hn + hi) * S + si]

        def lerp(a_, b_, w):
            return a_ + (b_ - a_) * w[:, None]
        c00 = lerp(g_(v0, h0, s0), g_(v0, h0, s1), fs)
        c01 = lerp(g_(v0, h1, s0), g_(v0, h1, s1), fs)
        c10 = lerp(g_(v1, h0, s0), g_(v1, h0, s1), fs)
        c11 = lerp(g_(v1, h1, s0), g_(v1, h1, s1), fs)
        d = lerp(lerp(c00, c01, fh), lerp(c10, c11, fh), fv)
        hs = d[:, 0] * amount / 60.0
        ss = 1 + (d[:, 1] - 1) * amount
        vs = 1 + (d[:, 2] - 1) * amount
        h2 = np.mod(h + hs, 6.0)
        s2 = np.clip(s * ss, 0, 1)
        v2 = mx * vs
        # HSV → RGB（向量化公式：f(n) = v − v·s·clip(min(k, 4−k), 0, 1)，k = (n + h) mod 6）
        vs_ = v2 * s2
        res = np.empty((px.shape[0], 3), np.float32)
        for j, nn in enumerate((5.0, 3.0, 1.0)):
            k = np.mod(nn + h2, 6.0)
            res[:, j] = v2 - vs_ * np.clip(np.minimum(k, 4.0 - k), 0.0, 1.0)
        out[a:a + chunk] = np.where((dl > 1e-9)[:, None], res, px * vs[:, None])
    return out.reshape(lin.shape)


# ───────────────────────── XMP 预设解析 ─────────────────────────

SLIDER_MAP = {"Exposure2012": "exposure", "Contrast2012": "contrast", "Highlights2012": "highlights",
              "Shadows2012": "shadows", "Whites2012": "whites", "Blacks2012": "blacks", "Clarity2012": "clarity",
              "Vibrance": "vibrance", "Saturation": "saturation", "IncrementalTemperature": "temp",
              "IncrementalTint": "tint"}
UNSUPPORTED_NAMES = {      # Lightroom 参数 → 不支持的功能代码（显示名见语言包 edit.unsup.*）
    "Texture": "texture", "Dehaze": "dehaze", "Sharpness": "sharpen", "LuminanceSmoothing": "nr", "ColorNoiseReduction": "color_nr",
    "GrainAmount": "grain", "PostCropVignetteAmount": "vignette", "Temperature": "abs_temp", "Tint": "abs_tint",
    "ParametricShadows": "parametric", "ParametricDarks": "parametric", "ParametricLights": "parametric",
    "ParametricHighlights": "parametric", "SplitToningShadowSaturation": "split_toning", "SplitToningHighlightSaturation": "split_toning",
    "ColorGradeMidtoneSat": "color_grading", "ColorGradeShadowSat": "color_grading", "ColorGradeHighlightSat": "color_grading",
    "ColorGradeGlobalSat": "color_grading", "LensProfileEnable": "lens_corr", "PerspectiveVertical": "perspective",
}
HSL_PREFIX = ("HueAdjustment", "SaturationAdjustment", "LuminanceAdjustment")
_PRESET_CACHE: dict = {}
_LOOK_INDEX: dict = {}


def _attrs(text: str) -> dict:
    return {k: v for k, v in re.findall(r'\bcrs:([A-Za-z0-9_]+)="([^"]*)"', text)}


def _curve(text: str, name: str):
    m = re.search(rf"<crs:{name}>\s*<rdf:Seq>(.*?)</rdf:Seq>", text, re.S)
    if not m:
        return None
    pts = []
    for li in re.findall(r"<rdf:li>\s*([^<]*)</rdf:li>", m.group(1)):
        try:
            a, b = (float(v) for v in li.split(","))
            pts.append([a / 255.0, b / 255.0])
        except ValueError:
            pass
    return pts if len(pts) >= 2 else None


def _is_identity(pts) -> bool:
    return pts is None or all(abs(a - b) < 1e-6 for a, b in pts)


def _name(text: str) -> str:
    m = re.search(r"<crs:Name>.*?<rdf:li[^>]*>([^<]*)</rdf:li>", text, re.S)
    return m.group(1).strip() if m else ""


def _tables(text: str, attrs: dict) -> dict:
    out = {}
    for key in ("RGBTable", "LookTable"):
        md5 = attrs.get(key)
        if md5:
            m = re.search(rf'crs:Table_{md5}="([^"]+)"', text)
            if m:
                out[key] = parse_table(decode_big_table(m.group(1)))
    return out


def read_preset(path: str) -> dict:
    """解析 Lightroom／Camera Raw 的 XMP 预设或外观（Look）。结果会缓存。"""
    p = Path(path)
    key = (str(p), p.stat().st_mtime)
    with _CACHE_LOCK:
        if key in _PRESET_CACHE:
            return _PRESET_CACHE[key]
    text = p.read_text(encoding="utf-8", errors="replace")
    look_block = ""
    m = re.search(r"<crs:Look>(.*?)</crs:Look>", text, re.S)
    if m:
        look_block = m.group(1)
        text_main = text[:m.start()] + text[m.end():]
    else:
        text_main = text
    attrs = _attrs(text_main)
    kind = attrs.get("PresetType", "Normal")
    res = {"path": str(p), "name": _name(text_main) or p.stem, "type": kind, "uuid": attrs.get("UUID", ""),
           "set": {}, "curves": {}, "mono": attrs.get("ConvertToGrayscale") == "True",
           "tables": {}, "look_ref": None, "unsupported": [], "profile": attrs.get("CameraProfile", ""),
           "for_raw": attrs.get("SupportsSceneReferred", "True") != "False",
           "for_jpeg": attrs.get("SupportsOutputReferred", "True") != "False"}
    for k, field in SLIDER_MAP.items():
        if k in attrs:
            try:
                res["set"][field] = float(attrs[k])
            except ValueError:
                pass
    for ch, name in (("rgb", "ToneCurvePV2012"), ("r", "ToneCurvePV2012Red"), ("g", "ToneCurvePV2012Green"),
                     ("b", "ToneCurvePV2012Blue")):
        pts = _curve(text_main, name)
        if pts and not _is_identity(pts):
            res["curves"][ch] = pts
    unsup = set()
    for k, v in attrs.items():
        label = UNSUPPORTED_NAMES.get(k)
        if label is None and k.startswith(HSL_PREFIX):
            label = "hsl"
        if label and v not in ("0", "+0", "0.0", "", "False", "false"):
            if k in ("Temperature", "Tint") and attrs.get("WhiteBalance") in (None, "As Shot"):
                continue
            unsup.add(label)
    if "<crs:CorrectionMasks>" in text_main or "<crs:MaskGroupBasedCorrections>" in text_main:
        unsup.add("masks")
    if "HDREditMode" in attrs and attrs["HDREditMode"] == "1":
        unsup.add("hdr")
    res["unsupported"] = sorted(unsup)
    res["tables"] = _tables(text_main, attrs)
    if look_block:
        la = _attrs(look_block)
        ref = {"name": la.get("Name", ""), "uuid": la.get("UUID", ""), "amount": float(la.get("Amount", "1") or 1)}
        if "Table_" in look_block:                      # 外观数据直接内嵌在预设里
            inner = _tables(look_block, la)
            if inner:
                ref["inline"] = {"tables": inner, "curves": {}, "mono": la.get("ConvertToGrayscale") == "True"}
        res["look_ref"] = ref
    with _CACHE_LOCK:
        if len(_PRESET_CACHE) > 64:
            _PRESET_CACHE.clear()
        _PRESET_CACHE[key] = res
    return res


def _scan_looks(folder: Path) -> dict:
    """读取文件夹里所有 Look 类 XMP 的 UUID 和名称（只读文件开头，速度快）。"""
    key = (str(folder), folder.stat().st_mtime)
    if key in _LOOK_INDEX:
        return _LOOK_INDEX[key]
    idx = {}
    for f in folder.iterdir():
        if f.suffix.lower() != ".xmp" or not f.is_file():
            continue
        try:
            with open(f, "rb") as fh:
                head = fh.read(6000).decode("utf-8", errors="replace")
        except OSError:
            continue
        if 'crs:PresetType="Look"' not in head:
            continue
        a = _attrs(head.split("<crs:Look>")[0])
        nm = _name(head)
        if a.get("UUID"):
            idx[a["UUID"]] = str(f)
        if nm:
            idx.setdefault("name:" + nm, str(f))
    _LOOK_INDEX[key] = idx
    return idx


def resolve_look(preset: dict, root: str | None = None) -> str | None:
    """预设里只写了外观的 UUID／名称时，在同一文件夹及上级（不超过素材库根目录）里找对应的 Look 文件。"""
    ref = preset.get("look_ref")
    if not ref:
        return None
    here = Path(preset["path"]).parent
    stop = Path(root).resolve() if root else None
    for _ in range(4):
        try:
            idx = _scan_looks(here)
        except OSError:
            idx = {}
        hit = idx.get(ref.get("uuid", "")) or idx.get("name:" + ref.get("name", ""))
        if hit:
            return hit
        if stop is not None and here.resolve() == stop or here.parent == here:
            break
        here = here.parent
    # 再看兄弟文件夹（例如 “配置文件” 子目录）
    for sub in Path(preset["path"]).parent.parent.glob("*/"):
        try:
            idx = _scan_looks(sub)
        except OSError:
            continue
        hit = idx.get(ref.get("uuid", "")) or idx.get("name:" + ref.get("name", ""))
        if hit:
            return hit
    return None


def describe_style(path: str, root: str | None = None) -> dict:
    """给界面用：选中一个 .cube 或 .xmp 后，返回要应用的参数和说明。"""
    p = Path(resolve_style(path))
    if p.suffix.lower() == ".cube":
        c = load_cube(str(p))
        return {"kind": "lut", "name": c["title"] or p.stem, "path": style_ref(str(p)), "size": c["size"], "lut_kind": c["kind"],
                "space": c["space"], "warning": guess_space(str(p))[1]}      # 提示文字按当前语言重新生成（load_cube 有缓存）
    if p.suffix.lower() != ".xmp":
        raise ValueError(t("edit.err.style_type"))
    pr = read_preset(path)
    out = {"kind": "look" if pr["type"] == "Look" else "preset", "name": pr["name"], "path": str(p),
           "set": pr["set"] if pr["type"] != "Look" else {}, "curves": pr["curves"] if pr["type"] != "Look" else {},
           "mono": pr["mono"], "unsupported": pr["unsupported"], "look": None, "warning": "",
           "has_rgbtable": "RGBTable" in pr["tables"], "has_looktable": "LookTable" in pr["tables"],
           "profile": pr["profile"]}
    target = pr
    if pr["type"] == "Look":
        out["look"] = {"path": str(p), "name": pr["name"]}
    elif pr["look_ref"]:
        if pr["look_ref"].get("inline"):
            out["look"] = {"path": str(p), "name": pr["look_ref"].get("name") or pr["name"]}
        else:
            hit = resolve_look(pr, root)
            if hit:
                out["look"] = {"path": hit, "name": pr["look_ref"].get("name") or Path(hit).stem}
                try:
                    target = read_preset(hit)
                except Exception:
                    pass
            else:
                out["warning"] = t("edit.warn.look_missing", name=pr["look_ref"].get("name") or "")
    out["for_raw"], out["for_jpeg"] = target.get("for_raw", True), target.get("for_jpeg", True)
    if pr["profile"] and pr["profile"] not in ("Adobe Standard", "Adobe Color", ""):
        out["unsupported"] = sorted(set(out["unsupported"]) | {"profile:" + pr["profile"]})
    out["unsupported"] = [unsup_text(u) for u in out["unsupported"]]
    return out


def unsup_text(code: str) -> str:
    if code.startswith("profile:"):
        return t("edit.unsup.profile", name=code[8:])
    key = "edit.unsup." + code
    text = t(key)
    return code if text == key else text


def look_layers(path: str) -> dict:
    """把一个外观（Look 预设，或内嵌外观的普通预设）整理成渲染要用的表和曲线。"""
    pr = read_preset(path)
    if pr["type"] == "Look":
        return {"tables": pr["tables"], "curves": pr["curves"], "mono": pr["mono"]}
    ref = pr.get("look_ref") or {}
    if ref.get("inline"):
        return ref["inline"]
    return {"tables": {}, "curves": {}, "mono": False}
