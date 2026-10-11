#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
REPO="takumi-sano22/presentation-skill-lab"
command -v gh >/dev/null || { echo "gh CLI が必要です" >&2; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "gh auth login が必要です" >&2; exit 1; }
gh repo view "$REPO" >/dev/null 2>&1 || { echo "$REPO がまだ作成されていません" >&2; exit 1; }

# GitHub の同名タイトルで二重登録を防ぐ（タイトルは docs/issues で管理）。
for f in docs/issues/*.md; do
  title=$(sed -n '1s/^# //p' "$f")
  if [[ -z "$title" ]]; then
    echo "$f: タイトルがありません" >&2; exit 1
  fi
  if gh issue list --repo "$REPO" --state all --limit 500 --json title --jq '.[].title' | grep -Fqx "$title"; then
    echo "skip: $title"
  else
    gh issue create --repo "$REPO" --title "$title" --body-file "$f"
  fi
done
