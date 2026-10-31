#!/usr/bin/env python3
"""跑全部测试：python3 tests/run.py [文件名…]

每个 test_*.py 在单独的进程里运行，HOME 指向临时文件夹（不会碰你自己的设置和 ~/.photo-cull），
界面语言固定为简体中文，不自动打开浏览器、不在后台启动另一个程序。
"""
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> int:
    files = [HERE / f for f in sys.argv[1:]] or sorted(HERE.glob("test_*.py"))
    bad = 0
    t0 = time.time()
    for f in files:
        home = tempfile.mkdtemp(prefix="photo-cull-home-")
        env = dict(os.environ, HOME=home, USERPROFILE=home, PHOTO_CULL_LANG="zh-CN", PHOTO_CULL_NO_AUTOSTART="1",
                   PHOTO_CULL_NO_BROWSER="1", PHOTO_CULL_TEST_TMP=tempfile.mkdtemp(prefix="photo-cull-test-"))
        env.pop("PHOTO_CULL_PORT", None)
        print(f"● {f.name}", flush=True)
        r = subprocess.run([sys.executable, str(f)], env=env)
        bad += r.returncode != 0
    print(f"\n{len(files) - bad}/{len(files)} 个文件通过，用时 {time.time() - t0:.0f} 秒")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
