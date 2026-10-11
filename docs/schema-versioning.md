# データ契約（JSON Schema）のバージョン移行ルール

対象: `schemas/content.schema.json`、`schemas/design.schema.json`（現行 v0.1）、および adapter が出力する `outline.json` の部分集合 `schemas/outline-adapter.schema.json`。

## 固定

- v0.1 のスキーマ本文は `tests/test_schema_freeze.py` で sha256 を固定している。スキーマを1文字でも変えるとテストが FAIL する。
- ハッシュだけを更新して通すことは禁止。以下の手順でバージョンを上げる。

## 変更の分類

| 種別 | 例 | バージョン | 手順 |
|---|---|---|---|
| 互換追加 | 任意フィールドの追加、enum 値の追加 | マイナー（0.1→0.2） | 新スキーマを `schema_version` 0.2 で受理し、0.1 入力も引き続き受理する |
| 破壊的変更 | 必須化、フィールド削除・改名、意味変更 | メジャー相当（ADR 必須） | ADR を先に作成（`docs/autonomy.md` の停止条件）。移行スクリプトと旧→新の変換テストを用意 |
| 説明のみ | `title`/`description` の文言 | 変更なし | ハッシュ更新可。PR で「意味変更なし」を明記 |

## 履歴

| content | 変更 | Issue |
|---|---|---|
| 0.1 | 初版 | #1 |
| 0.2 | 互換追加: `node.attributes[]`（name / type / pk / fk / nullable）、`edge.id`、`edge.cardinality{from,to}`。0.2 の項目は `schema_version: '0.2'` かつ `type: er` のスライドでだけ使える（`validate.er_contract_errors`）。0.1 の入力の意味項目・出力は変わらない | #19 |

design スキーマは v0.1 のまま（ER のポリシーは既存の `diagram_mode` に対応づけた）。

## 手順（互換追加）

1. `schema_version` の `const` を `enum` に変えて新旧を受理する（例: `["0.1", "0.2"]`）。
2. adapter の対応表（`scripts/adapter.py` の `SUPPORTED_SCHEMA_VERSIONS`）へ追加し、新フィールドの写像と往復検査（`semantic_items`）を実装する。写像できないフィールドは**黙って捨てず** `UnsupportedContent` で FAIL させる。
3. `tests/test_schema_freeze.py` のハッシュを更新し、旧バージョン入力の回帰テストを残す。
4. `examples/` を必要に応じて更新し、`scripts/validate.py` と全テストを通す。
