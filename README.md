# presentation-skill-lab

Claude Code と ChatGPT の双方から、**中身とデザインを分離**して技術系スライドを生成するためのスキル開発リポジトリ。

> **状態: Phase 1 着手中。** 上流レンダラ（`vendor/presentation-skill` v0.14.0）の固定と描画環境の doctor まで実装済みです。`content.yaml`/`design.yaml` → `outline.json` の adapter（`scripts/adapter.py`）は実装済み、PPTX/PDF/PNG のビルド CLI は**未実装**です。`scripts/validate.py` は共通データ契約と参照の検査のみです。

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

`python3 scripts/doctor.py` をホストで実行すると、ホストに不足しているツールが FAIL として表示されます（ホストでの描画は前提にしません）。CI の `toolchain` ジョブも同じ `scripts/dev.sh` 経路で doctor を実行します。上流の更新手順は [`docs/vendor-update.md`](docs/vendor-update.md) を参照してください。

## adapter（content/design → outline.json）

```bash
python3 scripts/adapter.py \
  --content examples/technical-architecture/content.yaml \
  --design examples/technical-architecture/design.yaml \
  --output build/outline.json
```

- 文言・数値・単位・表セル・図ラベル・出典・注記を意味項目として抽出し、変換後の outline.json から逆写像した項目と**順序込みで完全一致**しなければ FAIL（`ContentMismatch`）。
- 写像できない内容は FAIL（`UnsupportedContent`）。黙って捨てたり画像化しない。図は #6 までテキスト行（`A → B（ラベル）`）へ明示的にフォールバックし、`psl.fallback` に記録する。
- 上流 v0.14.0 に写像先がない design 指定（`theme.fonts`・`theme.colors`・`density`）は `psl.unapplied_design` に列挙し WARN を出す（適用は #5）。
- 出力は正規化 JSON（キー順固定）で、同一入力なら `outline_sha256` が一致する。出力の形は `schemas/outline-adapter.schema.json`、スキーマ変更手順は [`docs/schema-versioning.md`](docs/schema-versioning.md)。
- `outline.json` は生成物。編集しても次回変換で失われる。

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
