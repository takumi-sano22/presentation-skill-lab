---
name: slide-render
description: スライドの content.yaml と design.yaml から、再現可能な PPTX・PDF・PNGプレビューを出力する処理を実行・開発するときに使う。
---

# slide-render / 決定論的ビルド

`content.yaml`・`design.yaml` が正本。`outline.json`/PPTXは生成物として上書き可。ただし入力ファイルは勝手に変えない。

**Phase0では変換プログラムは未実装。** 使えるのは `python3 scripts/validate.py --content ... --design ...` の入力検査のみ。

Phase1以降: upstream adapter で `outline.json` → pinned renderer → PPTX → PDF/PNG → manifest の順で出力し、使用した upstream SHA・フォント・アセット hash・例外を記録する。機械処理だけのビルドにLLMを毎回呼ばない。
