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
6. `python3 scripts/validate.py --content ... --design ...` を実行する（Phase0では入力検査のみ）。

重要: すでに合意された本文/数値は勝手に短縮・丸め・組み替えない。更新内容・変更元・未確認事項を報告する。
