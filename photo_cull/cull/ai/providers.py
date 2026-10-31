from __future__ import annotations

import json
import os
import sys
import time

from ...i18n import t
from .. import state as _state
from ..state import CUSTOM_BASE

# ───────────────────────── AI 细评 ─────────────────────────
# 每家：显示名、环境变量、默认模型、可选模型（notes 是界面里的简短说明，对应语言包 cull.model_note.*）。
# api：messages＝Anthropic，responses＝OpenAI Responses API，chat＝OpenAI 兼容 Chat Completions，gemini＝Gemini REST。
# 模型列表核对于 2026-10：只列能看图的模型；用户也可以手动填写列表外的模型名称。
PROVIDERS = {
    "claude": {"name": "Claude", "env": "ANTHROPIC_API_KEY", "default": "claude-sonnet-5-5", "api": "messages",
               "models": ["claude-sonnet-5-5", "claude-haiku-5-5", "claude-opus-5-5", "claude-fable-5-1"],
               "notes": {"claude-sonnet-5-5": "recommended", "claude-haiku-5-5": "cheap", "claude-opus-5-5": "high",
                         "claude-fable-5-1": "top"},
               "console": "console.anthropic.com", "key_ph": "sk-ant-…"},
    "openai": {"name": "ChatGPT", "env": "OPENAI_API_KEY", "default": "gpt-6.1-sol", "api": "responses", "base_url": None,
               "models": ["gpt-6.1-sol", "gpt-6-luna", "gpt-6-astra", "gpt-5.5"],
               "notes": {"gpt-6.1-sol": "recommended", "gpt-6-luna": "cheap", "gpt-6-astra": "top", "gpt-5.5": "previous"},
               "console": "platform.openai.com", "key_ph": "sk-…"},
    "grok": {"name": "Grok", "env": "XAI_API_KEY", "default": "grok-4.7", "api": "responses", "base_url": "https://api.x.ai/v1",
             "models": ["grok-4.7"], "notes": {"grok-4.7": "recommended"}, "console": "console.x.ai", "key_ph": "xai-…"},
    "gemini": {"name": "Gemini", "env": "GEMINI_API_KEY", "alt_env": "GOOGLE_API_KEY", "default": "gemini-3.8-flash", "api": "gemini",
               "models": ["gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite", "gemini-4-argon"],
               "notes": {"gemini-3.8-flash": "recommended", "gemini-3.6-flash": "balanced", "gemini-3.5-flash-lite": "cheap",
                         "gemini-4-argon": "top"},
               "console": "aistudio.google.com", "key_ph": "AIza…"},
    # DeepSeek：只有 deepseek-flash 能看图（deepseek-v4-pro 只支持文字），见 api-docs.deepseek.com/guides/vision
    "deepseek": {"name": "DeepSeek", "env": "DEEPSEEK_API_KEY", "default": "deepseek-flash", "api": "chat",
                 "base_url": "https://api.deepseek.com", "models": ["deepseek-flash"], "notes": {"deepseek-flash": "ds_vision"},
                 "console": "platform.deepseek.com", "key_ph": "sk-…"},
    # 自定义：任意 OpenAI 兼容的视觉模型（通义千问、Kimi、豆包、OpenRouter、本地 Ollama／LM Studio 等），地址和模型名由用户填写
    "custom": {"name": "Custom", "env": "PHOTO_CULL_CUSTOM_API_KEY", "default": "", "api": "chat", "base_url": None,
               "models": [], "notes": {}, "console": "", "key_ph": "sk-…"},
}
GEMINI_BASE = os.environ.get("PHOTO_CULL_GEMINI_BASE", "https://generativelanguage.googleapis.com/v1beta")


def env_key(provider: str) -> str:
    info = PROVIDERS[provider]
    return os.environ.get(info["env"], "") or (os.environ.get(info["alt_env"], "") if info.get("alt_env") else "")


def make_caller(provider: str, model: str):
    """返回 call(b64_jpeg, prompt) -> 文本。各家统一接口。"""
    info = PROVIDERS[provider]
    key = _state.API_KEYS.get(provider) or env_key(provider)
    if not key and provider == "custom":
        key = "none"           # 本地服务（Ollama、LM Studio 等）通常不需要 Key
    if not key:
        sys.exit(t("cull.msg.no_key", env=info["env"], name=info["name"]))
    api = info["api"]
    if api == "messages":
        try:
            import anthropic
        except ImportError:
            sys.exit(t("cull.msg.need_pkg", name=info["name"], pkg="anthropic"))
        client = anthropic.Anthropic(api_key=key, max_retries=4)

        def call(b64, prompt):
            msg = client.messages.create(model=model, max_tokens=800, messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
                {"type": "text", "text": prompt}]}])
            return "".join(getattr(b, "text", "") for b in msg.content)
        return call
    if api == "gemini":
        return _gemini_caller(key, model)
    base = CUSTOM_BASE.get(provider) or info.get("base_url")
    if api == "chat":
        if not base:
            sys.exit(t("cull.err.custom_incomplete"))
        return _chat_caller(key, base, model, info["name"])
    try:
        from openai import OpenAI
    except ImportError:
        sys.exit(t("cull.msg.need_pkg", name=info["name"], pkg="openai"))
    client = OpenAI(api_key=key, base_url=base, max_retries=4)
    if api == "responses":
        def call(b64, prompt):
            # OpenAI 与 xAI 都支持 Responses API；推理模型的思考也计入输出上限，所以给足余量
            r = client.responses.create(model=model, store=False, max_output_tokens=4000, input=[{
                "role": "user", "content": [
                    {"type": "input_image", "image_url": "data:image/jpeg;base64," + b64, "detail": "high"},
                    {"type": "input_text", "text": prompt}]}])
            return r.output_text
        return call
    raise ValueError(api)


def _post_json(url: str, body: dict, headers: dict, label: str) -> dict:
    """POST JSON，遇到限流／服务端错误时退避重试（最多 4 次）。只用标准库。"""
    import urllib.error
    import urllib.request
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    delay = 2.0
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")[:300]
            if e.code in (429, 500, 502, 503, 504) and attempt < 3:
                time.sleep(delay)
                delay *= 2
                continue
            raise RuntimeError(f"{label} HTTP {e.code}: {detail}") from None
        except urllib.error.URLError as e:
            if attempt < 3:
                time.sleep(delay)
                delay *= 2
                continue
            raise RuntimeError(f"{label}: {e.reason}") from None


def _chat_caller(key: str, base: str, model: str, label: str):
    """OpenAI 兼容的 Chat Completions（DeepSeek、通义千问、Kimi、豆包、OpenRouter、Ollama、LM Studio…）。
    直接走 REST，不需要安装 openai 包。"""
    url = base.rstrip("/") + "/chat/completions"

    def call(b64, prompt):
        body = {"model": model, "max_tokens": 4000, "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b64}},
            {"type": "text", "text": prompt}]}]}
        res = _post_json(url, body, {"Authorization": "Bearer " + key}, label)
        choices = res.get("choices") or []
        if not choices:
            raise RuntimeError(f"{label}: {str(res)[:200]}")
        content = (choices[0].get("message") or {}).get("content") or ""
        if isinstance(content, list):          # 少数服务返回分段内容
            content = "".join(c.get("text", "") for c in content if isinstance(c, dict))
        return content
    return call


def _gemini_caller(key: str, model: str):
    """Gemini：直接调用 REST 接口 generateContent（无需额外安装 SDK）。"""
    import urllib.error
    import urllib.request

    def post(url, body):
        req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                     headers={"Content-Type": "application/json", "x-goog-api-key": key})
        delay = 2.0
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    return json.loads(r.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", errors="replace")[:300]
                if e.code in (429, 500, 502, 503, 504) and attempt < 3:
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise RuntimeError(f"Gemini HTTP {e.code}: {detail}") from None

    def texts(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k == "text" and isinstance(v, str):
                    yield v
                else:
                    yield from texts(v)
        elif isinstance(obj, list):
            for v in obj:
                yield from texts(v)

    def call(b64, prompt):
        body = {"contents": [{"role": "user", "parts": [
                    {"inline_data": {"mime_type": "image/jpeg", "data": b64}}, {"text": prompt}]}],
                "generationConfig": {"maxOutputTokens": 4096, "responseMimeType": "application/json"}}
        res = post(f"{GEMINI_BASE}/models/{model}:generateContent", body)
        cands = res.get("candidates") or []
        if not cands:
            reason = (res.get("promptFeedback") or {}).get("blockReason", "no candidates")
            raise RuntimeError(t("cull.msg.gemini_empty", reason=reason))
        return "".join(texts(cands[0].get("content", {})))
    return call
