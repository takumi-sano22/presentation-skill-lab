# Gate 4-B：ChatGPT → Claude Code

このディレクトリの `content.yaml` は、**ChatGPT通常チャットがGitHub接続を通じて作成**した架空の6枚資料です。

- 内容: 差分イベント同期と日次照合の役割分離
- 分類: `public` / `synthetic: true` / `content_locked: true`
- **次の担当: Claude Code**。このブランチで `design.yaml` を新規作成し、必要なら同一ブランチへテストを追加する。
- `content.yaml` のタイトル・本文・数値・表・図・ノードID・辺IDは**変更しない**。描画できない場合はレイアウトの修正やデザインの変更を優先し、変更要求をIssue #10へ記録する。
- `scripts/build --content examples/gate4-chatgpt-origin/content.yaml --design examples/gate4-chatgpt-origin/design.yaml --out build/gate4-chatgpt-origin` でPPTX/PDF/PNGを生成する。
- 既存の `tests/test_gate4_contract.py` がなければ、原文ハッシュが一致することをCIで検証できる薄いテストを追加する（原文はGitのコミットSHAでも照合する）。
- 生成物はQAと視覚検証を行い、PowerPoint実機の表示・編集についてはユーザーが#10で確認する。Claude自身は実施したと報告しない。

完成後、PRをレビュー可能にし、GitHub上にCI成果物と内容ハッシュを残す。最終的なGate 4の判定は `docs/gate4-validation.md`（PR #26で導入）に従う。
