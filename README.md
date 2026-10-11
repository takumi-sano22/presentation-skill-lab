# presentation-skill-lab

Claude Code と ChatGPT の双方から、**中身とデザインを分離**して技術系スライドを生成するためのスキル開発リポジトリ。

> **状態: Phase 0 / 設計・検証用雛形。** この時点では `PPTX / PDF` の実レンダラは未接続です。`scripts/validate.py` は共通データ契約と参照の検査のみ実装済みです。実装済みと未実装を混同しないでください。

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

## WSL でのセットアップ（初期PRのマージ後）

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

## 今後

- [実装ロードマップ](docs/roadmap.md)
- [アーキテクチャ](docs/architecture.md)
- [編集・運用手順](docs/usage.md)
- [コスト設計](docs/cost-policy.md)
- [設計決定 ADR-0001](docs/decisions/0001-base-stack.md)

## 出典・権利

上流プロジェクトは各々独立したライセンスを持ちます。現段階ではコードを取り込んでいません。詳細は [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) を参照してください。
