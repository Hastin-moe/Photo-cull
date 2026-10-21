"""打包测试版：python3 tools/make_release.py  →  dist/ 下生成 Windows 与 macOS 两个 zip。
包里只有源码、启动文件、内置 LUT 和说明；不含 .venv、缓存、测试素材。第一次运行时在对方电脑上联网装依赖。"""
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import cull  # noqa: E402

VER = cull.VERSION
COMMON = ["cull.py", "gui.py", "editor.py", "editor_ui.py", "requirements.txt", "README.md", "LICENSE", "luts/说明.txt", "tools/setup_env.py"]
PLATFORM = {
    "Windows": ["安装环境.bat", "启动筛选.bat", "启动编辑.bat", "windows/run.ps1", "windows/setup.ps1"],
    "macOS": ["安装环境.command", "启动筛选.command", "启动编辑.command"],
}

QUICK = {
    "Windows": f"""照片工具 {VER}（Windows 测试版）

1. 把整个文件夹解压到一个固定位置（例如「文档」里），不要直接在压缩包里运行。
2. 先双击「安装环境.bat」准备运行环境（需要联网，约 3–5 分钟）：
   · 电脑上没有 Python 3.9 以上时，会提示用 Windows 自带的 winget 安装 Python 3.12，按回车即可；
   · 连不上 PyPI 官方源时自动改用清华镜像；
   · 最后会列出每个组件的检查结果，全部 ✓ 就可以了。
   （跳过这一步直接双击启动文件也行，第一次会自动安装。）
3. 双击「启动筛选.bat」打开照片筛选，双击「启动编辑.bat」打开照片编辑。两个可以同时开。
4. 如果弹出「Windows 已保护你的电脑」，点「更多信息」→「仍要运行」。
5. 关闭黑色的命令行窗口即可退出对应的程序。

要求：64 位 Windows 10／11（x64）。ARM 版 Windows 暂不支持。
内置 39 个 LUT（Fujifilm GFX 胶片模拟 20 个、Leica Look 19 个，工作空间均为 sRGB），在照片编辑的「风格（LUT）」里直接用。
设置、缩略图缓存放在 用户文件夹\\.photo-cull；照片的星级、编辑记录写在照片所在文件夹里。
详细说明见 README.md（可以用记事本或浏览器打开）。

这是测试版：遇到问题时，把命令行窗口里的文字截图发回来。
""",
    "macOS": f"""照片工具 {VER}（macOS 测试版）

1. 解压到一个固定位置（例如「文稿」或桌面）。
2. 需要先装好 Python 3.9 以上：https://www.python.org/downloads/
3. 右键点「安装环境.command」→「打开」→ 再点「打开」（macOS 对网上下载的脚本会先拦一下），
   它会联网安装依赖（约 1–3 分钟；连不上 PyPI 时自动用清华镜像），最后列出检查结果。
4. 「启动筛选.command」「启动编辑.command」第一次也要右键 →「打开」，以后直接双击。两个可以同时开。
5. 关闭终端窗口即可退出对应的程序。

内置 39 个 LUT（Fujifilm GFX 胶片模拟 20 个、Leica Look 19 个，工作空间均为 sRGB），在照片编辑的「风格（LUT）」里直接用。
详细说明见 README.md。
""",
}


def build(platform: str) -> Path:
    top = f"照片工具 {VER}"
    out = ROOT / "dist" / f"照片工具-{VER}-{platform}.zip"
    out.parent.mkdir(exist_ok=True)
    files = COMMON + PLATFORM[platform]
    luts = sorted(p for p in (ROOT / "luts").rglob("*.cube"))
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for rel in files:
            src = ROOT / rel
            info = zipfile.ZipInfo.from_file(src, f"{top}/{rel}")
            info.compress_type = zipfile.ZIP_DEFLATED
            mode = 0o755 if rel.endswith(".command") else 0o644
            info.external_attr = (0o100000 | mode) << 16           # 保留 .command 的可执行权限
            z.writestr(info, src.read_bytes())
        for p in luts:
            rel = p.relative_to(ROOT).as_posix()
            info = zipfile.ZipInfo.from_file(p, f"{top}/{rel}")
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o100644) << 16
            z.writestr(info, p.read_bytes())
        text = QUICK[platform]
        data = ("﻿" + text.replace("\n", "\r\n")).encode("utf-8") if platform == "Windows" else text.encode("utf-8")
        info = zipfile.ZipInfo(f"{top}/先看我.txt", date_time=(2026, 10, 21, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = (0o100644) << 16
        z.writestr(info, data)
    return out


if __name__ == "__main__":
    for plat in ("Windows", "macOS"):
        f = build(plat)
        print(f"{f.name}  {f.stat().st_size / 1e6:.1f} MB")
