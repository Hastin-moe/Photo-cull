# 参与贡献

欢迎提交改进、修复和新想法，本项目以 MIT 许可证开源。提交即表示你同意你的贡献也以 MIT 许可证发布。

## 怎么参与
1. 先开一个 Issue 说明想做什么（小修复可以直接提交 PR）。
2. Fork 仓库，从 `main` 建分支，如 `feat/xxx` 或 `fix/xxx`。
3. 修改后自己跑一遍相关功能，在 PR 描述里写清：改了什么、为什么、怎么验证的、是否影响已有结果。
4. 提交 Pull Request，一个 PR 只做一件事。

## 本地运行
- macOS：双击 `安装环境.command`，再用 `启动筛选.command` / `启动编辑.command`。
- Windows：`安装环境.bat`、`启动筛选.bat`、`启动编辑.bat`。
- 或命令行：`python3 tools/setup_env.py`，然后 `.venv/bin/python gui.py --app cull`（编辑用 `--app edit`）。
- 环境检查：`python3 tools/setup_env.py --check`。

## 代码约定
- 筛选（`cull.py`）和编辑（`editor.py` / `editor_ui.py`）是两个独立程序，共用 `gui.py`，不要让一方依赖另一方的内部接口。
- 编辑器预览和导出必须走同一条渲染管线，改动后确认两者结果一致。
- 不要覆盖用户原片：写文件前先确认路径，删除一律走废纸篓。
- 界面和说明文字用中文，用户看得到的提示要说人话。
- 不要提交 `.venv`、`dist/`、个人照片或 API 密钥。

## 关于 LUT
- `luts/` 里是内置 LUT，工作空间均为 sRGB。新增内置 LUT 请沿用命名规则：富士为「机型 + 胶片模拟名 (sRGB)」，Leica 为「Leica Look + 滤镜名 (sRGB)」，并在文件头写明工作空间。
- 只想自己用的 LUT 不需要改源码：在照片编辑里点「添加 LUT…」即可。

## 欢迎的方向
- 更多相机 RAW 与 EXIF 兼容（富士 RAF 需要真实样张验证）。
- Windows 实机测试与问题反馈（目前只做过静态检查）。
- 自动调整方案、镜头暗角参数的更准数据。
- HDR 显示与测光（计划中）。
- 测试用例与文档（测试脚本计划整理到 `tests/`）。

详见 [docs/工作记录.md](docs/工作记录.md) 的“后续计划”和 [docs/测试计划.md](docs/测试计划.md)。改动较大时请同时更新 [CHANGELOG.md](CHANGELOG.md)。
