# Claude Code 向け

`AGENTS.md` と `docs/decisions/0001-base-stack.md` に従う。すべての文章・Issue・PR は日本語で記述する。ユーザーが `slide-content` と依頼したときは `skills/slide-content/SKILL.md` を、`slide-design` では `skills/slide-design/SKILL.md` を参照。未実装のレンダラを使えると説明しない。

## 自走開発

開発バックログの自走は `docs/autonomy.md` と `.claude/skills/dev-autopilot/SKILL.md` に従う。GitHub Issue #2〜#9が実装対象、#12は進捗管理、#10〜#11は外部実機検証・リリースのGateである。安全停止条件に当たったらIssueで証跡を残して止まる。CI・受け入れ基準を弱めて成功扱いにしない。

## v1.0の追加開発（2026-10-12）

所有者がQ1=高密度ERを内容を変えず可読な複数ページへ自動分割、Q2=構成図・ER図の線がPowerPointでノード移動に追従することをv1必須と確定。Accepted ADR-0003が優先。#32→#33の順に実装し、Windows実機操作が必要な#10は人間確認までOpen、#11はReleaseしない。
