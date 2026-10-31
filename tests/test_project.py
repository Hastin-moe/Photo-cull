"""项目整体：语言包一致（含韩语）、所有模块能导入、入口文件、打包清单里有新包、版本号只有一个出处。"""
import importlib
import pkgutil
import subprocess
import sys
import zipfile

from _util import ROOT, run

import photo_cull
from photo_cull import i18n
from photo_cull.version import VERSION


def test_i18n_consistent():
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "check_i18n.py")], capture_output=True, text=True)
    assert r.returncode == 0 and "没有问题" in r.stdout, r.stdout + r.stderr
    assert list(i18n.LANGS) == ["zh-CN", "en", "ja", "ko"]
    assert i18n.normalize("ko_KR.UTF-8") == "ko" and i18n.t("cat.moment", "ko") == "연사 결정적 순간"


def test_all_modules_import():
    for m in pkgutil.walk_packages(photo_cull.__path__, "photo_cull."):
        if not m.name.endswith("__main__"):
            importlib.import_module(m.name)


def test_boundaries():
    """筛选和编辑互不导入；共用的在 imaging。"""
    import re
    for pkg, other in (("cull", "edit"), ("edit", "cull")):
        for f in (ROOT / "photo_cull" / pkg).rglob("*.py"):
            src = f.read_text(encoding="utf-8")
            assert not re.search(rf"from \.+{other}\b|photo_cull\.{other}\b", src), f"{f} 导入了 {other}"


def test_entry_points():
    for args in (["cull.py", "--version"], ["-m", "photo_cull.cull", "--version"]):
        r = subprocess.run([sys.executable, *args], cwd=ROOT, capture_output=True, text=True)
        assert r.returncode == 0 and VERSION in r.stdout, (args, r.stdout, r.stderr)
    r = subprocess.run([sys.executable, "gui.py", "--help"], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0 and "--app" in r.stdout


def test_version_single_source():
    assert VERSION == "1.8-beta"
    hits = subprocess.run(["git", "grep", "-n", "-E", r'^VERSION = "', "--", "*.py"], cwd=ROOT, capture_output=True, text=True).stdout
    assert hits.strip().splitlines() == [f'photo_cull/version.py:2:VERSION = "{VERSION}"'], hits


def test_release_zip():
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "make_release.py")], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    z = next((ROOT / "dist").glob(f"*{VERSION}*mac*.zip"), None) or next((ROOT / "dist").glob(f"*{VERSION}*.zip"))
    names = zipfile.ZipFile(z).namelist()
    for need in ("photo_cull/cull/scoring.py", "photo_cull/server/handler.py", "locales/ko.json", "cull.py", "gui.py"):
        assert any(n.endswith(need) for n in names), need
    assert not any("__pycache__" in n for n in names)


if __name__ == "__main__":
    run(globals())
