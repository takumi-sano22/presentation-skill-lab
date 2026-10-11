# P1-03: PPTX/PDF/PNGの共通ビルドCLI

## 目的
両エージェントで同じコマンドを呼べば同じ資料を作れること。

## 実装
- `scripts/build` を用意し、adapter → upstream PPTX → PDF/PNG の順に出力。
- 全成果物へ元コンテンツhash・renderer SHA・フォント情報を記録。
- HTML galleryはPNGを一覧表示する静的プレビューとする。

## 完了条件 (DoD)
- [ ] 6枚の合成デッキのPPTX/PDF/PNGが作れる
- [ ] PDFページ数とSlide数が一致
- [ ] 日本語が豆腐化せず、改行が正常
- [ ] 静的プレビューが開ける

## 前提 / Gate
P1-02。Gate 1の解除条件。
