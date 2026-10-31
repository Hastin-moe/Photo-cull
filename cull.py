#!/usr/bin/env python3
"""照片筛选（命令行）。代码在 photo_cull/cull/，这里只是入口：

    python3 cull.py 照片文件夹 [选项]      # 等同于 python3 -m photo_cull.cull
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from photo_cull.cull.cli import main  # noqa: E402

if __name__ == "__main__":
    main()
