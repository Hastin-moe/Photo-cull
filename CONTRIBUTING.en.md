# Contributing

[简体中文](CONTRIBUTING.md) · **English** · [日本語](CONTRIBUTING.ja.md) · [한국어](CONTRIBUTING.ko.md)

Improvements, fixes, translations and ideas are welcome. The project is MIT-licensed, and by submitting you agree that your contribution is released under the MIT License too. Issues and PRs may be written in Chinese, English, Japanese or Korean.

## How to contribute
1. Open an issue describing what you’d like to do (small fixes can go straight to a PR).
2. Fork the repository and branch from `main`, e.g. `feat/xxx`, `fix/xxx`, `i18n/xx`.
3. Run the tests (`python3 tests/run.py`) and try the affected features yourself. In the PR, describe what changed, why, how you verified it, and whether existing results are affected.
4. Open a pull request. One PR, one change.

## Running locally
- macOS: double-click `安装环境.command` (install environment), then `启动筛选.command` (Photo Cull) / `启动编辑.command` (Photo Edit).
- Windows: `安装环境.bat`, `启动筛选.bat`, `启动编辑.bat`.
- Or from a terminal: `python3 tools/setup_env.py`, then `.venv/bin/python gui.py` (one window; `--start edit` opens Photo Edit first, `--app cull|edit` runs only one, `--lang en` picks the interface language).
- Command line only: `.venv/bin/python cull.py "photo folder"` (same as `python3 -m photo_cull.cull`).
- Check the environment: `python3 tools/setup_env.py --check`.

## Tests
`python3 tests/run.py` runs every `tests/test_*.py` in its own process, with `HOME` pointed at a temporary folder (your own settings are not touched). Test photos are generated in code (`tests/fixtures.py`); AI review is tested against a fake local endpoint, so nothing is charged. Run one file with `python3 tests/run.py test_scoring.py`. Please add a test with every fix or feature.

## Source layout

```
photo_cull/
  version.py     version number (the only place it is written)
  paths.py       fixed locations: bundled resources (web/, locales/, luts/) and ~/.photo-cull
  i18n.py        languages: loads locales/; t("key") returns text in the current language
  imaging/       reading images and EXIF — formats, TIFF-structured RAW, Fujifilm RAF, previews (shared by cull and edit)
  cull/          Photo Cull
    model.py       Photo data and the results.json format (schema 2; older results are converted on load)
    analysis.py    sharpness, exposure, faces / eyes / smiles
    grouping.py    bursts and repeated shots of a scene
    scoring.py     10-point scoring, highlight weights, picks / burst moments / usable
    ai/            providers.py (models and API calls), prompts.py (prompts per language), review.py
    xmp.py         sidecar and embedded-JPEG XMP
    organize.py    output folders and renaming; trash.py — moving to the Trash
    report.py      results.json / csv / report.html
    pipeline.py    the stages in order; cli.py — command-line options
  edit/          Photo Edit: color, logspace, lut3d, refs / styles (LUT references, user LUTs), presets, curves,
                 decode, render, auto, session, records (edit history), library, export
  server/        local web server: settings, jobs, apps (the two programs), pages, actions (report actions),
                 handler (/api), runtime (one window), main
cull.py · gui.py · desktop.py   entry points (command line, local web UI, Mac app)
web/           front end: common/ (design tokens tokens.css, i18n.js, shell.js), cull/, edit/, report/, shell/
locales/       language packs: zh-CN.json, en.json, ja.json, ko.json
luts/          built-in LUTs (sRGB)
tests/         tests (run.py, fixtures.py, test_*.py)
tools/         setup_env.py (environment), build_mac_app.py (Mac app), make_release.py (packages), check_i18n.py (language-pack check)
docs/          work log, structure notes, design direction, test plan (Chinese)
```

## Conventions
- **Front end and back end are separate**: no HTML in Python. Change the interface in `web/` and reload the browser — no restart needed.
- **Every user-visible string lives in the language packs**: `t("group.key")` in Python, `T("group.key")` or `data-i18n="group.key"` in the web pages. Add new strings in all four languages; if you don’t speak one, use English for now and say so in the PR so someone can translate it. Run `python3 tools/check_i18n.py` before submitting.
- **Colors, fonts and radii come only from the variables in `web/common/tokens.css`**; don’t hard-code colors in pages.
- `photo_cull/cull` and `photo_cull/edit` must not import each other; what both need goes in `photo_cull/imaging`.
- Scores are kept to 0.1 internally and shown as whole numbers; XMP stars are always derived from the score (`model.xmp_stars`), never stored separately.
- Editor preview and export must use the same rendering pipeline; check that they match after a change.
- Never overwrite a user’s originals: confirm paths before writing, and always delete via the Trash.
- Store codes, not sentences, in saved data (e.g. issue flags are stored as `blur`, `clip_high:0.05`; categories as `pick`, `moment`…), so old results still display after switching language. When the results format changes, bump `SCHEMA` in `cull/model.py` and convert the old format in `photos_from_json`.
- Don’t commit `.venv`, `dist/`, personal photos or API keys.

## Translations and new languages
- To fix a translation, edit `locales/<lang>.json`. Don’t rename keys, and keep `{placeholders}` as they are.
- To add a language, copy `locales/en.json` to `locales/<code>.json` and translate it, register it in `LANGS` in `photo_cull/i18n.py`, and add a review prompt for it to `AI_PROMPTS` in `photo_cull/cull/ai/prompts.py` (asking the model to write its comments in that language). Run `python3 tools/check_i18n.py`.
- The README exists in four languages (`README.md`, `README.en.md`, `README.ja.md`, `README.ko.md`); please keep them in step when features change.

## LUTs
- `luts/` holds the built-in LUTs, all in an sRGB working space. New built-in LUTs follow the naming rule “camera + film simulation (sRGB)” for Fujifilm and “Leica Look + filter (sRGB)” for Leica, with the working space noted in the file header.
- LUTs just for yourself need no code change: use “Add LUT…” in Photo Edit.

## AI models
- Selectable models are listed in `PROVIDERS` in `photo_cull/cull/ai/providers.py`, vision-capable models only. When updating the list, note the date and source you checked.
- A new provider that speaks OpenAI Chat Completions usually needs no code — users can pick “Custom” and enter its URL. For widely used ones, add an entry to `PROVIDERS` with `api: "chat"`.

## Welcome directions
- Visual design and interaction (see [docs/GUI设计方向.md](docs/GUI设计方向.md), in Chinese).
- Translations into more languages.
- Better detectors for faces, eyes and smiles (the highlight weights depend on them).
- Wider RAW and EXIF support (Fujifilm RAF needs real sample files).
- Testing on real Windows machines (so far only static checks).
- Better data for auto-adjust styles and lens vignetting.
- HDR display and metering (planned).

See the roadmap in [docs/工作记录.md](docs/工作记录.md) and [docs/测试计划.md](docs/测试计划.md) (both Chinese). For larger changes, please update [CHANGELOG.md](CHANGELOG.md) too.
