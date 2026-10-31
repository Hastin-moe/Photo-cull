from __future__ import annotations

import threading

# 供图形界面使用的钩子：进度回调与取消信号
PROGRESS = None            # callable(stage, done, total)
API_KEYS: dict = {}        # 图形界面传入的 API Key（优先于环境变量，不写入环境）
CANCEL = threading.Event()


class Cancelled(Exception):
    pass


def _report(stage, done, total):
    if PROGRESS:
        try:
            PROGRESS(stage, done, total)
        except Exception:
            pass
    if CANCEL.is_set():
        raise Cancelled()
CUSTOM_BASE: dict = {}      # 图形界面／命令行传入的自定义接口地址 {"custom": url}
