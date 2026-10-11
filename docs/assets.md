# 画像アセットの管理（SVG / PNG / 生成画像）

カスタムイラストや複雑な図を使いつつ、文字・比較データの編集性と権利の追跡可能性を守るための運用。

## 原則

- **図の中心データ（数値・表・比較・構成要素の名前）は画像に焼き込まない。** 表・グラフ・構成図は PowerPoint のネイティブオブジェクトで作る（日本語テーマ規約 J-7、ネイティブ図 #6）。画像は概念イラスト・写真・装飾に使う。
- 画像に文字を入れる場合は `contains_text: true` と `text_reason`（画像化してよい理由）を書く。SVG の `<text>` は自動検出する。PNG/JPEG の文字は自動検出できないため PR レビューで確認する。
- 画像生成（ChatGPT 等）は**チャットで人が明示的に指示したときだけ**行う。エージェントが自動で生成・課金しない。生成指示は `assets/prompts/*.md` に保存する。
- 画像は content.yaml の `asset_ref` から参照する。見せ方（`asset_fit: contain | cover`）は design.yaml。画像を差し替えても content.yaml の文言・数値は変わらない。

## manifest（`<deck>/assets/manifest.yaml`）

スキーマ: `schemas/asset-manifest.schema.json`。`assets/` 内の画像・補助ファイルはすべて manifest に登録するか、`prompt_file` / `source_file` として参照されていなければならない。

| 項目 | 内容 |
|---|---|
| `path` / `sha256` | content からの相対パスと実ファイルの sha256（差し替え時は必ず更新） |
| `media_type` / `width` / `height` / `transparent` | 実体と一致を検査（寸法・比率・透過） |
| `alt` | 代替テキスト（PPTX の画像に設定） |
| `contains_text` / `text_reason` | 画像内の文字の有無と理由 |
| `origin.type` | `authored`（自作: `author` 必須）/ `generated`（生成: `tool`・`prompt_file` 必須、`asset_id` 任意）/ `third_party`（第三者: `source_url`・`attribution` 必須） |
| `origin.source_file` / `conversion` | HTML+CSS や元 SVG から作った場合の元ファイルと変換手順 |
| `license` / `attribution` | 自動許可は MIT・CC0-1.0・CC-BY-4.0（帰属必須）・Apache-2.0。それ以外・不明は FAIL（人がレビューして停止条件として扱う） |
| `updated` | 最終更新日 |

## 検査（`python3 scripts/assets.py <deck>...`、CI とビルドで実行）

- 未登録ファイル（出自・権利不明）、manifest の重複、参照先の欠落
- sha256 不一致（差し替え後の manifest 更新漏れ）
- ライセンス許可リスト外・不明、出自ごとの必須項目（帰属・生成指示・取得元 URL・作者・変換手順）
- 寸法・比率の不一致、透過宣言と実体の不一致（PNG の色タイプ・tRNS）、CMYK、ラスタの解像度不足（長辺 1600px 未満）
- SVG の外部参照（`href`・`url()`・`@import`）、`<script>` / `<foreignObject>`、宣言のない `<text>`

## ビルドでの扱い

- `scripts/build` は描画前にアセット検査を実行し、違反があれば止める。
- 画像スライド（`type/layout: illustration`）は、manifest の寸法から配置を計算し（contain は比率を保って領域内、cover は領域を埋めて端を切る）、ネイティブの画像オブジェクトとして置く。本文は画像と重なるため置けない（注記は `notes`）。
- pptxgenjs は SVG の PNG フォールバックに SVG 本文を入れるため、ビルドで LibreOffice により実際の PNG を生成して差し替える（SVG 非対応の閲覧環境でも表示できる）。
- `manifest.json` の `assets` に使用画像の path・sha256・ライセンス・出自を記録する。

## HTML+CSS からの変換

自動変換は実装しない（ブラウザ依存で再現性が低く、ヘッドレスブラウザの追加依存が必要なため）。必要な場合は、元 HTML を `assets/src/` に置き、書き出した SVG/PNG を登録して `origin.source_file` と `origin.conversion`（使ったツール・版・手順）を記録する。

## 画像の差し替え手順

1. 同じ `path` に新しい画像を置く（比率が変わる場合は design の `asset_fit` も確認）。
2. manifest の `sha256`・`width`・`height`・`transparent`・`updated`（出自が変われば `origin`・`license`）を更新する。
3. `python3 scripts/assets.py <deck>` → `scripts/build ...` を実行し、`content_sha256` が変わらないことと PNG を目視確認する。
