#!/usr/bin/env bash
# Docker の描画ツールチェーン内でコマンドを実行する薄いラッパー。
# 使い方: scripts/dev.sh build            # イメージ作成
#         scripts/dev.sh run <command...> # リポジトリをホストと同じパスにマウントして実行
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
IMAGE="${PSL_IMAGE:-presentation-skill-lab-render:local}"

case "${1:-}" in
  build)
    docker build -f "$ROOT/docker/Dockerfile" -t "$IMAGE" "$ROOT"
    ;;
  run)
    shift
    # worktree / submodule の .git は共通 git ディレクトリを相対・絶対パスで指すため、同じパスでマウントする
    GIT_COMMON="$(cd "$ROOT" && git rev-parse --path-format=absolute --git-common-dir)"
    # 生成物の所有者をホストユーザーに揃える
    docker run --rm --user "$(id -u):$(id -g)" \
      -v "$ROOT:$ROOT" -v "$GIT_COMMON:$GIT_COMMON:ro" \
      -w "$ROOT" "$IMAGE" "$@"
    ;;
  *)
    echo "usage: $0 build | run <command...>" >&2
    exit 2
    ;;
esac
