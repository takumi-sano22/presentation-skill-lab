#!/usr/bin/env python3
"""生成環境の doctor。上流の固定・ライセンス・Python/Node/LibreOffice/poppler/日本語フォントを検査する。

ホストでも実行できるが、描画ツールは Docker イメージ（scripts/dev.sh）内で揃える前提。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCK = ROOT / "upstream.lock.json"
MIN_PYTHON = (3, 10)
MIN_NODE_MAJOR = 20
# 日本語描画に使えるフォントファミリー（いずれか1つ必須）
JA_FONTS = ("Noto Sans CJK JP", "Noto Sans JP")


@dataclass
class Check:
    name: str
    ok: bool
    detail: str


def run(cmd: list[str], cwd: Path | None = None) -> tuple[int, str]:
    """外部コマンドを実行し (終了コード, 出力) を返す。存在しなければ 127。"""
    if shutil.which(cmd[0]) is None:
        return 127, f"{cmd[0]} が見つかりません"
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=120, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)
    return p.returncode, (p.stdout + p.stderr).strip()


def load_lock(path: Path = LOCK) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def check_lock_format(lock: dict) -> Check:
    # SHA は短縮不可（再現性のため40桁固定）
    ok = bool(re.fullmatch(r"[0-9a-f]{40}", lock.get("commit", ""))) and bool(lock.get("license_sha256"))
    return Check("upstream.lock.json", ok, f"{lock.get('tag')} {lock.get('commit')}")


def check_submodule(lock: dict) -> list[Check]:
    sub = ROOT / lock["path"]
    checks: list[Check] = []
    # superproject に記録された gitlink が lock と一致するか
    code, out = run(["git", "ls-files", "-s", lock["path"]], cwd=ROOT)
    recorded = out.split()[1] if code == 0 and out.startswith("160000") else ""
    checks.append(Check("gitlink == lock", recorded == lock["commit"], recorded or out))
    # 実際にチェックアウトされているコミットが lock と一致するか
    code, out = run(["git", "rev-parse", "HEAD"], cwd=sub) if sub.is_dir() else (1, "未取得: git submodule update --init")
    checks.append(Check("checkout == lock", code == 0 and out == lock["commit"], out))
    return checks


def check_license(lock: dict) -> Check:
    path = ROOT / lock["path"] / lock["license_file"]
    if not path.is_file():
        return Check("upstream LICENSE", False, f"{path} がありません")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    ok = digest == lock["license_sha256"]
    return Check("upstream LICENSE", ok, f"{lock['license']} sha256={'一致' if ok else digest}")


def check_python() -> list[Check]:
    v = sys.version_info
    checks = [Check("python", v[:2] >= MIN_PYTHON, f"{v.major}.{v.minor}.{v.micro}")]
    for mod in ("yaml", "jsonschema"):
        try:
            __import__(mod)
            checks.append(Check(f"python:{mod}", True, "import OK"))
        except ImportError as exc:
            checks.append(Check(f"python:{mod}", False, str(exc)))
    return checks


def check_node(lock: dict) -> list[Check]:
    code, out = run(["node", "--version"])
    major = int(out.lstrip("v").split(".")[0]) if code == 0 else 0
    checks = [Check("node", major >= MIN_NODE_MAJOR, out)]
    if code != 0:
        return checks
    # 上流レンダラと同じ解決順（PPTX_NODE_MODULES → vendor/node_modules）で版を確認する
    env_dirs = [os.environ.get("PPTX_NODE_MODULES", ""), str(ROOT / lock["path"] / "node_modules")]
    for name, expected in lock.get("node_dependencies", {}).items():
        found = ""
        for d in filter(None, env_dirs):
            pkg = Path(d) / name / "package.json"
            if pkg.is_file():
                found = json.loads(pkg.read_text(encoding="utf-8")).get("version", "")
                break
        checks.append(Check(f"node:{name}", found == expected, f"installed={found or 'なし'} pinned={expected}"))
    return checks


def check_tools() -> list[Check]:
    checks = []
    code, out = run(["soffice", "--headless", "--version"])
    checks.append(Check("libreoffice", code == 0, out.splitlines()[0] if out else ""))
    code, out = run(["pdftoppm", "-v"])
    checks.append(Check("poppler(pdftoppm)", code == 0, out.splitlines()[0] if out else ""))
    code, out = run(["fc-list", ":lang=ja", "family"])
    families = {f.strip() for line in out.splitlines() for f in line.split(",")} if code == 0 else set()
    hit = [f for f in JA_FONTS if f in families]
    checks.append(Check("font:ja", bool(hit), ", ".join(hit) or f"{' / '.join(JA_FONTS)} が見つかりません"))
    return checks


def collect() -> list[Check]:
    lock = load_lock()
    checks = [check_lock_format(lock), *check_submodule(lock), check_license(lock)]
    checks += check_python() + check_node(lock) + check_tools()
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="結果を JSON で出力")
    args = parser.parse_args()
    checks = collect()
    if args.json:
        print(json.dumps([c.__dict__ for c in checks], ensure_ascii=False, indent=2))
    else:
        for c in checks:
            print(f"{'PASS' if c.ok else 'FAIL'} {c.name}: {c.detail}")
    failed = [c for c in checks if not c.ok]
    if not args.json:
        print(f"\n{'PASS' if not failed else 'FAIL'}: {len(checks) - len(failed)}/{len(checks)} 項目")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
