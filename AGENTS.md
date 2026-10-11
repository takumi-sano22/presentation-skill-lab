# Agent working agreement

- **文章は日本語を標準とする。** README、Issue、PR、ADR、コメント、レポートも原則日本語。固有名詞・コード識別子は英語可。
- `docs/decisions/` の確定済み ADR を優先。新しい設計変更は先に ADR を作成する。
- `content.yaml` はスライドの真実・文言・数字・引用を保持する。デザイン担当は内容を黙って変更しない。
- `design.yaml` はテーマ・レイアウト・画像割当を保持する。内容担当はデザインを黙って変更しない。
- 生成 `.pptx`、`build/outline.json`、スクリーンショット等を正本としない。
- 数字と根拠に架空データを使うときは `synthetic: true` を指定する。企業データ等は public repo に書かない。
- 実装済みの機能と計画だけの機能を区別する。現在稼働するのは入力検証・上流固定（doctor）・adapter・共通ビルド CLI（PPTX/PDF/PNG）まで。日本語テーマ・ネイティブ図・アセット管理・総合QAは未実装。
- PR では affected slide IDs、更新前後の検査結果、上流依存／ライセンスへの影響を書く。
- 複数の LLM サブエージェントでの自動反復を既定にしない。決定論的なチェックを先に用いる。
- 実装に入るときは `docs/roadmap.md` の Gate/DoD を守る。

- 自走開発を行う場合は `docs/autonomy.md` を参照する。Issue→PR→CI→マージの順序と停止条件を守り、重大な判断を曖昧にして継続しない。
