from __future__ import annotations

from ..paths import SETTINGS

from ..paths import CONFIG_DIR

import json
import os
from pathlib import Path

from ..cull.ai.providers import PROVIDERS


CONFIG = SETTINGS

DEFAULTS = {
    "folder": "", "recursive": False, "ai": False, "provider": "claude", "ai_alts": False,
    **{"model_" + k: v["default"] for k, v in PROVIDERS.items()},
    **{"key_" + k: "" for k in PROVIDERS}, "remember_key": False, "base_url_custom": "",
    "edit_folder": "", "edit_library": "",
    "xmp": True, "jpeg_embed": True, "xmp_all": False, "dry_run": True,
    "org": False, "org_dir": "", "org_result": True, "org_format": True, "org_rename": True, "org_move": False,
    "burst_gap": 15.0, "scene_gap": 60.0, "similarity": 0.6, "blur_warn": 0.58, "blur_reject": 0.75,
    "clip_high": 0.04, "clip_low": 0.30, "workers": 4,
}
KEYS = tuple("key_" + k for k in PROVIDERS)
TUNING = {"burst_gap", "scene_gap", "similarity", "blur_warn", "blur_reject", "clip_high", "clip_low"}
SETTINGS_VERSION = 3


def load_settings() -> dict:
    s = dict(DEFAULTS)
    try:
        saved = json.loads(CONFIG.read_text(encoding="utf-8"))
        if saved.get("settings_version", 0) < 2:          # 旧版本的阈值算法不同，恢复默认
            saved = {k: v for k, v in saved.items() if k not in TUNING}
        if saved.get("api_key") and not saved.get("key_claude"):   # 1.0/1.1 只有 Claude 一个 Key
            saved["key_claude"] = saved["api_key"]
        if saved.get("model", "").startswith("claude"):
            saved.setdefault("model_claude", saved["model"])
        s.update({k: v for k, v in saved.items() if k in DEFAULTS})
    except Exception:
        pass
    return s


def save_settings(s: dict):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    old = load_settings()
    data = {k: s.get(k, old.get(k, v)) for k, v in DEFAULTS.items()}
    data["settings_version"] = SETTINGS_VERSION
    if not data.get("remember_key"):
        for k in KEYS:
            data[k] = ""
    tmp = CONFIG.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(CONFIG)


def _remember(**kw):
    try:
        s = load_settings()
        s.update(kw)
        save_settings(s)
    except OSError:
        pass
