---
name: dev-autopilot
description: presentation-skill-labの実装バックログを、依存関係・CI・品質Gateを守ってGitHub Issue→PR→マージまで自律的に進めるときに使う。
---

# 開発自走スキル

最初に `AGENTS.md`、`CLAUDE.md`、`docs/autonomy.md`、`docs/roadmap.md`、`docs/decisions/0001-base-stack.md` を読む。プロジェクトの仕様や停止条件を上書きしない。

## 1ターンの作業

1. `gh issue list --repo takumi-sano22/presentation-skill-lab --state open --limit 100`、`gh pr list --repo takumi-sano22/presentation-skill-lab --state open` とCIを見て実際の状態を確かめる。
2. 未完了PRがあればそれを優先し、なければ#2〜#9から依存を満たす最小番号のIssueを選ぶ。#12は進捗管理用なので実装しない。
3. Issue原稿とDoDを確認し、担当Issueだけを独立ブランチで実装。実装済み/未実装を区別し、テストと資料を更新する。
4. PRに `Closes #N` を記載し、サンプルの生成結果、テスト、CI、図表の編集可能性、ライセンス、既知制約を示す。
5. 独立した自動検査とIssue DoDを満たすPRのみsquash mergeし、Issueが閉じたことを確認。#12に簡潔な進捗コメントを残し、次のIssueへ進む。
6. `docs/autonomy.md` の停止条件に当たったら、止まった理由と再開条件をIssueと#12に記録し、作業を捏造して終わらせない。

## 絶対に避けること

- CI・DoDを弱める「修正」、テストの除外、実際に未確認の成果物を確認済みと書く行為。
- API課金・Secretsの作成・実業務情報をPublicへpush・ライセンス不明のコード移植。
- `main`への直接push、force push、認証/権限検査の迂回。
- ChatGPTアカウントでしか実施できない作業を実施済みと見なすこと。

## 長期継続

初回のIssueを終えてもユーザーへの回答だけで停止せず、次の依存解決済みIssueがあれば続ける。`/goal` が設定されている場合は、その達成判定用に `gh issue view` とCI結果を回答に明示する。使用量制限や環境問題が起きたときは、GitHubに残した状態から再開できるようにする。
