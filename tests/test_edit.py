"""照片编辑：解码、渲染、内置 LUT、用户 LUT、自动调整、编辑记录、导出（原文件不变）。"""
import hashlib

import numpy as np

import fixtures
from _util import TMP, run

from photo_cull.edit import auto, decode, export, library, params, records, refs, render, styles

SRC = fixtures.build(TMP / "edit")
JPG = SRC / "DSC01234.JPG"
CUBE = "TITLE \"t\"\nLUT_3D_SIZE 2\n" + "\n".join(f"{r} {g} {b}" for b in (0, 1) for g in (0, 1) for r in (0, 1)) + "\n"


def test_decode_render():
    lin, info = decode.decode(str(JPG))
    assert lin.size and info
    P = params.normalize_params(None)
    out = render.render(lin, info, P)
    assert out.dtype == np.float32 and 0 <= float(out.min()) and float(out.max()) <= 1.0
    P2 = params.normalize_params({"exposure": 1.0})
    assert float(render.render(lin, info, P2).mean()) > float(out.mean())


def test_builtin_lut():
    cubes = sorted(refs.LUT_DIR.rglob("*.cube"))
    assert len(cubes) >= 39
    ref = refs.style_ref(str(cubes[0]))
    assert ref.startswith(refs.BUILTIN) and refs.resolve_style(ref) == str(cubes[0])
    lin, info = decode.decode(str(JPG))
    base = render.render(lin, info, params.normalize_params(None))
    look = render.render(lin, info, params.normalize_params({"lut": {"path": ref, "amount": 1.0}}))
    assert np.abs(look - base).mean() > 0.003


def test_user_lut():
    r = styles.add_user_lut("my.cube", CUBE)
    assert r["path"].startswith(refs.USER) and r["size"] == 2
    assert any(x["path"] == r["path"] for x in styles.user_lut_items())
    styles.remove_user_lut(r["path"])
    assert not any(x["path"] == r["path"] for x in styles.user_lut_items())


def test_auto_and_records():
    lin, info = decode.decode(str(JPG))
    a = auto.auto_adjust(lin, info, params.normalize_params(None))
    assert "exposure" in a["set"] and a["style_id"] == auto.DEFAULT_METER
    records.save_edit(str(JPG), params.normalize_params({"exposure": 0.5}))
    assert records.has_edit(str(JPG)) and records.load_edit(str(JPG))["exposure"] == 0.5
    items = library.list_folder(str(SRC))
    assert any(i.get("edited") for i in items)


def test_export_keeps_original():
    before = hashlib.sha1(JPG.read_bytes()).hexdigest()
    out = export.export(str(JPG), params.normalize_params({"contrast": 20}), long_edge=800)
    assert out and __import__("os").path.getsize(out) > 1000
    from PIL import Image
    assert max(Image.open(out).size) == 800
    assert hashlib.sha1(JPG.read_bytes()).hexdigest() == before
    assert library.thumbnail(str(JPG))[:2] == b"\xff\xd8"


if __name__ == "__main__":
    run(globals())
