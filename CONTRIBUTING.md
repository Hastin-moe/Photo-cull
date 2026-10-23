# 参与贡献

**简体中文** · [English](CONTRIBUTING.en.md) · [日本語](CONTRIBUTING.ja.md)

欢迎提交改进、修复、翻译和新想法，本项目以 MIT 许可证开源。提交即表示你同意你的贡献也以 MIT 许可证发布。Issue 和 PR 用中文、英文、日文都可以。

## 怎么参与
1. 先开一个 Issue 说明想做什么（小修复可以直接提交 PR）。
2. Fork 仓库，从 `main` 建分支，如 `feat/xxx`、`fix/xxx`、`i18n/xx`。
3. 修改后自己跑一遍相关功能，在 PR 描述里写清：改了什么、为什么、怎么验证的、是否影响已有结果。
4. 提交 Pull Request，一个 PR 只做一件事。

## 本地运行
- macOS：双击 `安装环境.command`，再用 `启动筛选.command` / `启动编辑.command`。
- Windows：`安装环境.bat`、`启动筛选.bat`、`启动编辑.bat`。
- 或命令行：`python3 tools/setup_env.py`，然后 `.venv/bin/python gui.py --app cull`（编辑用 `--app edit`；加 `--lang en` 可指定界面语言）。
- 环境检查：`python3 tools/setup_env.py --check`。

## 源码结构

```
cull.py        照片筛选：读图、评分、AI 细评、XMP、整理输出、生成报告
editor.py      照片编辑：解码、渲染管线、LUT、自动调整、导出
gui.py         本地网页服务：提供 web/ 里的页面和 /api 接口
desktop.py     桌面应用入口（Mac 应用）：一个原生窗口装两个程序
i18n.py        多语言：读取 locales/，t("键") 取当前语言的文字
web/           界面（前端）：common/（设计变量 tokens.css、i18n.js、shell.js）、cull/、edit/、report/、shell/（一体窗口）
packaging/     PyInstaller 配置和应用图标
locales/       语言包：zh-CN.json、en.json、ja.json
luts/          内置 LUT（sRGB）
tools/         setup_env.py（部署环境）、make_release.py（打包）、check_i18n.py（检查语言包）、build_mac_app.py（打包 Mac 应用）
```

## 代码约定
- **前后端分离**：Python 里不写 HTML；界面改 `web/` 里的文件即可，改完刷新浏览器就能看到（不用重启程序）。
- **所有用户看得到的文字都放进语言包**：Python 用 `t("分组.键")`，网页用 `T("分组.键")` 或在 HTML 上写 `data-i18n="分组.键"`。新增文字时三种语言都要加上；不会某种语言可以先填英文，在 PR 里说明，请别人补译。改完运行 `python3 tools/check_i18n.py`，没有问题再提交。
- **颜色、字体、圆角只用 `web/common/tokens.css` 里的变量**，不要在页面里写死颜色。
- 筛选（`cull.py`）和编辑（`editor.py`）是两个独立程序，共用 `gui.py`，不要让一方依赖另一方的内部接口。
- 编辑器预览和导出必须走同一条渲染管线，改动后确认两者结果一致。
- 不要覆盖用户原片：写文件前先确认路径，删除一律走废纸篓。
- 保存到文件里的数据用代码而不是某种语言的句子（例如问题标记存 `blur`、`clip_high:0.05`，显示时再翻译），这样换语言后旧结果也能正常显示。
- 不要提交 `.venv`、`dist/`、个人照片或 API 密钥。

## 翻译与新增语言
- 修改译文：直接编辑 `locales/<语言>.json`，键名不要动，`{占位符}` 原样保留。
- 新增语言：复制 `locales/en.json` 为 `locales/<语言代码>.json` 并翻译，在 `i18n.py` 的 `LANGS` 里登记；`cull.py` 的 `AI_PROMPTS` 里加一份该语言的细评提示词（要求模型用该语言写评语）。运行 `python3 tools/check_i18n.py` 检查。
- README 有三种语言（`README.md`、`README.en.md`、`README.ja.md`），改动功能时请尽量同步更新。

## 关于 LUT
- `luts/` 里是内置 LUT，工作空间均为 sRGB。新增内置 LUT 请沿用命名规则：富士为「机型 + 胶片模拟名 (sRGB)」，Leica 为「Leica Look + 滤镜名 (sRGB)」，并在文件头写明工作空间。
- 只想自己用的 LUT 不需要改源码：在照片编辑里点「添加 LUT…」即可。

## 关于 AI 模型
- 可选模型列在 `cull.py` 的 `PROVIDERS` 里，只列能看图的模型；更新列表时请注明核对日期和来源。
- 新服务商如果兼容 OpenAI 的 Chat Completions，通常不需要写代码：用户选「自定义」填地址即可；确实常用的，可以在 `PROVIDERS` 里加一项（`api: "chat"`）。

## 欢迎的方向
- 界面视觉与交互（方向见 [docs/GUI设计方向.md](docs/GUI设计方向.md)）。
- 更多语言的翻译。
- 更多相机 RAW 与 EXIF 兼容（富士 RAF 需要真实样张验证）。
- Windows 实机测试与问题反馈（目前只做过静态检查）。
- 自动调整方案、镜头暗角参数的更准数据。
- HDR 显示与测光（计划中）。
- 测试用例与文档（测试脚本计划整理到 `tests/`）。

详见 [docs/工作记录.md](docs/工作记录.md) 的“后续计划”和 [docs/测试计划.md](docs/测试计划.md)。改动较大时请同时更新 [CHANGELOG.md](CHANGELOG.md)。
