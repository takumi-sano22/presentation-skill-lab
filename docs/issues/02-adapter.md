# P1-02: 共通ソースをoutline.jsonへ変換するadapter

## 目的
`content.yaml` / `design.yaml` を、上流PPTXレンダラの `outline.json` に情報欠落なく変換する。

## 実装
- JSON Schema v0.1 をテスト固定し、バージョン移行ルールを作る。
- deck_id・Slide ID・表セル・数値・脚注・source_refs を中間表現へ伝搬。
- コンテンツとデザインの書き込み境界を分離し、文言変更があればFAIL。
- unsupported を明示的に FAIL / fallback する。黙って画像化しない。

## 完了条件 (DoD)
- [ ] 合成6枚をエラーなく中間JSONに変換
- [ ] タイトル/本文/数値/単位/表セルの意味情報欠落0
- [ ] 入力順序と安定IDを保持
- [ ] 同一入力の正規化出力ハッシュが一致

## 前提 / Gate
P1-01。Gate 1。
