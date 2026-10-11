# P1-01: 主基盤OSSの固定と環境整備

## 目的
`siril9/presentation-skill` のライセンスとリビジョンを固定して、WSL/CI で生成環境を再現可能にする。

## 実装
- 上流の release/tag と commit SHA を確認して `vendor/` へ submodule または pinned checkout で取り込む。
- MIT原本を保持、`THIRD_PARTY_NOTICES.md` に正確なコミット・コピー範囲を記録。
- Python/Node/LibreOffice/フォント関連の doctor を追加。

## 完了条件 (DoD)
- [ ] READMEに手順・バージョン・環境依存を記載
- [ ] upstream SHA が固定される
- [ ] ローカルとCIで doctor が成功
- [ ] vendor 更新の差分確認ルールが決まる

## 前提 / Gate
Phase 0 完了後。Gate 1 の先行Issue。
