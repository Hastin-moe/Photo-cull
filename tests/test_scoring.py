"""评分规则：10 分制、本地最高 6 分、AI 给 6 分以上、XMP 折算、连拍瞬间、精选线、旧结果转换。"""
from _util import run

from photo_cull.cull import scoring
from photo_cull.cull.model import Photo, _upgrade_v1, label_for, photos_from_json, shown, xmp_stars


def P(name, **kw):
    base = dict(path="/x/" + name, name=name, kind="image", blur=0.3, mean_luma=118, time=0.0)
    base.update(kw)
    return Photo(**base)


def test_xmp_stars_floor():
    assert [xmp_stars(s) for s in (0, 1.9, 2.0, 5.9, 6.0, 7.9, 8.0, 9.9, 10.0)] == [0, 0, 1, 2, 3, 3, 4, 4, 5]
    assert xmp_stars(8.0, rejected=True) == -1
    assert label_for(xmp_stars(8.5)) == "Green" and label_for(xmp_stars(6.5)) == "Yellow" and label_for(-1) == "Red"


def test_shown_hides_decimal():
    assert shown(7.9) == 7 and shown(8.0) == 8 and shown(5.99) == 6 and shown(0.0) == 0


def test_local_max_six():
    ps = [P(f"a{i}.jpg", blur=0.1 + i * 0.05, group=i + 1) for i in range(6)]
    scoring.score_local(ps)
    scoring.finalize(ps)
    assert all(1.0 <= p.local_score <= 6.0 for p in ps)
    assert max(p.score for p in ps) <= 6.0
    best = max(ps, key=lambda p: p.local_score)
    assert best.name == "a0.jpg" and best.local_score == 6.0


def test_reject_and_soft():
    ps = [P("ok.jpg", blur=0.2, group=1), P("soft.jpg", blur=0.6, group=2), P("bad.jpg", blur=0.9, group=3),
          P("dark.jpg", blur=0.2, mean_luma=10, group=4)]
    scoring.score_local(ps)
    scoring.finalize(ps)
    d = {p.name: p for p in ps}
    assert d["bad.jpg"].category == "reject" and d["bad.jpg"].stars == -1
    assert d["dark.jpg"].category == "reject"
    assert "soft" in d["soft.jpg"].flags and d["soft.jpg"].local_score <= scoring.SOFT_CAP


def test_ai_scores_above_six():
    ps = [P("a.jpg", group=1), P("b.jpg", group=2, blur=0.25)]
    scoring.score_local(ps)
    ps[0].ai = {"overall": 8.7}
    ps[1].ai = {"overall": 4.2}
    scoring.finalize(ps)
    assert ps[0].score == 8.7 and ps[0].category == "pick" and ps[0].stars == 4
    assert ps[1].score == 4.2 and ps[1].category == "usable" and ps[1].stars == 2


def test_pick_lines():
    a = P("a.jpg", group=1)
    scoring.score_local([a])
    scoring.finalize([a])
    assert a.score == 6.0 and a.category == "pick"           # 本地精选线 5.0
    args = type("A", (), {"pick_local": 6.5})()
    scoring.finalize([a], args)
    assert a.category == "usable"
    a.ai = {"overall": 6.9}
    scoring.finalize([a])
    assert a.category == "usable"                              # AI 精选线 7.0
    a.ai = {"overall": 7.0}
    scoring.finalize([a])
    assert a.category == "pick"


def test_burst_moment_by_highlight():
    # 同一组 3 张：中间那张最清晰、睁眼、笑
    ps = [P("b1.jpg", group=1, group_size=3, blur=0.40, faces=1, eyes_missing=1, face_area=0.05, time=1),
          P("b2.jpg", group=1, group_size=3, blur=0.30, faces=1, smiles=1, face_area=0.06, time=2),
          P("b3.jpg", group=1, group_size=3, blur=0.35, faces=1, face_area=0.05, time=3)]
    scoring.score_local(ps)
    scoring.finalize(ps)
    d = {p.name: p for p in ps}
    assert d["b2.jpg"].group_best and d["b2.jpg"].category == "moment"
    assert d["b1.jpg"].category == "usable" and d["b3.jpg"].category == "usable"
    assert d["b2.jpg"].highlight > d["b3.jpg"].highlight > d["b1.jpg"].highlight
    # 没选中的帧即使 AI 给了高分也封顶 4.9（2★）
    d["b3.jpg"].ai = {"overall": 9.0}
    scoring.finalize(ps)
    assert d["b3.jpg"].score <= scoring.ALT_CAP or d["b3.jpg"].group_best


def test_burst_ai_changes_choice():
    ps = [P("b1.jpg", group=1, group_size=2, blur=0.30, time=1), P("b2.jpg", group=1, group_size=2, blur=0.32, time=2)]
    scoring.score_local(ps)
    assert ps[0].group_best
    ps[0].ai, ps[1].ai = {"overall": 5.0}, {"overall": 9.0}    # 两张都细评过：AI 分占 60%
    scoring.finalize(ps)
    assert ps[1].group_best and ps[1].category == "moment" and ps[1].score == 9.0
    assert ps[0].category == "usable"


def test_weights():
    w = scoring.parse_weights("sharp=1, eyes=0")
    assert w["sharp"] == 1 and w["eyes"] == 0 and w["smile"] == scoring.HIGHLIGHT_WEIGHTS["smile"]
    assert scoring.parse_weights("sharp=0,eyes=0,smile=0,exposure=0,subject=0") == scoring.HIGHLIGHT_WEIGHTS
    # 只看笑容时，笑的那张胜出（即使不是最清晰）
    ps = [P("s1.jpg", group=1, group_size=2, blur=0.2, faces=1), P("s2.jpg", group=1, group_size=2, blur=0.4, faces=1, smiles=1)]
    scoring.score_local(ps, type("A", (), {"weights": {"smile": 1.0}})())
    assert ps[1].group_best


def test_manual():
    a = P("a.jpg", group=1)
    scoring.score_local([a])
    scoring.finalize([a])
    scoring.set_manual(a, 9)
    assert a.manual and a.score == 9 and a.stars == 4 and a.category == "pick"
    scoring.set_manual(a, -1)
    assert a.category == "reject" and a.stars == -1
    scoring.set_manual(a, 3)
    assert a.category == "usable" and a.stars == 1
    scoring.finalize([a])                      # 手动分数在重新定分时保留
    assert a.score == 3


def test_upgrade_v1():
    rows = [{"path": "/a", "name": "a", "kind": "image", "tier": "candidate", "stars": 4, "local_score": 80,
             "ai": {"overall": 8, "stars": 4}},
            {"path": "/b", "name": "b", "kind": "image", "tier": "alt", "stars": 2, "local_score": 50, "group_size": 3},
            {"path": "/c", "name": "c", "kind": "image", "tier": "reject", "stars": -1, "local_score": 10},
            {"path": "/d", "name": "d", "kind": "image", "tier": "candidate", "stars": 3, "local_score": 60, "group_size": 2},
            {"path": "/e", "name": "e", "kind": "image", "tier": "error", "stars": 0}]
    ps, schema = photos_from_json(rows)
    d = {p.name: p for p in ps}
    assert schema == 1
    assert d["a"].score == 8.0 and d["a"].category == "pick" and d["a"].stars == 4 and d["a"].local_score == 5.0
    assert d["b"].category == "usable" and d["c"].category == "reject" and d["c"].stars == -1
    assert d["d"].category == "moment" and d["e"].category == "error"
    assert _upgrade_v1({"tier": "candidate", "stars": 5, "manual": True, "ai": {"overall": 6}})["score"] == 10.0


if __name__ == "__main__":
    run(globals())
