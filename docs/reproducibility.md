# ビルド環境の再現性（v1.0 までの水準）

関連: #24。描画結果（PPTX/PDF/PNG）は、上流レンダラだけでなく LibreOffice・poppler・フォント・Python 依存の版でも変わり得る。ベンチマークや QA の差分が出たときに「入力の変更か、環境の変更か」を切り分けられることを v1.0 の目標とする。完全なビット再現は目標にしない。

## 固定するもの

| 対象 | 方法 | 検査 |
|---|---|---|
| 上流レンダラ `siril9/presentation-skill` | git submodule ＋ `upstream.lock.json`（コミット SHA・LICENSE ハッシュ） | `scripts/doctor.py` |
| Node 依存（pptxgenjs 等） | 上流の `package-lock.json` で `npm ci` | `scripts/doctor.py` |
| ベースイメージ `node:22-bookworm` | `docker/Dockerfile` の `BASE_IMAGE` を **digest 付き**で指定 | ビルド manifest の `tools.base_image` |

## 固定せず、実際の版を記録するもの

| 対象 | 理由 | 記録先 |
|---|---|---|
| apt パッケージ（libreoffice-impress / poppler-utils / fonts-noto-cjk / fontconfig） | Debian の版固定は snapshot リポジトリの運用が必要で、v1.0 の配布規模に対して保守コストが大きい。ベースイメージ digest を固定すれば Debian のリリース系列は固定される | manifest `tools.packages["apt:*"]`、`tools.libreoffice`、`tools.poppler` |
| Python 依存（PyYAML / jsonschema） | `requirements-dev.txt` はメジャー版の幅指定。検証ロジックはメジャー版内で互換 | manifest `tools.packages["pip:*"]`、`tools.python` |

ビルドごとの `manifest.json`（CI artifact `sample-decks` / `benchmark`）に上記が残るため、2 つのビルドの差分は manifest の `tools` を比較して環境由来かを判断する。

## 更新の手順

1. ベースイメージ digest の更新・Dockerfile のパッケージ追加は **専用 PR** で行い、機能変更と混ぜない（上流の更新は `docs/vendor-update.md`）。
2. PR で `scripts/dev.sh build` → `scripts/dev.sh run python3 scripts/doctor.py` → `scripts/dev.sh run python3 scripts/benchmark.py` を実行し、更新前後の `metrics.json`・`gate.json` と変更ページの PNG を比較して PR に記録する。
3. digest の取得: `docker pull node:22-bookworm && docker image inspect node:22-bookworm --format '{{index .RepoDigests 0}}'`

## v1.0 以降に再検討すること

- 配布先が増え、apt の版差による描画差が実際に問題になった場合は、snapshot.debian.org を使った apt 版固定か、ビルド済みイメージのレジストリ配布を検討する（そのときは ADR を作成する）。
