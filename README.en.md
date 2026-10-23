# photo-cull

[简体中文](README.md) · **English** · [日本語](README.ja.md)

photo-cull is two **independent programs**, each with its own launcher. Run either one, or both side by side:

- **Photo Cull** (double-click `启动筛选.command` on macOS / `启动筛选.bat` on Windows): technical culling on your own computer — focus, blur, exposure, faces and closed eyes, plus grouping of bursts and repeated shots of the same scene. Shortlisted photos can then get an aesthetic review from **Claude, ChatGPT, Grok, Gemini, DeepSeek**, or any OpenAI-compatible vision model (Qwen, Kimi, OpenRouter, a local Ollama, …). **Ratings and color labels** are written to XMP, which Lightroom Classic and Capture One both read, and you get an interactive web report.
- **Photo Edit** (double-click `启动编辑.command` / `启动编辑.bat`; basic): global adjustments with curves, a histogram and waveform scopes; apply `.cube` LUTs and Lightroom/Photoshop XMP presets; export JPEG or 16-bit TIFF. Supports Leica DNG, Panasonic DNG, every Sony ARW and Fujifilm RAF.

> The launcher files keep their Chinese names: `安装环境` = install environment, `启动筛选` = start Photo Cull, `启动编辑` = start Photo Edit.

**Interface languages**: 简体中文, English and 日本語 — switch at the top right of either program (both stay in sync). The report, the run log and AI comments follow the chosen language. On first launch the language is picked from your browser.

**RAW+JPEG pairing**: a RAW (DNG, ARW, RAF…) and a JPEG with the same name in the same folder are treated as one photo. Ratings are written to both; deleting removes both.

**Safety**
- Image data is never modified.
  - RAW ratings go into a sidecar `same-name.xmp`; the RAW file is untouched.
  - JPEG ratings go into the embedded XMP segment (metadata only). After writing, the image data — including any multi-picture previews from the camera — is compared byte for byte, and the write is abandoned on any mismatch.
- Existing XMP keeps everything except rating and label (develop settings, keywords…). Before the first change to a sidecar written by another app, a `.xmp.cull-bak` backup is made.
- “Delete” only moves files to the **Trash / Recycle Bin**, so you can restore them.
- Organizing **copies** by default and leaves the original folder alone; files are moved only if you choose “Move”.

## Install (once)

**macOS**: double-click `安装环境.command` (or just double-click a launcher — the first run installs automatically; both programs share one environment). Requires Python 3.9 or later ([python.org](https://www.python.org/downloads/)).

**Windows (beta)**: double-click `安装环境.bat`, then use `启动筛选.bat` / `启动编辑.bat`.
- The first run prepares everything: if Python is missing, press Enter to install Python 3.12 for the current user with Windows’ built-in winget; dependencies then download in about 3–5 minutes. After that, launchers open straight away.
- If Windows shows “Windows protected your PC”, click “More info → Run anyway”.
- Requires 64-bit Windows 10/11 (x64). Windows on ARM isn’t supported yet (the RAW decoding library has no ARM build).
- Windows uses its own `.venv-win`, separate from macOS’s `.venv`, so one folder can be shared between both systems.

### Setting up a new machine

On a new computer, or when the environment breaks, double-click **`安装环境.command`** (macOS) / **`安装环境.bat`** (Windows). It:

1. finds Python (on Windows it can install it with winget);
2. creates a private environment inside the tool folder (`.venv` on macOS, `.venv-win` on Windows) without touching other Python installs;
3. installs `requirements.txt`, trying the official PyPI first and switching to a mirror if PyPI can’t be reached within 4 seconds;
4. checks that each component actually imports (numpy, Pillow, OpenCV, rawpy/LibRaw and ExifRead are required; HEIC, Trash and AI review are optional), checks the bundled LUTs and the settings folder, and prints the result.

Afterwards the launchers only run a quick check before opening, and install new dependencies automatically when `requirements.txt` changes.

Options (on Windows: `安装环境.bat <options>`):

| Option | Effect |
|---|---|
| `--check` | Check only, don’t install |
| `--recreate` | Delete and rebuild the environment (after it breaks or Python changes) |
| `--mirror tuna` / `aliyun` / `ustc` / `pypi` / URL | Choose the pip index (default `auto`) |
| `--wheels <folder>` | Install offline from a local folder |
| `--download <folder> --target win / mac-arm / mac-intel / linux` | On a machine with internet, download packages for the target system (with `--target-python 3.12`), then install them offline with `--wheels` |

To install by hand on macOS, open Terminal:

```bash
cd ~/Desktop/照片筛选工具
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Using the interface

Double-click **`启动筛选.command`** to open Photo Cull in your browser, or **`启动编辑.command`** for Photo Edit. Each has a link at the top right (“Photo Edit ↗” / “Photo Cull ↗”) that opens the other program in a new tab if it is running, or tells you which launcher to start.

Photo Cull:

1. Click “Choose…” and pick a photo folder. If the folder was culled before, “Load the last results for this folder” lets you continue reviewing.
2. Choose “Local only” or “Local + AI review”. For AI review:
   - pick a provider: Claude, ChatGPT, Grok, Gemini, DeepSeek or Custom;
   - pick a model from the list (each is marked recommended / cheaper / strongest), or choose “Other” and type one;
   - enter that provider’s API key; for Custom, also enter the endpoint URL.
3. Turn on “Dry run” the first time to see how well it judges.
   Turn on “Organize output” to sort and rename after rating (see “Organizing output” below).
4. Click “Start”. Before any AI call, a dialog shows how many photos will be sent and the estimated usage; nothing is sent until you confirm.
5. The report appears in the window. In it you can:
   - click ★ to change a rating or ✕ to reject — changes are written to the RAW and the JPEG immediately;
   - tick the box on a photo and click “Delete selected”, or “Delete all rejects”; paired files and their XMP go to the Trash together;
   - click “Organize by current ratings” after reviewing to sort into the output folder using your edited ratings;
   - click “Edit” on a photo to open it in Photo Edit in a new tab (Photo Edit must be running).

Everything runs locally on 127.0.0.1 and is not reachable from other computers. Close a program’s terminal window to quit it.
If macOS says the app “can’t be opened because it is from an unidentified developer”: right-click the launcher → Open → Open.

## Models for AI review

| Provider | Models (first is the default) | Get an API key at | Environment variable |
|---|---|---|---|
| Claude | `claude-sonnet-5-5` (recommended), `claude-haiku-5-5` (cheaper), `claude-opus-5-5` (stronger), `claude-fable-5-1` (strongest, most expensive) | console.anthropic.com | `ANTHROPIC_API_KEY` |
| ChatGPT | `gpt-6.1-sol` (recommended), `gpt-6-luna` (cheaper), `gpt-6-astra` (strongest), `gpt-5.5` (previous) | platform.openai.com | `OPENAI_API_KEY` |
| Grok | `grok-4.7` | console.x.ai | `XAI_API_KEY` |
| Gemini | `gemini-3.8-flash` (recommended), `gemini-3.6-flash`, `gemini-3.5-flash-lite` (cheaper), `gemini-4-argon` (strongest) | aistudio.google.com | `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) |
| DeepSeek | `deepseek-flash` | platform.deepseek.com | `DEEPSEEK_API_KEY` |
| Custom | your choice | your provider | `PHOTO_CULL_CUSTOM_API_KEY` |

- The list was checked in October 2026 and only includes models that accept images. When a provider releases a new model, choose “Other (type a name)”.
- **DeepSeek**: only `deepseek-flash` accepts images right now (`deepseek-v4-pro` is text-only), so it is the only option.
- **Custom (OpenAI-compatible)**: enter an endpoint and a model name to use any service that supports image input through Chat Completions, for example:
  - OpenRouter `https://openrouter.ai/api/v1`
  - Qwen (international) `https://dashscope-intl.aliyuncs.com/compatible-mode/v1` (e.g. `qwen-vl-max`)
  - Kimi `https://api.moonshot.ai/v1`
  - a local Ollama `http://127.0.0.1:11434/v1` or LM Studio `http://127.0.0.1:1234/v1` (no key needed)

  Check each provider’s docs for exact URLs and model names. DeepSeek and Custom use plain HTTP and need no extra SDK.
- API keys are pay-as-you-go and separate from chat subscriptions (Claude Pro, ChatGPT Plus…).
- Photos already reviewed aren’t charged again: the cache is keyed by provider + model + language + image. Switching the interface language reviews again once so the comments are in the new language.
- If the first 3 calls in a row fail (wrong key or model name, no credit…), AI review stops automatically.

## Command line

```bash
# Local culling only, free
.venv/bin/python cull.py "/Volumes/SSD/2026-10-19 street"

# Dry run first: report only, no ratings written
.venv/bin/python cull.py "photo folder" --dry-run

# Claude review
export ANTHROPIC_API_KEY="…"
.venv/bin/python cull.py "photo folder" --ai

# ChatGPT / Grok / Gemini / DeepSeek
.venv/bin/python cull.py "photo folder" --ai --provider openai     # OPENAI_API_KEY
.venv/bin/python cull.py "photo folder" --ai --provider grok       # XAI_API_KEY
.venv/bin/python cull.py "photo folder" --ai --provider gemini     # GEMINI_API_KEY
.venv/bin/python cull.py "photo folder" --ai --provider deepseek   # DEEPSEEK_API_KEY

# Any OpenAI-compatible endpoint (e.g. OpenRouter)
export PHOTO_CULL_CUSTOM_API_KEY="…"
.venv/bin/python cull.py "photo folder" --ai --provider custom --model <model> --base-url https://openrouter.ai/api/v1

# Report, log and AI comments in English (zh-CN / en / ja)
.venv/bin/python cull.py "photo folder" --lang en

# After rating, move rejects (with paired files) to the Trash
.venv/bin/python cull.py "photo folder" --trash-rejects

# Organize: Keep/Rejected × JPEG/RAW folders, renamed (copies by default; add --move to move)
.venv/bin/python cull.py "photo folder" --organize "output folder" --by-result --by-format --rename
```

The report is written to `photo folder/photo-cull-report/report.html`, next to `results.csv` for Numbers or Excel. A report opened directly from disk is read-only; use the program to change ratings or delete.

## How results map to your software

| Result | Rating | Label | Meaning |
|---|---|---|---|
| Pick | 4–5★ | Green | Only given by AI review; never appears without it |
| Usable | 3★ | Yellow | Shortlisted but not outstanding |
| Burst alternate | up to 2★ | none | Not the best frame of its burst or repeated shots |
| Rejected | Reject (Rating −1) | Red | Badly out of focus, over- or underexposed; also red when the AI gives 1 star |

**Where ratings are written**

| File | Written to |
|---|---|
| RAW (DNG/ARW…) | The same-name `.xmp` sidecar, shared by a RAW+JPEG pair |
| JPEG | Embedded XMP (turn off “Also embed XMP in JPEGs” or use `--no-jpeg-embed` to skip) |
| Standalone HEIC/HIF/PNG | Not by default; turn on “Write XMP sidecars for standalone JPEG/HEIC too” for Capture One |

**Lightroom Classic**
- Newly imported photos: ratings are read on import.
- Photos already in the catalog:
  1. select them and press ⌘S (Save Metadata to File) so the catalog’s latest changes are in the files;
  2. run photo-cull;
  3. select them again and choose Metadata → Read Metadata from Files.
- If RAW+JPEG were imported as one photo (Lightroom’s default), Lightroom shows only the RAW’s rating. To see both, turn on “Treat JPEG files next to raw files as separate photos” in Preferences → General before importing.

**Capture One**
- In Preferences → Image → Metadata, set XMP sidecar auto sync to “Full sync” or “Load”. Then open the folder, or run “Reload metadata from XMP” on the images (menu names vary by version).

**Deleting and catalogs**
- Photos already in Lightroom or Capture One show as missing after being deleted here; remove them in that app too.
- Deleted the wrong one? Open the Trash and drag the files back.

## Organizing output

After rating, photos can be organized into an output folder (`photo folder/Organized` if left empty). Each option can be turned on separately:

- **Split into Keep / Rejected**: photos marked reject (X) go to “Rejected”, everything else to “Keep”. Folder names follow the interface language at the time you organize (中文 `保留`/`淘汰`, English `Keep`/`Rejected`, 日本語 `採用`/`不採用`); later updates from the report reuse the same names.
- **Then split into JPEG / RAW**: HEIC/PNG go with JPEG.
- **Rename**: prefix the name with `rating_camera_`, camera from EXIF, e.g.
  `4_ILCE-1M2_DSC01234.ARW`, `3_LEICA-M11-D_L1003467.DNG`, `X_X-T5_DSCF0001.RAF`.
  Rejects get `X_`, unrated `0_`; spaces and special characters in the camera name become `-`.
  **Only files in the output folder are renamed**; originals keep their names.

With both levels on:

```
Organized/
├── Keep/
│   ├── JPEG/  4_ILCE-1M2_DSC01234.JPG
│   └── RAW/   4_ILCE-1M2_DSC01234.ARW  4_ILCE-1M2_DSC01234.xmp
└── Rejected/
    ├── JPEG/
    └── RAW/
```

**Copy or move**
- **Copy** (default): the original folder stays as it is and the output holds copies (twice the space). Later rating changes in the report move the copy to the matching folder and name; deleting a photo also sends its copy to the Trash. Organizing again never makes a second copy.
- **Move**: photos leave the original folder. Rating changes and deletions in the report then apply to the files in their new place. Photos already in Lightroom / Capture One will show as missing and need their folder relocated there.

**Details**
- Paired RAW and JPEG travel together; a RAW’s `.xmp` sidecar follows it and is renamed with it, so Lightroom / Capture One see the ratings when importing the output folder.
- Name clashes get `-2`, `-3`…; both files of a pair share the same suffix.
- In dry-run mode the plan is listed but nothing is copied or moved.
- Unreadable and deleted photos are skipped.
- The output folder may live inside the photo folder: with “Include subfolders” on, the next cull skips it.

## Common options

| Option | Effect |
|---|---|
| `-r` | Include subfolders |
| `--dry-run` | Report only, no ratings written |
| `--no-xmp` | Report only |
| `--no-jpeg-embed` | Leave JPEG files alone; write RAW sidecars only |
| `--ai` | AI review for shortlisted photos |
| `--provider claude / openai / grok / gemini / deepseek / custom` | Which provider |
| `--model` | Model name |
| `--base-url` | Endpoint for `--provider custom` |
| `--lang zh-CN / en / ja` | Language of the report, log and AI comments (default: the interface setting or system language) |
| `--ai-alts` | Also review burst alternates (costs more) |
| `--trash-rejects` | Move rejects (with paired files) to the Trash |
| `--organize [folder]` | Organize after rating; default `photo folder/Organized`; relative paths start at the photo folder |
| `--by-result` / `--by-format` | Split into Keep/Rejected and JPEG/RAW folders |
| `--rename` | Rename to `rating_camera_original` |
| `--move` | Move instead of copy |
| `--yes` | Don’t ask before calling the API or deleting |
| `--burst-gap 15` | Burst: shots at most this many seconds apart that look alike form a group |
| `--scene-gap 60` | Same scene: shots at most this many seconds apart that look very alike also group (for slower shooting, e.g. rangefinders) |
| `--similarity 0.6` | Scene similarity threshold, 0–1; higher is stricter |
| `--blur-warn 0.58` / `--blur-reject 0.75` | Blur above the first is flagged “possibly soft”; above the second, rejected |

## Notes and limits

- **Which file is analyzed**: with a paired JPEG, the JPEG (full size, in-camera colors); otherwise the RAW’s embedded preview. TIFF-based RAW (DNG, ARW) and Fujifilm RAF are read directly; formats like CR3 need rawpy.
- **Pairing**: same folder, same name, different extension (case-insensitive), e.g. `L1003467.DNG` and `L1003467.JPG`. Files in different folders are not paired.
- **Focus check**: uses a re-blur metric — blur the image again and measure how much the edges change — so it doesn’t depend on how much detail a scene has, and only the sharpest region counts, so portraits with blurred backgrounds aren’t misjudged. Default thresholds were calibrated on Leica M11-D files; other cameras may need tuning.
- **Faces and closed eyes**: OpenCV’s classic detectors — fast but rough, so they only add a hint and never reject a photo.
- **AI review**:
  - only shortlisted photos are uploaded, downsized to 1024-pixel JPEGs;
  - results are cached in `ai_cache.json`;
  - models differ in taste: treat scores as suggestions and make the final call yourself.

## Photo Edit (basic)

Double-click `启动编辑.command`, or click “Edit” on a photo in the cull report to open that photo directly. The “Cull results” button opens the folder Photo Cull processed most recently.

**Adjustments**
- Basic: temperature, tint, exposure, contrast, highlights, shadows, whites, blacks, clarity, vibrance, saturation, black & white. Double-click a slider name to reset it.
- Curves: an RGB curve and separate red/green/blue curves. Click to add a point, drag to adjust, double-click to delete.
- **Preview**: resolution follows the pixels the image actually occupies on screen (Retina included) and re-renders when the window grows. Click the preview for 1:1 screen pixels (scrollable); click again or press Esc to fit. Hide the side panels with ◧ ◨ in the title bar or the `[` `]` keys; the choice is remembered. The file list has small and large thumbnails.
- Scopes: RGB histogram (with clipped highlight/shadow percentages) and a luma waveform or RGB parade.
- “Hold to compare” shows the photo before your adjustments.
- **Auto**: pick a metering style in the toolbar menu, then click “Auto”; you can fine-tune afterwards. The styles are rules of thumb based on each maker’s metering approach and look — **not copies of in-camera algorithms**. Metering runs on the editor’s real rendering, so RAW base exposure, JPEG brightness, current white balance and any chosen lens vignetting all count.

  Each style sets **exposure** first, then the **overall tone** (the Contrast / Blacks / Whites sliders):

  | Style | Metering | Tone |
  |---|---|---|
  | Evaluative (whole frame) | 6×4 zones, brightest and darkest 15% dropped, averaged to 18% gray | Neutral: moderate black and white points, contrast unchanged |
  | Leica classic center-weighted (default) | M-body style center weighting, about 1/4 EV below 18% gray; dark scenes only partly lifted | Deep: darkest blacks, base contrast +12, never lowers contrast |
  | Leica multi-field +0.3 EV | Leica multi-field metering plus +0.3 EV | Leica look, a little airier (base contrast +8) |
  | Fujifilm center-weighted | Wider center than Leica, 18% gray; stricter highlight protection | Soft: slightly lifted blacks, base contrast −5, gentle transitions |

  Tone rules: flat, gray images get a bit more contrast, already-punchy ones get less or slightly less; contrast is judged only on the part with content (pure black and white excluded), so low-key images on black aren’t misread. Blacks only go deeper (pure black never turns gray) and whites only brighter; low-key images aren’t forced to white, high-key ones aren’t forced to black. Every style pulls exposure back a little when too much clips. Your last style is remembered.

  HDR dynamic metering is not offered yet; it will arrive together with an HDR display mode.
- **Lens vignetting**: under Basic, pick a lens and strength to simulate the optical falloff of classic Leica M lenses before in-camera correction (circular, gradual, darkest in the corners):

  | Code | Lens | Light (≈f/5.6) | Medium (≈f/2.8) | Strong (wide open) |
  |---|---|---|---|---|
  | 11874 | Summilux-M 35mm f/1.4 ASPH. (1994, pre-FLE) | −0.6 EV | −1.2 EV | −2.2 EV (f/1.4) |
  | 11699 | APO-Summicron-M 35mm f/2 ASPH. | −0.8 EV | −1.3 EV | −1.9 EV (f/2) |
  | 11141 | APO-Summicron-M 50mm f/2 ASPH. | −0.5 EV | −0.9 EV | −1.4 EV (f/2) |
  | 11672 | Summicron-M 28mm f/2 ASPH. (2016, 2nd gen) | −1.0 EV | −1.6 EV | −2.3 EV (f/2) |

  Values are how many stops darker the corners are than the center. Leica publishes falloff only as charts, so these are estimates from each lens’s design (focal length, aperture, size); wide and fast lenses start falling off closer to the center. M bodies usually correct vignetting from the lens code; this simulates the uncorrected optics. It applies on export too; Basic → Reset clears it.
- Edits are saved automatically to `photo folder/photo-cull-report/edits/`; originals are never modified. “Copy settings / Paste settings” moves adjustments between photos.

**Formats**
- RAW is decoded by LibRaw (rawpy): Leica DNG (M11, Q3, SL…), Panasonic DNG/RW2, every Sony ARW (uncompressed, compressed, lossless), Fujifilm RAF (X-Trans and Bayer, including compressed RAF). DNG BaselineExposure is applied.
- JPG, HEIC, TIFF and PNG can be edited too.
- If a RAW can’t be decoded (e.g. a very new camera LibRaw doesn’t know yet), the embedded preview is used instead with a notice; quality and latitude are limited then.

**Style (LUT)**
- **Built-in LUTs**: `luts/` contains 39 LUTs: 20 Fujifilm GFX film simulations (named “camera + film simulation (sRGB)”, e.g. `GFX50S PROVIA (sRGB)`) and 19 Leica Looks (named “Leica Look + filter (sRGB)”, e.g. `Leica Look CHR (sRGB)`). **All use an sRGB working space**: apply them to images already in sRGB, not to Log or linear footage. They were collected from public sources; brand names only describe the style. They work on any computer you copy the folder to (Windows too), because edits store the built-in LUT’s name rather than a path on this machine.
- **Your own LUTs**: under Style (LUT), click “Add LUT…” and choose one or more `.cube` files. They are checked, then stored in `~/.photo-cull/luts` (kept across upgrades) and listed under “My LUTs”; hover an entry and click × to remove it.
- Search and click a LUT to apply it; the amount is adjustable. To use another library, click “Choose…” and pick a folder; “Built-in” switches back. An external library lists all its LUTs and presets.
- **Input space**: always treated as sRGB, matching the in-camera look of Sony “ST” / Leica “STD”.
  - JPEG: JPEGs shot in ST/STD match what the LUTs were designed for.
  - RAW: the editor’s standard rendering approximates that look before the LUT.
- Camera Log conversion (S-Log3 and others) is disabled for now (kept in code: `ENABLE_LOG` in `editor.py`).
- The editor can also decode Adobe color tables (RGBTable / LookTable) in XMP presets.

**Export**
- JPEG (adjustable quality, with sRGB profile and capture data) or 16-bit TIFF; full size, or long edge 6000 / 4000 / 2048.
- Exports go to a `photo-cull-export` subfolder next to the photo; the original is never overwritten.
- Export decodes at full resolution and renders in strips, so even 60-megapixel files don’t fill memory. Preview and export share one pipeline, and each strip is processed on several threads.

**Notes**
- Highlights and Shadows are global curves, not Lightroom-style local tone mapping, so large moves look different.
- Previews render in the background: a low-resolution image while dragging, full quality on release. Rendering uses all CPU cores; large JPEGs are decoded at reduced size for previews, and thumbnails use the small previews embedded in files (Sony JPEG and ARW both have them), so folders open quickly.

## For developers

The code separates front end and back end: Python (`cull.py`, `editor.py`, `gui.py`) handles photos and serves an API; the interface is HTML/CSS/JS in `web/`, and every piece of text lives in the `locales/` language packs. You can change the interface without touching Python, and the wording without touching code. See [docs/工作记录.md](docs/工作记录.md) (Chinese) for the structure and [docs/GUI设计方向.md](docs/GUI设计方向.md) (Chinese) for the design direction.

- [Changelog](CHANGELOG.md) (Chinese)
- [Contributing](CONTRIBUTING.en.md)

## License

The code is released under the [MIT License](LICENSE). The LUTs in `luts/` were collected from public sources; see `luts/说明.txt`. Contributions are welcome, including translations into new languages — see [CONTRIBUTING.en.md](CONTRIBUTING.en.md).
