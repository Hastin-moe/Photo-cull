#!/bin/bash
# 照片工具：部署／修复运行环境（macOS、Linux）。双击即可；也可以在终端里带参数运行：
#   ./安装环境.command --check          只检查
#   ./安装环境.command --recreate       重新安装
#   ./安装环境.command --mirror tuna    用清华镜像
#   ./安装环境.command --wheels 离线包   离线安装
cd "$(dirname "$0")" || exit 1
printf '\033]0;照片工具 · 安装环境\007'
PY="$(command -v python3 || true)"
if [ -z "$PY" ] || ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
  echo "没有找到 Python 3.9 或更高版本。"
  echo "请从 https://www.python.org/downloads/ 下载安装（macOS 选 universal2 安装包），装好后重新双击本文件。"
  read -r -p "按回车键关闭…" _
  exit 1
fi
"$PY" tools/setup_env.py "$@"
code=$?
echo
read -r -p "按回车键关闭…" _
exit $code
