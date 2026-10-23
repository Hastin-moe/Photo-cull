#!/bin/bash
# 双击启动「照片筛选」（macOS）。环境没准备好时会先自动安装（第一次需要联网）。
# 两个程序在同一个窗口里，右上角直接切换；已经开着时再双击只会打开现有窗口。关掉终端窗口即可退出。
cd "$(dirname "$0")" || exit 1
printf '\033]0;照片筛选\007'

PY=".venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3 || true)"
if [ -z "$PY" ] || ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
  echo "没有找到 Python 3.9 或更高版本。请从 https://www.python.org/downloads/ 安装后重试。"
  read -r -p "按回车键关闭…" _
  exit 1
fi
if ! "$PY" tools/setup_env.py --quiet-if-ready; then
  echo
  echo "运行环境没有准备好。可以双击「安装环境.command」查看详细检查结果。"
  read -r -p "按回车键关闭…" _
  exit 1
fi

exec .venv/bin/python gui.py --app all --start cull
