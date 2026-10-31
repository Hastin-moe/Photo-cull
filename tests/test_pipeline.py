"""完整筛选流程（命令行）：配对、XMP、整理输出的文件夹结构、重命名、再次整理、旧结果、手动分数沿用。"""
import json
import re
import shutil

import fixtures
from _util import TMP, after_sos, quiet, run

from photo_cull.cull import cli
from photo_cull.cull.report import load_results


def _run(folder, *extra):
    res, log = quiet(cli.main, [str(folder), *extra])
    return res, log


def test_basic_folder():
    d = fixtures.build(TMP / "basic")
    before = {p.name: after_sos(p.read_bytes()) for p in d.glob("*.JPG")}
    res, log = _run(d, "--organize", "--by-result", "--by-category", "--by-format", "--rename")
    assert res["total"] == 7 and res["pairs"] == 1, res
    assert res["reject"] == 2, res                      # 一张严重模糊＋一张过曝（另一张只是「可能失焦」）
    data = json.loads((d / "photo-cull-report" / "results.json").read_text(encoding="utf-8"))
    assert data["schema"] == 2 and data["version"].startswith("1.8")
    for p in data["photos"]:
        assert p["category"] in ("pick", "moment", "usable", "reject")
        assert p["score"] <= 6.0                          # 没开 AI：最高 6 分
    # 画面数据没被改动；RAF 写了边车，配对的 JPG 写了内嵌 XMP
    assert {p.name: after_sos(p.read_bytes()) for p in d.glob("*.JPG")} == before
    assert (d / "DSCF0003.xmp").is_file() and b"xmp:Rating" in (d / "DSCF0003.JPG").read_bytes()
    out = d / "整理输出"
    files = sorted(str(p.relative_to(out)) for p in out.rglob("*") if p.is_file() and not p.name.startswith("."))
    assert any(f.startswith("保留/精选/") or f.startswith("保留/可用/") for f in files), files
    assert all(re.match(r"^(保留/(精选|可用|连拍瞬间/[^/]+)|淘汰)/(JPEG|RAW)/(X|\d\d)_", f) for f in files if not f.endswith(".xmp")), files
    assert any(f.startswith("淘汰/") and "/X_" in f for f in files)
    # 配对的 RAF 和 JPG 在同一个分类里、同一个名字
    pair = [f for f in files if "DSCF0003" in f and not f.endswith(".xmp")]
    assert len(pair) == 2 and {p.split("/")[-1].rsplit(".", 1)[0] for p in pair} == {pair[0].split("/")[-1].rsplit(".", 1)[0]}


def test_burst_folder():
    d = TMP / "burst"
    fixtures.build_burst(d)
    res, _ = _run(d, "--organize", "--by-result", "--by-category", "--rename", "--blur-reject", "0.95", "--blur-warn", "0.9")
    assert res["bursts"] == 1 and res["moment"] == 1, res
    photos, meta = load_results(d / "photo-cull-report")
    burst = [p for p in photos if p.group_size == 4]
    best = [p for p in burst if p.group_best]
    assert len(best) == 1 and best[0].name == "DSC02002.JPG"      # 最清晰的那张
    assert best[0].category == "moment" and all(p.category == "usable" for p in burst if not p.group_best)
    moment_dirs = list((d / "整理输出" / "保留" / "连拍瞬间").iterdir())
    assert len(moment_dirs) == 1 and moment_dirs[0].name.startswith("连拍001_")
    assert [f.name.split("_", 2)[-1] for f in moment_dirs[0].iterdir()] == ["DSC02002.JPG"]
    assert meta["organized"]["dirs"]["moment"] == "连拍瞬间"
    assert meta["scoring"]["pick_local"] == 5.0


def test_rerun_keeps_manual_and_moves_copy():
    d = TMP / "rerun"
    fixtures.build_burst(d)
    _run(d, "--organize", "--by-result", "--by-category", "--rename", "--blur-reject", "0.95", "--blur-warn", "0.9")
    out = d / "photo-cull-report"
    data = json.loads((out / "results.json").read_text(encoding="utf-8"))
    for p in data["photos"]:
        if p["name"] == "DSC02100.JPG":
            p["score"], p["manual"] = 9.0, True
    (out / "results.json").write_text(json.dumps(data), encoding="utf-8")
    res, log = _run(d, "--organize", "--by-result", "--by-category", "--rename", "--blur-reject", "0.95", "--blur-warn", "0.9")
    assert "手动" in log
    photos, _ = load_results(out)
    p = next(x for x in photos if x.name == "DSC02100.JPG")
    assert p.manual and p.score == 9.0 and p.stars == 4 and p.category == "pick"
    picks = [f.name for f in (d / "整理输出" / "保留" / "精选").rglob("*.JPG")]
    assert "09_ILCE-1M2_DSC02100.JPG" in picks, picks
    assert len(list((d / "整理输出").rglob("*DSC02100.JPG"))) == 1        # 旧副本被换掉，没多出一份


def test_old_results_upgrade():
    d = TMP / "old"
    fixtures.build(d)
    _run(d, "--dry-run")
    out = d / "photo-cull-report"
    data = json.loads((out / "results.json").read_text(encoding="utf-8"))
    v1 = []
    for p in data["photos"]:                     # 造一份 1.7.1 格式的结果
        p = dict(p)
        cat = p.pop("category")
        for k in ("score", "highlight", "smiles", "face_area"):
            p.pop(k, None)
        p["tier"] = {"pick": "candidate", "moment": "candidate", "usable": "candidate"}.get(cat, cat)
        p["stars"] = -1 if cat == "reject" else 3
        p["local_score"] = 70.0
        v1.append(p)
    (out / "results.json").write_text(json.dumps(v1), encoding="utf-8")
    photos, meta = load_results(out)
    assert meta.get("upgraded_from") == 1
    assert all(p.category in ("pick", "usable", "moment", "reject", "error") for p in photos)
    assert all(p.score == 6.0 for p in photos if p.category != "reject")


def test_report_page():
    d = TMP / "basic"
    html = (d / "photo-cull-report" / "report.html").read_text(encoding="utf-8")
    assert "window.REPORT_DATA" in html and '"category"' in html and "cat.moment" in html
    assert "__" not in re.sub(r"__\w+__(?=[^<]*</script>)", "", html[:200])
    csv = (d / "photo-cull-report" / "results.csv").read_text(encoding="utf-8-sig")
    assert csv.splitlines()[0].startswith("文件,配对文件,结果,分数,XMP 星级")


def test_english_folders():
    d = TMP / "en"
    fixtures.build_burst(d)
    _run(d, "--lang", "en", "--organize", "--by-result", "--by-category", "--blur-reject", "0.95", "--blur-warn", "0.9")
    out = d / "Organized" if (d / "Organized").exists() else next(x for x in d.iterdir() if x.is_dir() and x.name != "photo-cull-report")
    assert (out / "Kept" / "Burst moments").is_dir(), list(out.rglob("*"))
    shutil.rmtree(d)


if __name__ == "__main__":
    run(globals())
