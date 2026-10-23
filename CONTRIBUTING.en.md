# Contributing

[简体中文](CONTRIBUTING.md) · **English** · [日本語](CONTRIBUTING.ja.md)

Improvements, fixes, translations and ideas are welcome. The project is MIT-licensed, and by submitting you agree that your contribution is released under the MIT License too. Issues and PRs may be written in Chinese, English or Japanese.

## How to contribute
1. Open an issue describing what you’d like to do (small fixes can go straight to a PR).
2. Fork the repository and branch from `main`, e.g. `feat/xxx`, `fix/xxx`, `i18n/xx`.
3. Try the affected features yourself. In the PR, describe what changed, why, how you verified it, and whether existing results are affected.
4. Open a pull request. One PR, one change.

## Running locally
- macOS: double-click `安装环境.command` (install environment), then `启动筛选.command` (Photo Cull) / `启动编辑.command` (Photo Edit).
- Windows: `安装环境.bat`, `启动筛选.bat`, `启动编辑.bat`.
- Or from a terminal: `python3 tools/setup_env.py`, then `.venv/bin/python gui.py --app cull` (`--app edit` for the editor; add `--lang en` to pick the interface language).
- Check the environment: `python3 tools/setup_env.py --check`.

## Source layout

```
cull.py        Photo Cull: reading images, scoring, AI review, XMP, organizing, the report
editor.py      Photo Edit: decoding, rendering pipeline, LUTs, auto adjust, export
gui.py         Local web server: serves the pages in web/ and the /api endpoints
i18n.py        Languages: loads locales/; t("key") returns text in the current language
web/           Front end: common/ (design tokens tokens.css, i18n.js), cull/, edit/, report/
locales/       Language packs: zh-CN.json, en.json, ja.json
luts/          Built-in LUTs (sRGB)
tools/         setup_env.py (environment), make_release.py (packages), check_i18n.py (language-pack check)
```

## Conventions
- **Front end and back end are separate**: no HTML in Python. Change the interface in `web/` and reload the browser — no restart needed.
- **Every user-visible string lives in the language packs**: `t("group.key")` in Python, `T("group.key")` or `data-i18n="group.key"` in the web pages. Add new strings in all three languages; if you don’t speak one, use English for now and say so in the PR so someone can translate it. Run `python3 tools/check_i18n.py` before submitting.
- **Colors, fonts and radii come only from the variables in `web/common/tokens.css`**; don’t hard-code colors in pages.
- Photo Cull (`cull.py`) and Photo Edit (`editor.py`) are independent programs sharing `gui.py`; neither should depend on the other’s internals.
- Editor preview and export must use the same rendering pipeline; check that they match after a change.
- Never overwrite a user’s originals: confirm paths before writing, and always delete via the Trash.
- Store codes, not sentences, in saved data (e.g. issue flags are stored as `blur`, `clip_high:0.05` and translated for display), so old results still display after switching language.
- Don’t commit `.venv`, `dist/`, personal photos or API keys.

## Translations and new languages
- To fix a translation, edit `locales/<lang>.json`. Don’t rename keys, and keep `{placeholders}` as they are.
- To add a language, copy `locales/en.json` to `locales/<code>.json` and translate it, register it in `LANGS` in `i18n.py`, and add a review prompt for it to `AI_PROMPTS` in `cull.py` (asking the model to write its comments in that language). Run `python3 tools/check_i18n.py`.
- The README exists in three languages (`README.md`, `README.en.md`, `README.ja.md`); please keep them in step when features change.

## LUTs
- `luts/` holds the built-in LUTs, all in an sRGB working space. New built-in LUTs follow the naming rule “camera + film simulation (sRGB)” for Fujifilm and “Leica Look + filter (sRGB)” for Leica, with the working space noted in the file header.
- LUTs just for yourself need no code change: use “Add LUT…” in Photo Edit.

## AI models
- Selectable models are listed in `PROVIDERS` in `cull.py`, vision-capable models only. When updating the list, note the date and source you checked.
- A new provider that speaks OpenAI Chat Completions usually needs no code — users can pick “Custom” and enter its URL. For widely used ones, add an entry to `PROVIDERS` with `api: "chat"`.

## Welcome directions
- Visual design and interaction (see [docs/GUI设计方向.md](docs/GUI设计方向.md), in Chinese).
- Translations into more languages.
- Wider RAW and EXIF support (Fujifilm RAF needs real sample files).
- Testing on real Windows machines (so far only static checks).
- Better data for auto-adjust styles and lens vignetting.
- HDR display and metering (planned).
- Tests and documentation (test scripts will move into `tests/`).

See the roadmap in [docs/工作记录.md](docs/工作记录.md) and [docs/测试计划.md](docs/测试计划.md) (both Chinese). For larger changes, please update [CHANGELOG.md](CHANGELOG.md) too.
