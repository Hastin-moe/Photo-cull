"""照片工具：部署／修复运行环境（macOS、Windows、Linux 通用，只用 Python 标准库）。

一般不用直接运行它：双击「安装环境」或启动文件时会自动调用。手动用法（在工具文件夹里）：

    python3 tools/setup_env.py                 # 准备环境（已经装好且没变化时直接跳过）
    python3 tools/setup_env.py --check         # 只检查，不安装
    python3 tools/setup_env.py --recreate      # 删掉旧环境重新装（环境坏了时用）
    python3 tools/setup_env.py --mirror tuna   # 用清华镜像（auto＝连不上 PyPI 时自动切换，默认）
    python3 tools/setup_env.py --wheels 离线包   # 从本地文件夹离线安装，不联网

离线部署（在能联网的电脑上先下载好，拷到新电脑后用 --wheels 安装）：

    python3 tools/setup_env.py --download 离线包 --target win     # 给 64 位 Windows 下载
    python3 tools/setup_env.py --download 离线包 --target mac-arm # 给 Apple 芯片的 Mac 下载
"""
from __future__ import annotations

import argparse
import hashlib
import os
import platform
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQ = ROOT / "requirements.txt"
MIN_PY = (3, 9)
IS_WIN = os.name == "nt"
VENV = ROOT / (".venv-win" if IS_WIN else ".venv")
MIRRORS = {
    "tuna": "https://pypi.tuna.tsinghua.edu.cn/simple",
    "aliyun": "https://mirrors.aliyun.com/pypi/simple/",
    "ustc": "https://pypi.mirrors.ustc.edu.cn/simple",
    "pypi": "https://pypi.org/simple",
}
# 导入名 → 用途；安装后逐个检查能否真正导入（装上了但导入失败，往往是系统或芯片不支持）
MODULES = [
    ("numpy", "数值计算", True),
    ("PIL", "图片读写（Pillow）", True),
    ("cv2", "图像分析（OpenCV）", True),
    ("rawpy", "RAW 解码（LibRaw）", True),
    ("exifread", "EXIF 读取", True),
    ("pillow_heif", "HEIC／HIF 支持", False),
    ("send2trash", "删除到废纸篓", False),
    ("anthropic", "Claude 细评", False),
    ("openai", "ChatGPT／Grok 细评", False),
]
TARGETS = {   # --download 用：pip 的平台标签
    "win": ["win_amd64"],
    "mac-arm": ["macosx_11_0_arm64", "macosx_12_0_arm64", "macosx_13_0_arm64", "macosx_14_0_arm64"],
    "mac-intel": ["macosx_10_9_x86_64", "macosx_10_13_x86_64", "macosx_11_0_x86_64", "macosx_12_0_x86_64"],
    "linux": ["manylinux2014_x86_64", "manylinux_2_17_x86_64", "manylinux_2_28_x86_64"],
}


def say(msg: str = ""):
    print(msg, flush=True)


def req_hash() -> str:
    return hashlib.sha256(REQ.read_bytes()).hexdigest()


def venv_python(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if IS_WIN else "bin/python")


def run(cmd: list, **kw) -> int:
    say("  $ " + " ".join(str(c) for c in cmd))
    return subprocess.call([str(c) for c in cmd], **kw)


def py_version(py: Path) -> tuple | None:
    try:
        out = subprocess.run([str(py), "-c", "import sys;print(sys.version_info[0],sys.version_info[1])"],
                             capture_output=True, text=True, timeout=30)
        a, b = out.stdout.split()
        return int(a), int(b)
    except Exception:
        return None


def pick_mirror(choice: str) -> str | None:
    """auto：PyPI 4 秒内连得上就用官方源，否则用清华镜像。"""
    if choice in MIRRORS:
        return MIRRORS[choice]
    if choice.startswith("http"):
        return choice
    try:
        urllib.request.urlopen("https://pypi.org/simple/pip/", timeout=4).read(64)
        return None
    except Exception:
        say("连不上 PyPI 官方源，改用清华镜像。")
        return MIRRORS["tuna"]


def pip_args(index: str | None, wheels: Path | None) -> list:
    if wheels:
        return ["--no-index", "--find-links", str(wheels)]
    if index:
        host = index.split("/")[2]
        return ["-i", index, "--trusted-host", host]
    return []


def check_modules(py: Path) -> list:
    """逐个导入，返回 [(模块, 用途, 必需, 版本或错误, 是否成功)]。"""
    res = []
    for mod, what, need in MODULES:
        code = (f"import {mod} as m;v=getattr(m,'__version__','')"
                + (";import rawpy;v=v+' / LibRaw '+'.'.join(map(str,rawpy.libraw_version))" if mod == "rawpy" else "")
                + ";print(v or 'ok')")
        p = subprocess.run([str(py), "-c", code], capture_output=True, text=True, timeout=120)
        okay = p.returncode == 0
        info = p.stdout.strip() if okay else (p.stderr.strip().splitlines() or ["导入失败"])[-1]
        res.append((mod, what, need, info, okay))
    return res


def check_files() -> list:
    """工具本身是否完整：程序文件、内置 LUT、设置文件夹能否写入。"""
    out = []
    missing = [f for f in ("cull.py", "gui.py", "photo_cull/__init__.py", "photo_cull/version.py", "requirements.txt",
                                    "web/cull/index.html", "web/edit/index.html", "web/report/report.html", "web/shell/index.html",
                                    "locales/zh-CN.json", "locales/en.json", "locales/ja.json", "locales/ko.json") if not (ROOT / f).is_file()]
    out.append(("程序文件", not missing, "完整" if not missing else "缺少 " + "、".join(missing)))
    luts = list((ROOT / "luts").rglob("*.cube")) if (ROOT / "luts").is_dir() else []
    out.append(("内置 LUT", len(luts) >= 39, f"{len(luts)} 个"))
    cfg = Path.home() / ".photo-cull"
    try:
        cfg.mkdir(parents=True, exist_ok=True)
        t = cfg / ".write-test"
        t.write_text("ok", encoding="utf-8")
        t.unlink()
        out.append(("设置文件夹", True, str(cfg)))
    except OSError as e:
        out.append(("设置文件夹", False, f"{cfg} 不能写入：{e}"))
    return out


def report(py: Path) -> bool:
    say("\n── 检查结果 ──")
    v = py_version(py)
    say(f"  Python        {v[0]}.{v[1]}（{py}）" if v else f"  Python        无法运行 {py}")
    good = v is not None
    for mod, what, need, info, okay in check_modules(py) if v else []:
        mark = "✓" if okay else ("✗" if need else "!")
        say(f"  {mark} {what:<16s} {info}")
        if need and not okay:
            good = False
    for name, okay, info in check_files():
        say(f"  {'✓' if okay else '✗'} {name:<16s} {info}")
        good = good and okay
    say("  （! 表示可选功能不可用，不影响其余部分）")
    return good


def download(dest: Path, target: str, pyver: str, index: str | None) -> int:
    dest.mkdir(parents=True, exist_ok=True)
    plats = TARGETS[target]
    cmd = [sys.executable, "-m", "pip", "download", "-r", str(REQ), "-d", str(dest), "--only-binary=:all:",
           "--python-version", pyver] + sum((["--platform", p] for p in plats), []) + pip_args(index, None)
    code = run(cmd)
    # pip 本身也带上，离线环境里升级 pip 用
    run([sys.executable, "-m", "pip", "download", "pip", "-d", str(dest), "--only-binary=:all:",
         "--python-version", pyver] + sum((["--platform", p] for p in plats), []) + pip_args(index, None))
    if code == 0:
        n = len(list(dest.glob("*.whl")))
        say(f"\n已下载 {n} 个安装包到 {dest}（目标：{target}，Python {pyver}）。")
        say(f"拷到新电脑的工具文件夹旁边后运行：python3 tools/setup_env.py --wheels {dest.name}")
    return code


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="照片工具：部署／修复运行环境")
    ap.add_argument("--check", action="store_true", help="只检查，不安装")
    ap.add_argument("--recreate", action="store_true", help="删掉旧环境重新装")
    ap.add_argument("--mirror", default="auto", help="pip 源：auto（默认）、tuna、aliyun、ustc、pypi，或完整网址")
    ap.add_argument("--wheels", type=Path, help="从本地文件夹离线安装")
    ap.add_argument("--download", type=Path, help="下载离线安装包到这个文件夹（不安装）")
    ap.add_argument("--target", choices=list(TARGETS), default="win", help="--download 的目标系统")
    ap.add_argument("--target-python", default="3.12", help="--download 的目标 Python 版本（默认 3.12）")
    ap.add_argument("--quiet-if-ready", action="store_true", help="环境已就绪时不输出（启动文件调用时用）")
    a = ap.parse_args(argv)

    say(f"照片工具 运行环境（{platform.system()} {platform.machine()}，工具文件夹：{ROOT}）")
    if sys.version_info[:2] < MIN_PY:
        say(f"需要 Python {MIN_PY[0]}.{MIN_PY[1]} 或更高版本，当前是 {sys.version.split()[0]}。")
        return 2
    if IS_WIN and platform.machine().lower() in ("arm64", "aarch64"):
        say("提示：ARM 版 Windows 暂不支持（RAW 解码库没有 ARM 版），安装可能失败。")

    if a.download:
        return download(a.download.resolve(), a.target, a.target_python, pick_mirror(a.mirror))

    py = venv_python(VENV)
    stamp = VENV / ".req-hash"
    if a.check:
        return 0 if report(py) else 1

    ready = py.is_file() and py_version(py) is not None and stamp.is_file() \
        and stamp.read_text(encoding="utf-8").strip().lower() == req_hash()
    if ready and not a.recreate and not a.wheels:
        if not a.quiet_if_ready:
            say("环境已就绪，无需安装。（要重新检查可加 --check，重装可加 --recreate）")
        return 0

    t0 = time.time()
    if a.recreate and VENV.exists():
        say(f"删除旧环境 {VENV} …")
        shutil.rmtree(VENV, ignore_errors=True)
    if py.is_file() and py_version(py) is None:          # 环境坏了（比如系统 Python 升级后）：重建
        say("旧环境无法运行，重新创建…")
        shutil.rmtree(VENV, ignore_errors=True)
    if not py.is_file():
        say(f"\n① 创建 Python 环境：{VENV}")
        if run([sys.executable, "-m", "venv", str(VENV)]) != 0 or not py.is_file():
            say("创建环境失败。macOS 可以先安装 python.org 的 Python；Linux 需要 python3-venv。")
            return 1
    index = None if a.wheels else pick_mirror(a.mirror)
    extra = pip_args(index, a.wheels.resolve() if a.wheels else None)
    say("\n② 更新 pip")
    run([py, "-m", "pip", "install", "--upgrade", "pip", "--disable-pip-version-check"] + extra)
    say("\n③ 安装依赖（第一次约 1–5 分钟）")
    if run([py, "-m", "pip", "install", "-r", REQ, "--disable-pip-version-check"] + extra) != 0:
        say("\n依赖安装失败。可以：检查网络后重试；或加 --mirror tuna 用国内镜像；或用 --wheels 离线安装。")
        return 1
    good = report(py)
    if good:
        stamp.write_text(req_hash(), encoding="utf-8")
        say(f"\n环境准备完成，用时 {time.time() - t0:.0f} 秒。现在可以双击「启动筛选」「启动编辑」了。")
        return 0
    say("\n有必需的组件不能用，请把上面的检查结果截图发回来。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
