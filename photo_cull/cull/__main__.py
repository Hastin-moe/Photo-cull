"""python3 -m photo_cull.cull 照片文件夹 [选项]"""
import sys

from .cli import main

sys.exit(main() and 0)
