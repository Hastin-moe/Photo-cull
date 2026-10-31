# 参与贡献

**简体中文** · [English](CONTRIBUTING.en.md) · [日本語](CONTRIBUTING.ja.md) · [한국어](CONTRIBUTING.ko.md)

欢迎提交改进、修复、翻译和想法。本项目采用 MIT 许可证，提交即表示你同意贡献内容也以 MIT 许可证发布。Issue 和 PR 用中文、英文、日文、韩文都可以。

## 怎么参与
1. 先开一个 Issue 说明想做什么（小修小补可以直接提 PR）。
2. Fork 仓库，从 `main` 拉分支，比如 `feat/xxx`、`fix/xxx`、`i18n/xx`。
3. 跑一遍测试（`python3 tests/run.py`），并亲手试一下改到的功能。PR 里写清楚改了什么、为什么改、怎么验证的、会不会影响已有的结果。
4. 提交 Pull Request。一个 PR 只做一件事。

## 本地运行
- macOS：双击 `安装环境.command`，然后 `启动筛选.command`／`启动编辑.command`。
- Windows：`安装环境.bat`、`启动筛选.bat`、`启动编辑.bat`。
- 或命令行：`python3 tools/setup_env.py`，然后 `.venv/bin/python gui.py`（一体窗口；`--start edit` 先显示编辑，`--app cull|edit` 只运行其中一个，`--lang en` 指定界面语言）。
- 只用命令行：`.venv/bin/python cull.py "照片文件夹"`（等同于 `python3 -m photo_cull.cull`）。
- 检查环境：`python3 tools/setup_env.py --check`。

## 测试
`python3 tests/run.py` 会把 `tests/test_*.py` 逐个放在单独的进程里跑，`HOME` 指向临时文件夹（不会碰你自己的设置）。测试照片全部由代码生成（`tests/fixtures.py`）；AI 细评用本机的假接口测试，不花钱。只跑一个文件：`python3 tests/run.py test_scoring.py`。修 bug、加功能时请顺手加一条测试。

## 源码结构

```
photo_cull/
  version.py     版本号（唯一写版本号的地方）
  paths.py       固定位置：自带的资源（web/、locales/、luts/）和 ~/.photo-cull
  i18n.py        多语言：读取 locales/，t("键") 取当前语言的文字
  imaging/       读图与 EXIF：格式、TIFF 结构的 RAW、富士 RAF、预览（筛选和编辑共用）
  cull/          照片筛选
    model.py       照片数据和 results.json 格式（schema 2；旧结果载入时自动转换）
    analysis.py    锐度、曝光、人脸／眼睛／笑容
    grouping.py    连拍和同场景重拍分组
    scoring.py     10 分制评分、精彩帧权重、精选／连拍瞬间／可用
    ai/            providers.py（模型和接口调用）、prompts.py（各语言提示词）、review.py
    xmp.py         边车 XMP 和 JPEG 内嵌 XMP
    organize.py    整理输出、重命名；trash.py 移到废纸篓
    report.py      results.json／csv／report.html
    pipeline.py    各阶段按顺序执行；cli.py 命令行参数
  edit/          照片编辑：color、logspace、lut3d、refs／styles（LUT 引用、用户 LUT）、presets、curves、
                 decode、render、auto、session、records（编辑记录）、library、export
  server/        本地网页服务：settings、jobs、apps（两个程序）、pages、actions（报告里的操作）、
                 handler（/api 接口）、runtime（一体窗口）、main
cull.py · gui.py · desktop.py   入口（命令行、本地网页、Mac 应用）
web/           前端：common/（设计变量 tokens.css、i18n.js、shell.js）、cull/、edit/、report/、shell/
locales/       语言包：zh-CN.json、en.json、ja.json、ko.json
luts/          内置 LUT（sRGB）
tests/         测试（run.py、fixtures.py、test_*.py）
tools/         setup_env.py（部署环境）、build_mac_app.py（打包 Mac 应用）、make_release.py（打包）、check_i18n.py（检查语言包）
docs/          工作记录、结构说明、界面设计方向、测试计划
```

## 约定
- **前后端分离**：Python 里不写 HTML。改界面就改 `web/` 里的文件，刷新浏览器即可，不用重启。
- **所有用户看得到的文字都放进语言包**：Python 用 `t("分组.键")`，网页用 `T("分组.键")` 或在 HTML 上写 `data-i18n="分组.键"`。新增文字时四种语言都要加；不会的语言先写英文，在 PR 里说明，留给其他人翻译。提交前跑一下 `python3 tools/check_i18n.py`。
- **颜色、字体、圆角只用 `web/common/tokens.css` 里的变量**，不要在页面里写死颜色。
- `photo_cull/cull` 和 `photo_cull/edit` 互不导入；两边都要用的放进 `photo_cull/imaging`。
- 分数内部精确到 0.1，显示整数；XMP 星级永远由分数折算（`model.xmp_stars`），不单独保存。
- 编辑器的预览和导出必须走同一条渲染管线，改完要核对两者一致。
- 绝不覆盖用户的原文件：写入前确认路径，删除一律走废纸篓。
- 保存的数据里存代码，不存句子（比如问题标记存成 `blur`、`clip_high:0.05`，分类存成 `pick`、`moment`…，显示时再翻译），换语言后旧结果也能正常显示。结果格式有变化时，把 `cull/model.py` 的 `SCHEMA` 加一，并在 `photos_from_json` 里转换旧格式。
- 不要提交 `.venv`、`dist/`、个人照片和 API Key。

## 翻译与新增语言
- 修改译文：编辑 `locales/<语言>.json`，不要改键名，`{占位符}` 保持原样。
- 新增语言：复制 `locales/en.json` 为 `locales/<语言代码>.json` 并翻译，在 `photo_cull/i18n.py` 的 `LANGS` 里登记；`photo_cull/cull/ai/prompts.py` 的 `AI_PROMPTS` 里加一份该语言的细评提示词（要求模型用该语言写评语）。然后跑 `python3 tools/check_i18n.py`。
- README 有四种语言（`README.md`、`README.en.md`、`README.ja.md`、`README.ko.md`），改动功能时请尽量同步更新。

## LUT
- `luts/` 里是内置 LUT，工作空间均为 sRGB。新增内置 LUT 按「机型 + 胶片模拟名 (sRGB)」（富士）或「Leica Look + 滤镜名 (sRGB)」（徕卡）命名，并在文件头注明工作空间。
- 只给自己用的 LUT 不需要改代码：在照片编辑里点「添加 LUT…」。

## AI 模型
- 可选模型列在 `photo_cull/cull/ai/providers.py` 的 `PROVIDERS` 里，只列能看图的模型；更新列表时请注明核对日期和来源。
- 支持 OpenAI Chat Completions 的新服务商通常不用改代码：用户选「自定义」填地址即可。常用的可以在 `PROVIDERS` 里加一项（`api: "chat"`）。

## 欢迎的方向
- 界面视觉和交互（见 [docs/GUI设计方向.md](docs/GUI设计方向.md)）。
- 更多语言的翻译。
- 更好的人脸、眼睛、笑容检测（精彩帧权重依赖它们）。
- 更多 RAW 和 EXIF 的支持（富士 RAF 需要真实样片）。
- Windows 实机测试（目前只做过静态检查）。
- 自动调整方案和镜头暗角的数据改进。
- HDR 显示与测光（已在计划中）。

路线图见 [docs/工作记录.md](docs/工作记录.md) 和 [docs/测试计划.md](docs/测试计划.md)。较大的改动请同时更新 [CHANGELOG.md](CHANGELOG.md)。
