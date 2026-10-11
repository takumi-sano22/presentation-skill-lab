# presentation-skill-lab

Claude Code と ChatGPT の双方から、**中身とデザインを分離**して技術系スライドを生成するためのスキル開発リポジトリ。

> **状態: Phase 1 着手中。** 上流レンダラ（`vendor/presentation-skill` v0.14.0）の固定と描画環境の doctor まで実装済みです。`content.yaml`/`design.yaml` → `outline.json` の adapter と、PPTX/PDF/PNG/静的プレビューを出す共通ビルド CLI（`scripts/build`）まで実装済みです。日本語テーマ（technical-light / technical-dark）・ネイティブ技術図・画像アセット管理・自動 QA・技術資料3種の視覚ベンチマークまで実装済みです。ChatGPT 側の実機検証（#10）とリリース判定（#11）は未実施です。`scripts/validate.py` は共通データ契約と参照の検査のみです。

## 確定事項

- **主用途:** 技術設計、アーキテクチャ図、ER 図、比較表、データ図表。
- **制作担当:** Claude Code と ChatGPT は対等。どちらから開始しても共通ソースへ収束。
- **出力:** 見栄えのよい PDF と、文字・表・基本図形が編集可能な PPTX。複雑なイラスト／SVGは画像配置を許容。
- **ライセンス:** 自作部分は MIT。外部コードを移植した場合は元ライセンス・著作権表示を維持。
- **低コスト:** LLM はコンテンツ判断・デザイン判断・必要な画像生成のみ。変換、配置、検査は原則決定論的なスクリプト。
- **公開:** 実業務データ、顧客情報、未公開コード、実際の秘密資料を公開リポジトリへ含めない。

## 技術選択

| 領域 | 選択 | 理由 |
|---|---|---|
| PPTX 主基盤 | [siril9/presentation-skill](https://github.com/siril9/presentation-skill) を固定コミットで参照 | JSON を元に編集可能 PPTX、表・グラフ、QA が既存 |
| 日本語設計規約 | [carnot-tech/jinba-consulting-pptx-skill](https://github.com/carnot-tech/jinba-consulting-pptx-skill) を選択的参照 | ストーリー、62 型カタログ、読みやすさの規約。レンダラとしては採用しない |
| 図・日本語 QA | [minorun365/minorun-marp-skill](https://github.com/minorun365/minorun-marp-skill) を設計上参考 | 図解と余白・文字サイズ検査の知見。初期は Apache 2.0 コード移植なし |
| ノード配置 | [dagrejs/dagre](https://github.com/dagrejs/dagre) を Phase 3 候補 | MIT、決定論的な有向グラフ配置 |
| 入力 | YAML + Markdown・CSV・SVG 等 | 人にもエージェントにも編集しやすい |
| 出力 | PPTX → PDF/PNG、HTML は画像ギャラリー | 異なるレンダラの二重保守を避ける |

`HTML はプレビュー` であり、HTML/CSS を PPTX に変換するという約束ではありません。HTML ベースの自由レイアウトは SVG/PNG アセットとして取り込みます。

## ディレクトリ

```text
skills/         # Claude Code / Codex 対応の SKILL.md（日本語）
schemas/        # content / design 共通データ契約
examples/       # 公開可能な架空の技術資料データ
scripts/        # 決定論的な検査・今後の変換プログラム
docs/           # ADR、アーキテクチャ、運用、計画
.github/        # CI、Issue テンプレート
```

**ソース正本:** `content.yaml` は内容だけ、`design.yaml` は見せ方だけを管理し、生成される `outline.json`・`.pptx` は編集しない。画像はソース（SVGやプロンプト）と生成物を保存し、外部参照を曖昧にしない。

## 現時点で実行できる操作

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
python3 scripts/validate.py \
  --content examples/technical-architecture/content.yaml \
  --design examples/technical-architecture/design.yaml \
  --public-repo-check
python3 -m unittest discover -s tests -v
```

PASS は**入力契約の検証結果だけ**です。スライドの完成度を証明しません。

## 生成環境（上流固定・doctor）

上流レンダラは git submodule として **固定コミット**で参照します。

| 項目 | 版・内容 |
|---|---|
| 上流 | `siril9/presentation-skill` `v0.14.0` / `efd899c5ddf866af2ce0001c4c9340af775d4d55`（`upstream.lock.json`） |
| Node | 22（Docker イメージ `node:22-bookworm`）。pptxgenjs 4.0.1 / jszip 3.10.1（上流 `package-lock.json`） |
| Python | 3.10 以上（イメージ内 3.11）、`requirements-dev.txt` |
| LibreOffice | Debian bookworm の `libreoffice-impress`（PPTX→PDF） |
| poppler | `poppler-utils`（PDF→PNG） |
| 日本語フォント | `fonts-noto-cjk`（Noto Sans CJK JP） |

第三者コード（npm 依存・上流スクリプト・LibreOffice）は**ホストで直接実行せず Docker コンテナ内で実行**します。必要なのは Docker と git のみです（WSL では Docker Desktop の WSL 統合または WSL 内 Docker Engine）。

```bash
git clone --recurse-submodules https://github.com/takumi-sano22/presentation-skill-lab.git
cd presentation-skill-lab
# 既存クローンの場合: git submodule update --init
scripts/dev.sh build                              # 描画ツールチェーンのイメージ作成
scripts/dev.sh run python3 scripts/doctor.py      # 全項目 PASS を確認
scripts/dev.sh run python3 -m unittest discover -s tests -v
```

`python3 scripts/doctor.py` をホストで実行すると、ホストに不足しているツールが FAIL として表示されます（ホストでの描画は前提にしません）。CI の `toolchain` ジョブも同じ `scripts/dev.sh` 経路で doctor を実行します。上流の更新手順は [`docs/vendor-update.md`](docs/vendor-update.md)、ビルド環境の固定と版の記録は [`docs/reproducibility.md`](docs/reproducibility.md) を参照してください。

## adapter（content/design → outline.json）

```bash
python3 scripts/adapter.py \
  --content examples/technical-architecture/content.yaml \
  --design examples/technical-architecture/design.yaml \
  --output build/outline.json
```

- 文言・数値・単位・表セル・図ラベル・出典・注記を意味項目として抽出し、変換後の outline.json から逆写像した項目と**順序込みで完全一致**しなければ FAIL（`ContentMismatch`）。
- 写像できない内容は FAIL（`UnsupportedContent`）。黙って捨てたり画像化しない。図は #6 までテキスト行（`A → B（ラベル）`）へ明示的にフォールバックし、`psl.fallback` に記録する。
- 上流 v0.14.0 に写像先がない design 指定（現状 `density`）は `psl.unapplied_design` に列挙し WARN を出す。
- 出力は正規化 JSON（キー順固定）で、同一入力なら `outline_sha256` が一致する。出力の形は `schemas/outline-adapter.schema.json`、スキーマ変更手順は [`docs/schema-versioning.md`](docs/schema-versioning.md)。
- `outline.json` は生成物。編集しても次回変換で失われる。

## 共通ビルド（PPTX / PDF / PNG / 静的プレビュー）

```bash
scripts/build \
  --content examples/technical-architecture/content.yaml \
  --design examples/technical-architecture/design.yaml
# → build/<deck_id>/ に outline.json, deck.pptx, deck.pdf, png/NN-<slide_id>.png, index.html, manifest.json
```

- Claude Code / ChatGPT / 人のいずれも同じコマンドで同じ資料を作る入口。上流レンダラ・LibreOffice は Docker イメージ内で実行する（`scripts/dev.sh build` が必要）。
- 手順: adapter（往復検査）→ 固定上流レンダラ（`psl.render.style_preset`）→ LibreOffice で PDF → pdftoppm で PNG（110 dpi）→ 静的ギャラリー `index.html`。
- 検査（FAIL で終了コード 1）: PDF ページ数＝スライド数、**PPTX 実体のテキスト／グラフ XML に全内容文字列が存在**、PDF 抽出テキストに内容文字列が存在（グラフ以外）、PDF フォントがすべて埋め込み済みで日本語フォントを含み Type 3 がない。
- 警告（manifest `checks.non_content_text`）: content 由来でない文言（レンダラの装飾ラベル等）。
- `manifest.json` に入力 hash（content/design）、adapter 版、上流 tag/commit・プリセット、Node/LibreOffice/poppler の版、PDF の埋め込みフォント、全成果物の sha256、フォールバック（例: 図のテキスト表示）を記録。
- **PASS は内容保持と描画環境の検査結果であり、デザイン品質の保証ではありません。** 全ページの PNG を目視確認してください。CI では生成物を Actions の artifact として保存します。

## 日本語テーマ（design.yaml だけで見た目を変える）

```bash
# 同じ content.yaml を暗色テーマでビルド（content_sha256 は変わらない）
scripts/build \
  --content examples/technical-architecture/content.yaml \
  --design examples/technical-architecture/design-dark.yaml \
  --out build/sample-dark
```

- `theme.name`（technical-light → 上流 arctic-minimal、technical-dark → midnight-neon を基底）と、`theme.fonts`・`theme.colors` のトークンを `scripts/render.js` が上流プリセットへ注入して描画する（上流コードは改変しない）。
- フォント名は design の値（例: Noto Sans JP）を PPTX の欧文・和文の両方に書き、描画環境では fontconfig の別名で Noto Sans CJK JP に解決する。
- 配色コントラスト（本文 4.5:1 等）を満たさないテーマは FAIL。タイトル長・泣き別れは WARN。規約と例外・出典は [`docs/design-rules.md`](docs/design-rules.md)「日本語テーマ規約」。

## ネイティブ技術図（architecture / flow）

- content.yaml の `diagram.nodes / edges`（任意で `group`・`description`・`kind`）だけから、`scripts/diagram.py` が**決定論的に配置**する（座標を LLM や人が書かない）。位相順の最長路で層を決め、2層以上をまたぐ辺は中継点で迂回、層内の並びは重心法で交差を減らす。同じ入力からは常に同じ座標になる。
- `scripts/render.js` がノード（種別ごとの形: actor=楕円、policy=六角形、datastore=円柱、tool=角丸、その他=矩形）、辺（終点に矢印、種別ごとの線種: データ=実線・制御=破線…）、辺ラベル、区画枠、凡例を **PowerPoint のネイティブ図形・線・テキスト**として描く。画像化しない。
- 配置時に検査して FAIL: ノードの重なり・領域はみ出し、辺がノードを貫通、ラベルが箱に収まらない・他と重なる、区画に区画外ノードが入る。
- ビルド時に PPTX 実体の座標を読み、全ノード図形の存在・重なり0、各辺の始点/終点が正しいノード境界にあり終点に矢印があること、content に無いノード・辺が無いことを検査（manifest `checks.diagram_errors`、交差数は `checks.diagram_crossings`）。
- 図のスライドに本文は置けない（注記は `notes`）。

## ER 図（`type/layout: er`、ADR-0002）

- content スキーマ v0.2（v0.1 の互換追加）で、エンティティの属性 `attributes[]`（`name` / `type` / `pk` / `fk: <エンティティID>.<属性名>` / `nullable`）、関係の `id`・`cardinality: {from, to}`（`1` / `0..1` / `1..N` / `0..N`）を書ける。`from` は外部キーを持つ側。fk の参照先の実在と関係の向きは `validate.py` が検査する。
- `scripts/er.py` が決定論的に配置し、`scripts/render.js` がエンティティ枠・見出し・**属性行（1行ずつ別の文字図形）**・直交の関係線・両端の多重度・関係名を **PowerPoint のネイティブ図形**で描く。文字は 10→9.5→9pt まで（9pt 未満にしない）。属性の無い v0.1 の ER は説明（description）を1行で表示する。
- ポリシーは design の `diagram_mode`: 未指定=auto（ネイティブで安全に配置できなければ SVG へ）、`native`=native_only（できなければ FAIL）、`svg`=常に SVG。
- フォールバックの判定（再現可能）: 9pt でも横幅/縦幅が足りない、列をまたぐ関係線の通路がない・線がエンティティを貫通、ラベルを重ならずに置けない、関係線の交差が 2 を超える。
- SVG 例外は content の構造から生成し、manifest `fallbacks.<Slide ID>` に理由・元定義ハッシュ・SVG ハッシュ・画像化範囲・**図内部は個別編集不可**・縮小後の実効文字サイズ・分割提案を記録する（`checks.er_fallback_warnings` にも警告）。ビルドは埋め込み SVG がハッシュ一致し、全文字列と関係を含むことを検査する。
- ビルド時に PPTX 実体で、見出し・属性行の文字と所属（枠内）、関係線の始点＝外部キーを持つ側の境界かつ FK 行の高さ、終点＝参照先の境界、多重度の位置、定義に無い図形がないことを検査する（`checks.diagram_errors`）。サンプル: `examples/bench-er`（小規模ER＝ネイティブ、12エンティティ＝SVG 例外）。

## 画像アセット（SVG / PNG / 生成画像）

```bash
python3 scripts/assets.py examples/*/        # 権利・出自・ハッシュ・解像度・SVG の検査
scripts/build --content examples/asset-illustration/content.yaml --design examples/asset-illustration/design.yaml
```

- 画像の出自（自作 / 生成 / 第三者）・生成指示・ライセンス・sha256・寸法・透過を `<deck>/assets/manifest.yaml` に記録し、未登録・権利不明・差し替え後の更新漏れ等を CI とビルドで検出する。
- 図の中心データは画像に焼き込まない。画像生成は人がチャットで明示的に指示したときだけ。詳細は [`docs/assets.md`](docs/assets.md)。

## 自動 QA

`scripts/build` が内容保持（PPTX/PDF の照合・往復検査）、幾何（スライド外・文字図形の重なり・推定あふれ）、最小文字サイズ、図の線と関係、編集性（表・グラフ・図の画像化の検出）、権利を検査し、結果を `build/<deck>/qa/report.json` に出す（CI artifact）。誤検知の除外は `qa-exceptions.yaml`（Slide ID・検査 ID・対象・理由が必須）。詳細は [`docs/qa.md`](docs/qa.md)。

## 視覚ベンチマーク

```bash
scripts/dev.sh run python3 scripts/benchmark.py   # 3デッキ × 初期 / テーマ変更 / 文言増加
# → build/benchmark/index.html（before/after 比較）、build/benchmark/metrics.json
```

意味保持（自動指標）と装飾品質（目視の5段階評価）を分けて [`docs/benchmarks.md`](docs/benchmarks.md) に記録している。

## WSL でのセットアップ（入力検証のみ）

```bash
gh repo clone takumi-sano22/presentation-skill-lab
cd presentation-skill-lab
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
python3 scripts/validate.py \
  --content examples/technical-architecture/content.yaml \
  --design examples/technical-architecture/design.yaml \
  --public-repo-check
python3 -m unittest discover -s tests -v
```

Claude Code / Codex へのスキル配置は [`docs/usage.md`](docs/usage.md) を参照。`bash scripts/create-issues.sh` で開発用Issue原稿10件を登録できます（`gh` 認証が必要。同名タイトルはスキップ）。レンダラ実装の前に実行できるのはスキーマと参照の検証だけです。

## 開発バックログの自走（Phase 1〜）

GitHub Issue #2〜#11 を登録済み。うち #2〜#9 はClaude Code中心で自走実装し、#10のChatGPT実機検証と#11のリリース判断は別途Gateを設ける。進捗の集約先は [管理Issue #12](https://github.com/takumi-sano22/presentation-skill-lab/issues/12)。

運用・停止条件は [自走開発規約](docs/autonomy.md) と [dev-autopilotスキル](.claude/skills/dev-autopilot/SKILL.md) にまとめた。規約導入PRのマージ後に `git pull --ff-only` し、`claude auth status` でログイン方法を確認してから `claude --permission-mode auto`（利用可能な環境）で開始し、`docs/autonomy.md` に記載した `/goal` を設定する。非対話モードやAPI課金は必須ではない。

**注意:** 完全無人での作業は、実行環境が動作している間かつ認証・権限・利用枠が有効な場合に限る。モデルやプランでautoモードが使えない場合は手動承認が発生する。安全のためローカルPCで `--dangerously-skip-permissions` は使わない。

## 今後

- [実装ロードマップ](docs/roadmap.md)
- [アーキテクチャ](docs/architecture.md)
- [編集・運用手順](docs/usage.md)
- [コスト設計](docs/cost-policy.md)
- [設計決定 ADR-0001](docs/decisions/0001-base-stack.md)

## 出典・権利

上流プロジェクトは各々独立したライセンスを持ちます。`presentation-skill` は submodule 参照のみで、コードのコピーはしていません。詳細は [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) を参照してください。
