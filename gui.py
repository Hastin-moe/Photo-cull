#!/usr/bin/env python3
"""照片筛选／照片编辑（本地网页界面）。代码在 photo_cull/server/，这里只是入口：

    python3 gui.py                    # 一体窗口（默认先显示照片筛选）
    python3 gui.py --start edit       # 一体窗口，先显示照片编辑
    python3 gui.py --app cull|edit    # 只运行其中一个
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from photo_cull.server.main import main  # noqa: E402

if __name__ == "__main__":
    main()
