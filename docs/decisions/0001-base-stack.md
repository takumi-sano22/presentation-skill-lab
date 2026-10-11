# ADR-0001: スライド生成の主基盤と共通契約

- 日付: 2026-10-11
- 状態: Accepted（初期方針）

## 背景

ユーザーの条件: 内容とデザインを分業し、Claude Code と ChatGPT を対等に利用する。技術図・表が多く、PDF 見栄えと PowerPoint 編集性を両立させる。画像化は例外的に許容。低トークンコスト、Public、MIT。

## 決定

1. 主エンジンは `siril9/presentation-skill` の PptxGenJS 系を固定バージョンで利用する。
2. ソース正本を `content.yaml` と `design.yaml` に分離する。必要時に Markdown/CSV/画像を参照する。
3. 上流の `outline.json` は adapter が自動生成する二次形式とする。
4. HTML はプレビュー用ギャラリー、複雑なデザイン図は画像アセットとして扱う。初期は HTML→編集可能PPTX を実装しない。
5. 日本語規約は carnot の MIT 規約を選択的に移植/翻案する。minorun の Apache 2.0 ソースは初期コピーしない。
6. Claude Code と ChatGPT は同一ルール・同一スキーマを読む。ChatGPT通常チャットで Skills のネイティブ導入ができない環境では GitHub 経由でファイルを扱う。
7. ChatGPT Work 等の GUI 操作・反復評価は検証で必要性が示された場合に限定する。

## 選ばなかった案

- Marp/Slidev 単独: Markdown とデザインの機動性は高いが、編集可能なPPTXの再現性・非画像化の範囲を検証する必要がある。
- HTML/Marp/PPTX の3系統を最初から並列開発: トークン費とレイアウト差分の二重保守が増える。
- 既存 OSS 全部をそのまま結合: ライセンス・依存・指示の衝突と長文コンテキストが問題になる。

## 再検討条件

技術図を含むベンチマーク3組以上で、主エンジンが PowerPoint 編集可能性またはビジュアル品質を継続して満たせない場合。必要なら Slidev `pptx-editable` を比較検証し、ADRで改定する。
