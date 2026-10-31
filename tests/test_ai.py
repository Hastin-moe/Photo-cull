"""AI 细评（用本机假接口，不花钱）：OpenAI 兼容接口和 Gemini 的请求格式、10 分制总分、6 分以上只由 AI 给、
评语语言（含韩语）、缓存按语言区分。"""
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import fixtures
from _util import TMP, quiet, run

LOG = []
SCORE = {"value": 8.6}


def _answer(prompt):
    lang = "ko" if "한국어" in prompt else "ja" if "日本語" in prompt else "en" if "in English" in prompt else "zh"
    comment = {"ko": "빛을 훌륭하게 썼습니다", "ja": "光の使い方が見事です", "en": "Lovely use of light", "zh": "光线运用出色"}[lang]
    return {"genre": "street", "scores": {"composition": 7, "light": 8, "subject": 7, "moment": 6, "technical": 8},
            "overall": SCORE["value"], "keep": True, "comment": comment, "issues": ["x"]}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        LOG.append({"path": self.path, "auth": self.headers.get("Authorization") or self.headers.get("x-goog-api-key"),
                    "body": body})
        if "generateContent" in self.path:
            prompt = body["contents"][0]["parts"][-1]["text"] if "text" in body["contents"][0]["parts"][-1] \
                else json.dumps(body, ensure_ascii=False)
            txt = json.dumps(_answer(prompt), ensure_ascii=False)
            data = {"candidates": [{"content": {"parts": [{"text": txt}]}}]}
        else:
            prompt = body["messages"][0]["content"][1]["text"]
            data = {"choices": [{"message": {"role": "assistant",
                                             "content": "```json\n" + json.dumps(_answer(prompt), ensure_ascii=False) + "\n```"}}]}
        out = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)


srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_address[1]}"
for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
    os.environ.pop(k, None)
os.environ["NO_PROXY"] = "127.0.0.1,localhost"
os.environ["PHOTO_CULL_CUSTOM_API_KEY"] = "k-custom"
os.environ["GEMINI_API_KEY"] = "k-gem"

from photo_cull.cull import cli  # noqa: E402
from photo_cull.cull.ai import providers  # noqa: E402
from photo_cull.cull.ai.prompts import AI_PROMPTS, _parse_json  # noqa: E402
from photo_cull.cull.report import load_results  # noqa: E402

SRC = fixtures.build_burst(TMP / "ai")


def _cull(*args):
    return quiet(cli.main, [str(SRC), "--dry-run", "--yes", "--ai", "--blur-reject", "0.95", "--blur-warn", "0.9", *args])[0]


def test_custom_endpoint_scores_above_six():
    LOG.clear()
    res = _cull("--provider", "custom", "--model", "qwen-vl-max", "--base-url", BASE + "/v1", "--lang", "en")
    assert LOG and all(x["path"] == "/v1/chat/completions" for x in LOG)
    b = LOG[0]["body"]
    assert b["model"] == "qwen-vl-max" and LOG[0]["auth"] == "Bearer k-custom"
    assert b["messages"][0]["content"][0]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert "1.0 to 10.0" in b["messages"][0]["content"][1]["text"]
    # 只评每组选中的那张和单张：4 张连拍＋2 张单张 → 3 次
    assert len(LOG) == 3, len(LOG)
    photos, _ = load_results(SRC / "photo-cull-report")
    reviewed = [p for p in photos if p.ai]
    assert reviewed and all(p.score == 8.6 and p.stars == 4 for p in reviewed)
    assert all(p.ai["lang"] == "en" and p.ai["comment"] == "Lovely use of light" for p in reviewed)
    assert {p.category for p in reviewed} == {"pick", "moment"} and res["pick"] == 2 and res["moment"] == 1
    assert all(p.score <= 4.9 for p in photos if p.group_size > 1 and not p.group_best)


def test_cache_by_language():
    n0 = len(LOG)
    _cull("--provider", "custom", "--model", "qwen-vl-max", "--base-url", BASE + "/v1", "--lang", "en")
    assert len(LOG) == n0                                   # 同语言：全部命中缓存
    _cull("--provider", "custom", "--model", "qwen-vl-max", "--base-url", BASE + "/v1", "--lang", "ko")
    assert len(LOG) == n0 + 3 and "한국어" in LOG[-1]["body"]["messages"][0]["content"][1]["text"]
    photos, _ = load_results(SRC / "photo-cull-report")
    assert any((p.ai or {}).get("comment") == "빛을 훌륭하게 썼습니다" for p in photos)


def test_gemini():
    providers.GEMINI_BASE = BASE + "/v1beta"
    LOG.clear()
    SCORE["value"] = 6.4
    _cull("--provider", "gemini", "--model", "gemini-test", "--lang", "zh-CN")
    assert LOG and all("gemini-test:generateContent" in x["path"] and x["auth"] == "k-gem" for x in LOG)
    photos, _ = load_results(SRC / "photo-cull-report")
    singles = [p for p in photos if p.group_size == 1]
    assert all(p.score == 6.4 and p.category == "usable" and p.stars == 3 for p in singles)   # 6.4 < 精选线 7


def test_parse():
    assert _parse_json('{"overall": 7.46, "genre": "扫街"}') == {"overall": 7.5, "genre": "street"}
    for bad in ('{"overall": 0}', '{"overall": 11}', '{"stars": 4}'):
        try:
            _parse_json(bad)
        except ValueError:
            continue
        raise AssertionError(bad)
    assert set(AI_PROMPTS) == {"zh-CN", "en", "ja", "ko"}
    assert all("{exif}" in p and "{flags}" in p and '"overall":0.0' in p for p in AI_PROMPTS.values())


if __name__ == "__main__":
    try:
        run(globals())
    finally:
        srv.shutdown()
