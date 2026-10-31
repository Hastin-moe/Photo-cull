# コントリビュート

[简体中文](CONTRIBUTING.md) · [English](CONTRIBUTING.en.md) · **日本語** · [한국어](CONTRIBUTING.ko.md)

改善、修正、翻訳、アイデアを歓迎します。本プロジェクトは MIT ライセンスで、投稿した内容も MIT ライセンスで公開されることに同意したものとみなします。Issue や PR は中国語・英語・日本語・韓国語のどれでもかまいません。

## 参加のしかた
1. まず Issue でやりたいことを説明してください（小さな修正は直接 PR でもかまいません）。
2. リポジトリをフォークし、`main` からブランチを切ります。例：`feat/xxx`、`fix/xxx`、`i18n/xx`。
3. テスト（`python3 tests/run.py`）を実行し、変更した機能を実際に試してください。PR には、何を・なぜ変えたか、どう確認したか、既存の結果に影響があるかを書いてください。
4. Pull Request を出します。1 つの PR には 1 つの変更だけにしてください。

## ローカルでの実行
- macOS：`安装环境.command`（環境のインストール）をダブルクリックし、`启动筛选.command`（写真セレクト）／`启动编辑.command`（写真編集）を開きます。
- Windows：`安装环境.bat`、`启动筛选.bat`、`启动编辑.bat`。
- コマンドラインでは：`python3 tools/setup_env.py` のあと `.venv/bin/python gui.py`（ひとつのウィンドウ。`--start edit` で写真編集を先に表示、`--app cull|edit` で片方だけ、`--lang ja` で表示言語を指定）。
- コマンドラインだけで使う：`.venv/bin/python cull.py "写真フォルダー"`（`python3 -m photo_cull.cull` と同じ）。
- 環境の確認：`python3 tools/setup_env.py --check`。

## テスト
`python3 tests/run.py` は `tests/test_*.py` をひとつずつ別プロセスで実行し、`HOME` を一時フォルダーに向けます（ご自身の設定には触れません）。テスト用の写真はコードで生成し（`tests/fixtures.py`）、AI 講評はローカルの偽 API でテストするので費用はかかりません。1 ファイルだけ実行するには `python3 tests/run.py test_scoring.py`。修正や機能追加のときはテストも追加してください。

## ソースの構成

```
photo_cull/
  version.py     バージョン番号（書くのはここだけ）
  paths.py       固定の場所：同梱リソース（web/、locales/、luts/）と ~/.photo-cull
  i18n.py        多言語：locales/ を読み込み、t("キー") で現在の言語の文言を返す
  imaging/       画像と EXIF の読み込み：形式、TIFF 構造の RAW、富士フイルム RAF、プレビュー（セレクトと編集で共用）
  cull/          写真セレクト
    model.py       写真データと results.json の形式（schema 2。古い結果は読み込み時に変換）
    analysis.py    シャープさ、露出、顔／目／笑顔
    grouping.py    連写と同じシーンの撮り直しのグループ分け
    scoring.py     10 点満点の点数、決定瞬間の重み、セレクト／連写の決定瞬間／使える
    ai/            providers.py（モデルと API 呼び出し）、prompts.py（言語ごとのプロンプト）、review.py
    xmp.py         サイドカー XMP と JPEG 埋め込み XMP
    organize.py    出力の整理と名前変更。trash.py はゴミ箱への移動
    report.py      results.json／csv／report.html
    pipeline.py    各段階を順番に実行。cli.py はコマンドラインのオプション
  edit/          写真編集：color、logspace、lut3d、refs／styles（LUT の参照、ユーザー LUT）、presets、curves、
                 decode、render、auto、session、records（編集の記録）、library、export
  server/        ローカル Web サーバー：settings、jobs、apps（2 つのプログラム）、pages、actions（レポートでの操作）、
                 handler（/api）、runtime（ひとつのウィンドウ）、main
cull.py · gui.py · desktop.py   入口（コマンドライン、ローカル Web 画面、Mac アプリ）
web/           フロントエンド：common/（デザイン変数 tokens.css、i18n.js、shell.js）、cull/、edit/、report/、shell/
locales/       言語パック：zh-CN.json、en.json、ja.json、ko.json
luts/          内蔵 LUT（sRGB）
tests/         テスト（run.py、fixtures.py、test_*.py）
tools/         setup_env.py（環境構築）、build_mac_app.py（Mac アプリ）、make_release.py（パッケージ作成）、check_i18n.py（言語パックの確認）
docs/          作業記録、構成メモ、デザインの方向性、テスト計画（中国語）
```

## 約束ごと
- **フロントエンドとバックエンドを分ける**：Python に HTML を書かないでください。画面は `web/` のファイルを変更し、ブラウザーを再読み込みすれば反映されます（再起動は不要）。
- **ユーザーに見える文言はすべて言語パックへ**：Python は `t("グループ.キー")`、Web ページは `T("グループ.キー")` か HTML の `data-i18n="グループ.キー"`。新しい文言は 4 言語すべてに追加してください。分からない言語はひとまず英語で書き、PR にその旨を書いてください。提出前に `python3 tools/check_i18n.py` を実行してください。
- **色・フォント・角丸は `web/common/tokens.css` の変数だけを使う**。ページに色を直接書かないでください。
- `photo_cull/cull` と `photo_cull/edit` は互いに import しません。両方で使うものは `photo_cull/imaging` に置きます。
- 点数は内部では 0.1 刻み、表示は整数です。XMP の星は常に点数から換算し（`model.xmp_stars`）、別に保存しません。
- 編集のプレビューと書き出しは同じレンダリングパイプラインを使うこと。変更後は両者が一致するか確認してください。
- ユーザーの元ファイルは決して上書きしない：書き込む前にパスを確認し、削除は必ずゴミ箱経由で。
- 保存するデータには文章ではなくコードを入れる（問題の印は `blur`、`clip_high:0.05`、分類は `pick`、`moment`… として保存し、表示時に翻訳）。言語を切り替えても古い結果が正しく表示されます。結果の形式を変えたら `cull/model.py` の `SCHEMA` を 1 つ上げ、`photos_from_json` で古い形式を変換してください。
- `.venv`、`dist/`、個人の写真、API キーはコミットしないでください。

## 翻訳と新しい言語
- 訳を直すときは `locales/<言語>.json` を編集します。キー名は変えず、`{プレースホルダー}` はそのままにしてください。
- 新しい言語を追加するときは、`locales/en.json` を `locales/<言語コード>.json` にコピーして翻訳し、`photo_cull/i18n.py` の `LANGS` に登録します。さらに `photo_cull/cull/ai/prompts.py` の `AI_PROMPTS` にその言語の講評プロンプト（その言語で講評を書くよう指示するもの）を追加し、`python3 tools/check_i18n.py` を実行してください。
- README は 4 言語あります（`README.md`、`README.en.md`、`README.ja.md`、`README.ko.md`）。機能を変えたらできるだけ揃えて更新してください。

## LUT
- `luts/` は内蔵 LUT で、作業空間はすべて sRGB です。新しく内蔵する LUT は、富士フイルムは「機種 + フィルムシミュレーション名 (sRGB)」、ライカは「Leica Look + フィルター名 (sRGB)」と命名し、ファイルの先頭に作業空間を書いてください。
- 自分だけで使う LUT はコードの変更は不要です。写真編集の「LUT を追加…」を使ってください。

## AI モデル
- 選べるモデルは `photo_cull/cull/ai/providers.py` の `PROVIDERS` にあり、画像を扱えるモデルだけを載せています。一覧を更新するときは確認した日付と情報源を書いてください。
- OpenAI Chat Completions に対応した新しいサービスは、たいていコードの変更は不要です（ユーザーが「カスタム」を選んで URL を入力すれば使えます）。よく使われるものは `PROVIDERS` に `api: "chat"` で追加してください。

## 歓迎する方向
- 画面のビジュアルと操作（[docs/GUI设计方向.md](docs/GUI设计方向.md) を参照、中国語）。
- ほかの言語への翻訳。
- 顔・目・笑顔の検出の改善（決定瞬間の重みはこれに依存します）。
- RAW と EXIF の対応拡大（富士フイルム RAF は実際のサンプルが必要）。
- Windows 実機でのテスト（今のところ静的なチェックのみ）。
- 自動補正の方式とレンズの周辺減光のデータ改善。
- HDR 表示と測光（計画中）。

ロードマップは [docs/工作记录.md](docs/工作记录.md) と [docs/测试计划.md](docs/测试计划.md)（いずれも中国語）にあります。大きな変更では [CHANGELOG.md](CHANGELOG.md) も更新してください。
