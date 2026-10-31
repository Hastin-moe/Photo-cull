"""在 Mac 上把照片工具打包成「照片工具.app」：自带 Python 和全部依赖，双击就能用，不需要终端。

一般双击工具文件夹里的「打包Mac应用.command」即可；也可以在终端里：

    python3 tools/build_mac_app.py              # 打包（第一次要联网装打包工具，约 3–8 分钟）
    python3 tools/build_mac_app.py --mirror tuna
    python3 tools/build_mac_app.py --clean      # 删掉上次的打包缓存再打

结果：dist/mac/照片工具.app，以及可以发给别人的 dist/照片工具-<版本>-macOS-app.zip。
打包用单独的环境 .venv-build，不影响平时用的 .venv。完整记录写在 dist/mac/build.log。
"""
from __future__ import annotations

import argparse
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import setup_env  # noqa: E402

BUILD_VENV = ROOT / ".venv-build"
OUT = ROOT / "dist" / "mac"
WORK = ROOT / "build" / "mac"
APP = OUT / "照片工具.app"
LOG = OUT / "build.log"
EXTRA = ["pyinstaller>=6.6", "pywebview>=5.0"]


def pick_python() -> str:
    """打包用哪个 Python：优先 python.org／Homebrew 装的新版本（最稳），没有再用当前这个。"""
    cands = []
    for v in ("3.13", "3.12", "3.11", "3.10"):
        cands += [f"/Library/Frameworks/Python.framework/Versions/{v}/bin/python{v}",
                  f"/opt/homebrew/bin/python{v}", f"/usr/local/bin/python{v}"]
    for c in cands:
        if Path(c).is_file() and os.access(c, os.X_OK):
            return c
    # 不用虚拟环境里的 python 去建另一个虚拟环境（会串成一条链，文件夹一挪就全断）：找它背后真正的 Python
    for c in (Path(sys.base_prefix) / "bin" / f"python{sys.version_info[0]}.{sys.version_info[1]}",
              Path(sys.base_prefix) / "bin" / "python3"):
        if c.is_file() and os.access(c, os.X_OK):
            return str(c)
    return str(Path(sys.executable).resolve())


def version() -> str:
    return re.search(r'^VERSION = "([^"]+)"', (ROOT / "photo_cull" / "version.py").read_text(encoding="utf-8"), re.M).group(1)


class Tee:
    def __init__(self, f):
        self.f = f

    def write(self, s):
        sys.__stdout__.write(s)
        self.f.write(s)
        return len(s)

    def flush(self):
        sys.__stdout__.flush()
        self.f.flush()


def run(cmd, **kw) -> int:
    print("  $ " + " ".join(str(c) for c in cmd), flush=True)
    p = subprocess.Popen([str(c) for c in cmd], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, **kw)
    for line in p.stdout:
        sys.stdout.write("    " + line)
    return p.wait()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="打包 Mac 应用「照片工具.app」")
    ap.add_argument("--mirror", default="auto", help="pip 源：auto（默认）、tuna、aliyun、ustc、pypi 或网址")
    ap.add_argument("--clean", action="store_true", help="删掉上次的打包缓存（build/mac）和打包环境再打")
    a = ap.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    sys.stdout = Tee(open(LOG, "w", encoding="utf-8"))
    t0 = time.time()
    print(f"照片工具 {version()} · 打包 Mac 应用（{platform.mac_ver()[0] or platform.system()} {platform.machine()}，"
          f"Python {platform.python_version()}）\n", flush=True)
    if sys.platform != "darwin":
        print("只能在 macOS 上打包。")
        return 2
    if a.clean:
        shutil.rmtree(WORK, ignore_errors=True)
        shutil.rmtree(BUILD_VENV, ignore_errors=True)

    py = setup_env.venv_python(BUILD_VENV)
    if BUILD_VENV.exists() and not py.exists():
        # 虚拟环境不能挪位置：项目文件夹移动过以后，里面的 python 还指着旧路径，直接重建
        print("  打包环境 .venv-build 已失效（项目文件夹移动过？），删掉重建", flush=True)
        shutil.rmtree(BUILD_VENV, ignore_errors=True)
    if not py.exists():
        print("① 创建打包环境 .venv-build", flush=True)
        base = pick_python()
        print(f"  用 {base}", flush=True)
        if run([base, "-m", "venv", "--clear", BUILD_VENV]) != 0:
            print("创建打包环境失败。")
            return 1
    extra = setup_env.pip_args(setup_env.pick_mirror(a.mirror), None)
    print("\n② 安装依赖和打包工具（PyInstaller、pywebview）", flush=True)
    run([py, "-m", "pip", "install", "--upgrade", "pip", "--disable-pip-version-check", "-q"] + extra)
    if run([py, "-m", "pip", "install", "-r", ROOT / "requirements.txt", *EXTRA, "--disable-pip-version-check"] + extra) != 0:
        print("\n安装失败：检查网络后重试，或加 --mirror tuna 用国内镜像。")
        return 1

    print("\n③ 打包（约 1–3 分钟）", flush=True)
    if APP.exists():
        shutil.rmtree(APP)
    code = run([py, "-m", "PyInstaller", ROOT / "packaging" / "photo-cull.spec", "--noconfirm",
                "--distpath", OUT, "--workpath", WORK], cwd=ROOT)
    if code != 0 or not APP.is_dir():
        print("\n打包失败，请把 dist/mac/build.log 发回来。")
        return 1
    leftover = OUT / "PhotoCull"                 # COLLECT 的中间产物，.app 里已经有一份
    if leftover.is_dir():
        shutil.rmtree(leftover)

    print("\n④ 自检（启动打包好的程序，检查依赖、资源和两个服务）", flush=True)
    exe = APP / "Contents" / "MacOS" / "PhotoCull"
    env = dict(os.environ, PHOTO_CULL_CONSOLE="1")
    if run([exe, "--selftest"], env=env) != 0:
        print("\n自检没有通过，请把 dist/mac/build.log 发回来。")
        return 1

    print("\n⑤ 生成可以分发的压缩包", flush=True)
    zip_path = ROOT / "dist" / f"照片工具-{version()}-macOS-app.zip"
    if zip_path.exists():
        zip_path.unlink()
    run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", APP, zip_path])
    size = sum(f.stat().st_size for f in APP.rglob("*") if f.is_file()) / 1e6
    print(f"\n完成，用时 {time.time() - t0:.0f} 秒。")
    print(f"  应用：{APP}（约 {size:.0f} MB）")
    print(f"  压缩包：{zip_path}")
    print("把「照片工具.app」拖到「应用程序」文件夹，以后从启动台或程序坞打开即可。")
    subprocess.call(["open", "-R", str(APP)])
    return 0


if __name__ == "__main__":
    sys.exit(main())
