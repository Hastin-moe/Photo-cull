#!/bin/bash
# 双击：把照片工具打包成「照片工具.app」（自带 Python 和全部依赖，以后双击应用就能用，不需要终端）。
# 第一次要联网安装打包工具，约 3–8 分钟。结果在 dist/mac/照片工具.app。
cd "$(dirname "$0")" || exit 1
printf '\033]0;打包照片工具\007'
PY="$(command -v python3 || true)"
[ -x ".venv/bin/python" ] && PY=".venv/bin/python"
if [ -z "$PY" ] || ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
  echo "没有找到 Python 3.9 或更高版本。请从 https://www.python.org/downloads/ 安装后重试。"
  read -r -p "按回车键关闭…" _
  exit 1
fi
"$PY" tools/build_mac_app.py "$@"
echo
read -r -p "按回车键关闭…" _
