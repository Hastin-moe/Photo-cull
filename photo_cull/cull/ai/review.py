from __future__ import annotations

import base64
import concurrent.futures as cf
import hashlib
import io
import json
import sys
from pathlib import Path

from PIL import Image

from ... import i18n
from ...i18n import t
from ...imaging.preview import _fit
from ..flags import flag_text
from ..model import Photo
from ..state import CANCEL, Cancelled, _report
from .prompts import _parse_json, ai_prompt
from .providers import PROVIDERS, make_caller

AI_SIDE = 1024     # 发给 AI 的长边像素


def _jpeg_b64(img: Image.Image, side: int) -> tuple[str, str]:
    buf = io.BytesIO()
    _fit(img, side).save(buf, "JPEG", quality=85)
    data = buf.getvalue()
    return base64.b64encode(data).decode(), hashlib.sha1(data).hexdigest()


def ai_review(items: list[tuple[Photo, Image.Image]], args, cache: dict, cache_path: Path):
    provider = args.provider
    info = PROVIDERS[provider]
    model = args.model or info["default"]
    if not model:
        sys.exit(t("cull.err.custom_incomplete"))
    lang = i18n.current()
    label = f"{info['name']} ({model})"
    jobs = []
    for p, img in items:
        b64, digest = _jpeg_b64(img, AI_SIDE)
        key = f"{provider}:{model}:{lang}:{digest}"     # 评语跟语言走：换语言会重新细评
        hit = cache.get(key) or (lang == "zh-CN" and (cache.get(f"{provider}:{model}:{digest}")
                                 or (cache.get(f"{model}:{digest}") if provider == "claude" else None))) or None   # 1.5 及以前的中文缓存
        if hit:
            p.ai = hit
        else:
            jobs.append((p, b64, key))
    if not jobs:
        print(t("cull.msg.ai_all_cached", n=len(items)))
        return
    call = make_caller(provider, model)
    est_in = len(jobs) * 1500
    est_out = len(jobs) * (250 if info["api"] in ("messages", "gemini") else 800)
    print(t("cull.msg.ai_jobs", n=len(jobs), label=label, cached=len(items) - len(jobs)))
    fm = lambda n: f"{n/1e6:.2f}M" if n >= 1e6 else f"{n/1e3:.0f}K"
    print("  " + t("cull.confirm.tokens", inp=fm(est_in), out=fm(est_out)))
    if not args.yes:
        confirm = getattr(args, "confirm", None)
        ok = confirm(len(jobs), est_in, est_out, label) if confirm else \
            input("  " + t("cull.msg.ai_ask")).strip().lower() == "y"
        if not ok:
            print("  " + t("cull.msg.ai_skipped"))
            return

    def run(job):
        p, b64, key = job
        exif = f"{p.camera} {p.lens} {p.exposure}".strip() or t("cull.msg.unknown", lang)
        flags = t("cull.msg.list_sep", lang).join(flag_text(f, lang) for f in p.flags) or t("cull.msg.no_issues", lang)
        d = _parse_json(call(b64, ai_prompt(exif, flags, lang)))
        d["lang"] = lang
        d["provider"], d["model"] = info["name"], model
        return p, key, d

    def save():
        cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")

    done = ok_count = 0
    _report("ai", 0, len(jobs))
    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(run, j) for j in jobs]
        for fut in cf.as_completed(futs):
            if CANCEL.is_set():
                for f in futs:
                    f.cancel()
                save()
                raise Cancelled()
            done += 1
            try:
                p, key, d = fut.result()
                p.ai = d
                cache[key] = d
                ok_count += 1
            except Exception as e:  # 单张失败不影响整体
                print("  " + t("cull.msg.ai_failed", err=f"{type(e).__name__}: {e}"))
                if ok_count == 0 and done >= 3:   # 开头连续失败：多半是 Key、模型名或余额问题，及时止损
                    for f in futs:
                        f.cancel()
                    save()
                    print("  " + t("cull.msg.ai_stop", n=done, env=info["env"]))
                    return
            _report("ai", done, len(jobs))
            if done % 10 == 0 or done == len(jobs):
                print(f"  {done}/{len(jobs)}")
                save()
