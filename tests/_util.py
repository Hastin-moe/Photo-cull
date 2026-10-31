"""测试用的小工具：不依赖 pytest。每个 test_*.py 文件末尾调用 run(globals())。"""
from __future__ import annotations

import contextlib
import io
import os
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
TMP = Path(os.environ.get("PHOTO_CULL_TEST_TMP") or tempfile.mkdtemp(prefix="photo-cull-test-"))


def quiet(fn, *a, **kw):
    """运行 fn，吞掉它打印的内容；返回 (结果, 输出文本)。"""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        res = fn(*a, **kw)
    return res, buf.getvalue()


def after_sos(b: bytes) -> bytes:
    """JPEG 的画面数据（SOS 之后的部分）：写 XMP 前后应该逐字节相同。"""
    i = 2
    while True:
        assert b[i] == 0xFF
        mk, ln = b[i + 1], int.from_bytes(b[i + 2:i + 4], "big")
        if mk == 0xDA:
            return b[i:]
        i += 2 + ln


def run(ns: dict):
    tests = [(k, v) for k, v in ns.items() if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  ✓ {name}")
        except Exception:
            failed += 1
            print(f"  ✗ {name}")
            traceback.print_exc()
    print(f"{len(tests) - failed}/{len(tests)} 通过")
    sys.exit(1 if failed else 0)
