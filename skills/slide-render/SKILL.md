---
name: slide-render
description: スライドの content.yaml と design.yaml から、再現可能な PPTX・PDF・PNGプレビューを出力する処理を実行・開発するときに使う。
---

# slide-render / 決定論的ビルド

`content.yaml`・`design.yaml` が正本。`outline.json`/PPTXは生成物として上書き可。ただし入力ファイルは勝手に変えない。

**実装済み:** 入力検査 `python3 scripts/validate.py --content ... --design ...` と、adapter `python3 scripts/adapter.py --content ... --design ... --output build/outline.json`（意味項目の往復検査付き）。**PPTX/PDF/PNG を出すビルド CLI は未実装（#4）。**

Phase1以降: upstream adapter で `outline.json` → pinned renderer → PPTX → PDF/PNG → manifest の順で出力し、使用した upstream SHA・フォント・アセット hash・例外を記録する。機械処理だけのビルドにLLMを毎回呼ばない。
