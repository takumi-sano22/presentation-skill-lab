---
name: slide-content
description: 技術資料の根拠・主張・表・図の意味構造を整理し、デザインとは独立した content.yaml を作成または編集する際に使う。
---

# slide-content / 内容のみ

1. `AGENTS.md` と `docs/architecture.md` の内容契約を確認する。
2. 指定された資料または GitHub リポジトリの必要範囲だけを読む。根拠がない数字は作らない。
3. Audience / Goal / Key message を定め、各スライドに一つの主張か問いを置く。
4. `content.yaml` の安定 ID・本文・比較項目・図ノード/辺・出典を編集する。
5. `design.yaml` は変更しない。文字数が多すぎる場合はデザイン担当に分割案を提示。
6. `python3 scripts/validate.py --content ... --design ...` を実行する（入力検査）。生成確認は `scripts/build` を使う。

重要: すでに合意された本文/数値は勝手に短縮・丸め・組み替えない。更新内容・変更元・未確認事項を報告する。

ER 図（`type: er`）は `schema_version: '0.2'` で、ノードに `attributes`（`name`・`type`・`pk`・`fk: <エンティティID>.<属性名>`・`nullable`）、辺に `cardinality: {from, to}` と任意の `id` を書く。`from` は外部キーを持つ側（子）、`to` は参照される側（親）。複合主キーは複数の属性に `pk: true`。エンティティが多く1枚で読めない場合（ビルドが SVG 例外を警告し分割枚数を提案する）は、スライドの分割を検討する。

画像スライド（`type: illustration`）は `asset_ref` で manifest 登録済みの画像を参照し、本文は置かない（注記は `notes`）。画像に頼らず、主張・数値・出典は content.yaml に書く。
