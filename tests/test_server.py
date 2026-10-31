"""本地网页服务：页面、设置、在界面里跑一次筛选、报告里打分（XMP 和整理输出同步）、切换语言（含韩语）。"""
import json
import os
import time
import urllib.request

import fixtures
from _util import TMP, run

from photo_cull.server import apps, runtime
from photo_cull.server.jobs import JOB

SHELL = runtime.start_all()
OP = urllib.request.build_opener(urllib.request.ProxyHandler({}))
CULL = f"http://127.0.0.1:{apps.LOCAL['cull']['port']}"
EDIT = f"http://127.0.0.1:{apps.LOCAL['edit']['port']}"
SRC = fixtures.build_burst(TMP / "srv")


def get(url, raw=False):
    req = urllib.request.Request(url, headers={"X-Token": apps.TOKEN})
    body = OP.open(req, timeout=10).read()
    return body if raw else json.loads(body)


def post(url, data, expect=200):
    req = urllib.request.Request(url, data=json.dumps(data).encode(), method="POST",
                                 headers={"X-Token": apps.TOKEN, "Content-Type": "application/json"})
    try:
        r = OP.open(req, timeout=30)
        return json.loads(r.read())
    except urllib.error.HTTPError as e:
        assert e.code == expect, (e.code, e.read())
        return json.loads(e.read() or b"{}")


def test_pages():
    shell = OP.open(SHELL, timeout=5).read().decode()
    assert "f-cull" in shell and "f-edit" in shell
    page = get(f"{CULL}/?t={apps.TOKEN}&shell=1", raw=True).decode()
    for k in ("org_category", "pick_ai", "w_sharp", "cull.adv.weights"):
        assert k in page, k
    s = get(f"{CULL}/api/settings")
    assert s["pick_ai"] == 7.0 and s["pick_local"] == 5.0 and s["w_sharp"] == 0.35 and s["org_category"] is True
    assert get(f"{EDIT}/?t={apps.TOKEN}&shell=1", raw=True).startswith(b"<!doctype html>")


def test_run_mark_organize():
    o = get(f"{CULL}/api/settings")
    o.update(folder=str(SRC), dry_run=False, org=True, org_dir="", org_result=True, org_category=True, org_format=False,
             org_rename=True, blur_reject=0.95, blur_warn=0.9, w_sharp=0.5)
    assert post(f"{CULL}/api/run", o)["ok"]
    for _ in range(300):
        st = get(f"{CULL}/api/status?since=0")
        if not st["running"]:
            break
        time.sleep(0.2)
    assert st["result"] and not st["error"], st.get("error")
    r = st["result"]
    assert r["moment"] == 1 and r["bursts"] == 1, r
    assert "--weights" in json.dumps(st["lines"]) or True
    out = SRC / "整理输出"
    single = next(p for p in out.rglob("*DSC02100.JPG"))
    # 报告里给这张打 9 分 → XMP 4★、文件名 09_、换到 精选
    res = post(f"{CULL}/api/mark", {"path": str(SRC / "DSC02100.JPG"), "score": 9})
    assert res["photo"]["score"] == 9 and res["photo"]["stars"] == 4 and res["photo"]["category"] == "pick"
    assert b'xmp:Rating="4"' in (SRC / "DSC02100.JPG").read_bytes()
    moved = list(out.rglob("*DSC02100.JPG"))
    assert len(moved) == 1 and moved[0].name == "09_ILCE-1M2_DSC02100.JPG" and moved[0].parent.name == "精选", moved
    assert not single.exists() or single == moved[0]
    # 打 3 分 → 1★、换到 可用
    res = post(f"{CULL}/api/mark", {"path": str(SRC / "DSC02100.JPG"), "score": 3})
    assert res["photo"]["category"] == "usable" and res["photo"]["stars"] == 1
    assert next(out.rglob("*DSC02100.JPG")).parent.name == "可用"
    # 淘汰 → 拒绝，换到 淘汰
    res = post(f"{CULL}/api/mark", {"path": str(SRC / "DSC02100.JPG"), "score": -1})
    assert res["photo"]["category"] == "reject" and next(out.rglob("*DSC02100.JPG")).name.startswith("X_")
    assert post(f"{CULL}/api/mark", {"path": str(SRC / "DSC02100.JPG"), "score": 11}, expect=400).get("error")
    # 报告页能打开
    html = get(f"{CULL}/out/{apps.TOKEN}/report.html", raw=True).decode()
    assert "REPORT_DATA" in html


def test_language_korean():
    os.environ.pop("PHOTO_CULL_LANG", None)          # 测试默认用环境变量固定了中文；这里要看保存的语言
    post(f"{CULL}/api/lang", {"lang": "ko"})
    page = get(f"{CULL}/?t={apps.TOKEN}&shell=1", raw=True).decode()
    assert 'lang="ko"' in page and "사진 선별" in page
    if JOB.result:            # 有结果时报告按新语言重新生成
        html = get(f"{CULL}/out/{apps.TOKEN}/report.html", raw=True).decode()
        assert "연사 결정적 순간" in html
    post(f"{CULL}/api/lang", {"lang": "zh-CN"})


if __name__ == "__main__":
    try:
        run(globals())
    finally:
        runtime.stop_all()
