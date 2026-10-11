# スキルの配置と変更手順

WSL 上では、初期PRのマージ後に `gh repo clone takumi-sano22/presentation-skill-lab` で取得し、そのリポジトリのルートから以下を実行する。

## 開発リポジトリ内

全スキルの唯一の正本は `skills/<skill-name>/SKILL.md`。プロジェクトごとに文章をコピーして改変しない。

## Claude Code 個人環境

```bash
# リポジトリ直下で実行
mkdir -p ~/.claude/skills
for s in slide-content slide-design slide-render slide-qa; do
  ln -s "$(pwd)/skills/$s" "$HOME/.claude/skills/$s"
done
```

既に同名がある場合は自動で上書きしない。個人環境でシンボリックリンク検出に問題がある場合はディレクトリ単位コピーへ切り替える。プロジェクト固有の `.claude/skills/` へのコピー/リンクも選択できる。

## Codex（CLI/デスクトップ）

```bash
mkdir -p ~/.agents/skills
for s in slide-content slide-design slide-render slide-qa; do
  ln -s "$(pwd)/skills/$s" "$HOME/.agents/skills/$s"
done
```

環境やバージョンでディレクトリの自動検出が異なる場合があるため、導入後にスキル認識を確認する。将来インストーラで自動化する。

## ChatGPT 通常チャット / Work

一般の ChatGPT 会話で GitHub 上の `SKILL.md` を自動検出できるとは限らない。GitHub コネクタでリポジトリを読み、`AGENTS.md`、対象スキル、必要な参照資料、content/design を明示して作業する。

Skills 機能が利用できるプラン/ワークスペースでは適切なパッケージを配布できる。Work は必要に応じてGUI品質確認や複数ファイル操作に利用し、ビルドの必須要件にしない。

## 普段の変更（運用予定: Phase 1以降）

1. GitHub Issue に不具合のスクリーンショット、Slide ID、期待結果を添付（公開可否を確認）。
2. ブランチを作成し、`content` と `design` のどちらを変更するか明示。
3. 原因を `規約` / `テンプレート` / `レイアウト` / `レンダラ` / `QA` に分類。
4. 対応箇所と回帰テストを追加。一般化できる不具合なら `docs/design-rules.md` に規約を1つ追加。
5. 検証スクリプトと3種のサンプルを確認、変更したページのPNG比較を作成。
6. PRで差分・トークン影響・サードパーティライセンスをレビュー。
7. マージ後タグを付与し、スキル利用環境を更新。

## 上流の更新

`vendor` のリビジョンを固定して取り込み、コード差分と権利表記を確認してから独立 PR。レンダラ API の破壊的変更をデータ契約に波及させない。
