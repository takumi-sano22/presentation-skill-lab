# Gate 4 実機・相互運用検証の手順

2026-10-11時点。関連: #10（Gate 4）, #19（ER）, #22（装飾）, #24（QA境界）。

## 目的・役割の分離

- **A: Claude Code → ChatGPT（デザイン）**: Claude Code由来の `examples/technical-architecture/content.yaml` をChatGPTが**一切変更せず**、`design-chatgpt.yaml` のみを作成する。GitHub CIが既存 `design.yaml` とのcontentハッシュ一致、異なるdesignハッシュ、6枚のPPTX/PDF/PNG生成、重要QAゼロを確認する。
- **B: ChatGPT → Claude Code（デザイン）**: ChatGPTが `examples/gate4-chatgpt-origin/content.yaml` の架空6枚を作成する。Claude Codeは同じブランチでその本文を**一切変更せず** `design.yaml` を作成し、`scripts/build` とQAを実行する。
- **C: Windows PowerPoint**: 所有者が実機で表示と編集を確かめる。これをLibreOffice CIの緑で代替しない。
- 正本はYAMLとアセット、PPTX/PDFは生成物。PowerPointで直接修正した生成PPTXをソースとして逆流させない。

## A の証跡（GitHub）

- 原文: `examples/technical-architecture/content.yaml`
- ChatGPTデザイン: `examples/technical-architecture/design-chatgpt.yaml`
- CIの `Gate 4-A - content lock and design diff` がSUCCESSであること
- 出力: `build/gate4-chatgpt-design/`（Actions `sample-decks` artifact）
- GitHub上の変更ファイルのうち入力資料は design-chatgpt.yaml **だけ**。原文の content.yaml に変更がないこと。

## B の受け入れ

- ChatGPT起点: `examples/gate4-chatgpt-origin/content.yaml`（全て synthetic/public）
- Claude Code担当: 同じディレクトリの `design.yaml` と必要なら生成物のQA設定だけ
- `content.yaml` は読取専用で、変更する必要が生じたら提案しユーザーとChatGPTに確認する。
- 6枚の生成と `content_sha256` の記録。文字・値・表セル・図の接続関係欠落ゼロ。
- ChatGPT起点の内容とClaudeデザインの変更差分がPRで追えること。

## PowerPoint（Windows）実機試験

検証用の合成PPTXだけを使用。Actionsの該当runを開き、`sample-decks` または `benchmark` artifactから `deck.pptx` を取得する。フォント `Noto Sans JP` がPowerPoint環境で解決するか確認し、代替が起こる場合は代替フォント名を記録する（フォントファイルを公開リポジトリにアップロードしない）。

1. **表示**: 表紙、長い日本語見出し、表、棒グラフ、ネイティブ構成図、色の異なるテーマのページを表示。PDF/PNGと比較し、はみ出し・文字消失・カラーバランス・矢印方向を記録。
2. **編集**: PPTXを別名保存したコピー上で、タイトル文字、表のセル、棒グラフのデータ、ノード文字と位置、接続線を一つずつ選択・編集。保存→閉じる→再度開いて編集が残っているか確認。
3. **ER図**: #19完了後、小規模ERのエンティティ名・属性・キー・関係線を選択・編集。高密度のSVGフォールバックは図全体のみ選択可能であること、内部個別編集不可であることを**正しく報告**。
4. **人間評価**: 見出し、和文文字組み、図の意味、比較表/グラフ、余白の5項目を1〜5で採点（1=致命的崩れ、3=実務前に修正したい、5=手直し不要）。低スコアはSlide IDと原因候補を記録。
5. **記録**: 変更前PPTXのActions run/commitと、確認したOffice版/OS/フォント、対象Slide ID、結果を #10 のコメントへ記載。必要な画面キャプチャは**合成資料のみ**を使い、実顧客情報は含めない。

### 簡易チェック記録テンプレート

```text
対象デッキ/commit:
PowerPoint版/OS:
フォント（指定/実際）:
表示一致: PASS/FAIL/条件付き
タイトル文字: 編集/保存/再open PASS/FAIL
表セル: 編集/保存/再open PASS/FAIL
グラフデータ: 編集/保存/再open PASS/FAIL
ノード/線: 編集/保存/再open PASS/FAIL
ERネイティブ/例外SVG: 未試験/PASS/FAIL
見出し: 1-5 / 和文: 1-5 / 図: 1-5 / 表/グラフ: 1-5 / 余白: 1-5
問題Slide ID・所見:
```

## Cost / Workの判断

初期経路は **ChatGPT通常チャット→GitHub入力変更→GitHub Actionsで決定論的ビルド**。ChatGPT Workを使う条件は、通常チャットでのファイルや図版の編集・GUI操作が品質上の阻害要因と分かった場合だけ。LLMトークンは取得できた値のみ記録し、取得不能なら「未計測」と書く。ローカルのビルド時間/CI時間をトークン使用量と混同しない。

## リリースに関する注意

A/B両経路の成功、PowerPoint実機検証、#19/#22/#24への対応と既知例外の整理が済むまで #10 はCloseしない。#11のGitHub Releaseを作成しない。
