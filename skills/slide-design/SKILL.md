---
name: slide-design
description: content.yaml の文言や数値を変えずに、技術スライドのレイアウト、配色、図表の見せ方、イラスト等を design.yaml で設計するときに使う。
---

# slide-design / 見た目のみ

1. `content.yaml` は読み取り専用で参照し、`design.yaml` とアセットのみ変更する。
2. スライドの種類（architecture/table/comparison/etc）に応じてレイアウトを選択。
3. アーキテクチャは構造化 nodes/edges をネイティブ図形優先で配置し、コネクタの意味を保つ。
4. オリジナル画像を生成する場合、可能ならプロンプトと生成バージョンを資産に記録。文字・表・凡例を画像に焼き込むのは必要な場合に限定。
5. 文章が収まらないときは、字を極端に縮小せず内容担当に具体的な分割案を渡す。
6. `slide-qa` の基準で見直し、変更 Slide ID と理由を報告する。

`scripts/build` で PPTX/PDF/PNG に変換できる。design.yaml の `theme`（technical-light / technical-dark、フォント、配色トークン）は適用済み。`density` は上流未対応のため未適用（`unapplied_design` に列挙）。日本語テーマ規約 J-1〜J-8（`docs/design-rules.md`）に従い、配色はコントラスト検査を通すこと。
