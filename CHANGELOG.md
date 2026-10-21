# 更新日志

版本号见 `cull.py` 里的 `VERSION`。日期为北京时间。

## 1.5-beta（2026-10-21）
- **内置 LUT**：39 个 LUT 随工具发布（`luts/`），工作空间均为 sRGB。
  - Fujifilm GFX 胶片模拟 20 个，命名「机型 + 胶片模拟名 (sRGB)」，如 `GFX50S PROVIA (sRGB)`。
  - Leica Look 19 个，命名「Leica Look + 滤镜名 (sRGB)」，如 `Leica Look CHR (sRGB)`。
  - 编辑记录保存 `builtin:` 相对引用，换电脑也能用；旧路径可用可选的 `lut-aliases.json` 对应。
- **添加 LUT**：照片编辑「风格（LUT）」里的「添加 LUT…」，可多选 `.cube`；先检查格式，再存到 `~/.photo-cull/luts`，显示在「我的 LUT」分组，可移除。
- **自动调整**：整体调性与对比度优化（对比度随画面反差自适应，黑场只压深、白场只提亮）；HDR 动态测光隐藏，等 HDR 显示模式一起做。
- **Windows / macOS 测试包**：`tools/make_release.py` 生成两个 zip；Windows 用 PowerShell 启动，缺 Python 时用 winget 安装 3.12。
- **环境部署脚本** `tools/setup_env.py`（`安装环境.command` / `安装环境.bat`）：建独立环境、自动换国内镜像、逐个检查组件；支持 `--check --recreate --mirror --wheels --download`。启动文件在环境不对时自动修复。
- **开源**：MIT 许可证、`CONTRIBUTING.md`、`.gitignore`、`.gitattributes`、Issue / PR 模板。

## 1.4
- 照片筛选与照片编辑拆成两个独立程序（`gui.py --app cull|edit`），可同时运行、互相跳转。
- 自动调整提供多种测光方案：全局评价、徕卡经典中央重点（默认）、徕卡全局 +0.3EV、富士中央重点。
- 镜头暗角：4 支徕卡 M 镜头（11874 / 11699 / 11141 / 11672）× 弱 / 中 / 强。
- 全管线提速：部分解码、内嵌预览缩略图、渲染缓存、平面内存布局、四面体 3D LUT 重写、多线程分块渲染。

## 1.3.1
- 修复编辑器预览图、缩略图过小；自动调整默认按徕卡 STD 风格做曝光和暗角。

## 1.3
- 整理输出：按 `保留/淘汰` × `JPEG/RAW` 分文件夹，复制或移动；重复运行不产生重复文件；在报告里改星级、删除后输出文件夹自动同步。
- 重命名：`星级_机型_原名`，如 `4_ILCE-1M2_DSC01234.ARW`，只改输出文件夹里的文件。
- 支持富士 RAF（读取内嵌 JPEG 预览）。

## 1.2 及更早
- 本地评分（清晰度、曝光、闭眼等）、AI 细评（Claude / ChatGPT / Grok / Gemini）、XMP 星级与色标、RAW+JPEG 配对、HTML 报告、照片编辑基础版。
