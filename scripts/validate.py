#!/usr/bin/env python3
"""Validate v0.1 slide content/design sources. This is not a slide renderer."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent.parent


def load_yaml(path: Path) -> dict:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: オブジェクトではありません")
    return value


def schema_errors(data: dict, path: Path) -> list[str]:
    schema = json.loads((ROOT / "schemas" / f"{path}.schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    return [f"{path}: {'.'.join(map(str, e.absolute_path)) or '(root)'}: {e.message}" for e in sorted(validator.iter_errors(data), key=lambda e: str(e.path))]


def cross_validate(content: dict, design: dict, content_dir: Path) -> list[str]:
    errors: list[str] = []
    if content.get("deck_id") != design.get("deck_id"):
        errors.append("content.deck_id と design.deck_id が一致しません")
    slides = content.get("slides", [])
    ids = [s.get("id") for s in slides if isinstance(s, dict)]
    if len(ids) != len(set(ids)):
        errors.append("slide.id が重複しています")
    for sid in design.get("overrides", {}):
        if sid not in ids:
            errors.append(f"design.overrides の {sid} は content に存在しません")
    for slide in slides:
        if not isinstance(slide, dict):
            continue
        sid = slide.get("id", "unknown")
        diagram = slide.get("diagram", {})
        if diagram:
            node_ids = [n.get("id") for n in diagram.get("nodes", []) if isinstance(n, dict)]
            if len(node_ids) != len(set(node_ids)):
                errors.append(f"{sid}: node.id 重複")
            for edge in diagram.get("edges", []):
                if edge.get("from") not in node_ids or edge.get("to") not in node_ids:
                    errors.append(f"{sid}: edge の接続先がありません {edge}")
                if edge.get("from") == edge.get("to"):
                    errors.append(f"{sid}: 自己接続は初期仕様で未対応")
        table = slide.get("table", {})
        if table:
            headers = table.get("headers", [])
            for rowno, row in enumerate(table.get("rows", []), start=1):
                if len(row) != len(headers):
                    errors.append(f"{sid}: 表の {rowno} 行目が列数不一致")
        chart = slide.get("chart", {})
        if chart:
            categories = chart.get("categories", [])
            for series in chart.get("series", []):
                if len(series.get("values", [])) != len(categories):
                    errors.append(f"{sid}: chart の categories と values の数が一致しません")
        asset = slide.get("asset_ref")
        if asset:
            path = (content_dir / asset).resolve()
            if not path.is_relative_to(content_dir.resolve()):
                errors.append(f"{sid}: asset_ref が content ディレクトリ外を参照します")
            elif not path.is_file():
                errors.append(f"{sid}: アセットが存在しません {asset}")
    return errors


# 引用符なしの値の途中にある「 #」は YAML ではコメントになり、以降の文言が黙って捨てられる
# （例: notes: 詳細は Issue #19 で検討 → 「詳細は Issue」になる）
KEY_PREFIX = re.compile(r"^\s*(?:-\s+)?(?:[\w.-]+:(?:\s+|$))?")


def yaml_comment_issues(path: Path) -> tuple[list[str], list[str]]:
    """文言の途中に「 #」があり、コメントとして切り捨てられている可能性のある行を返す。

    戻り値は（strict, loose）。キー（`key:`）と箇条（`- `）を除いた値が引用符・ブロック記号で始まらず、
    途中に「 #」を含む行を対象にする。値の無い行末コメント（`key:  # 説明`）と、識別子だけの設定値に続く説明
    （`layout: cover  # 説明`）は対象外。
      - strict: 「 #」の直後が空白でない（`Issue #19`、`#タグ` など）。文言の一部である可能性が高い。
        公開リポジトリ検査（--public-repo-check）では FAIL にする。
      - loose: 「 # 」と空白が続く。文言の後ろに意図して書いたコメントの可能性があるため警告に留める。
    意図したコメントを文言の後ろに書く場合は「 # 」（# の後ろに空白）とし、文言に # を含める場合は引用符で囲む。
    """
    strict, loose = [], []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if line.lstrip().startswith("#"):
            continue
        value = line[KEY_PREFIX.match(line).end():]
        if not value or value[0] in "'\"|>#[{" or " #" not in value:
            continue
        before, after = value.split(" #", 1)
        message = f"{path.name}:{lineno}: 「 #」以降が YAML のコメントとして捨てられます。文言なら引用符で囲んでください: {line.strip()[:60]}"
        if after and not after[0].isspace():
            # 「#」の直後が空白でない（Issue #19、#タグ）: 値が一語でも文言の欠落とみなす（takeaway: Issue #19 など）
            strict.append(message)
            continue
        # 「 # 」で始まるコメント: 識別子だけの設定値（例: layout: cover  # 説明）は意図したコメントとみなし、
        # 文言（空白や非 ASCII を含む）だけ警告する。\w は和文も含むため ASCII に限定する
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", before.strip()):
            loose.append(message)
    return strict, loose


def yaml_comment_warnings(path: Path) -> list[str]:
    """yaml_comment_issues の両区分をまとめた一覧（従来の警告 API）。"""
    strict, loose = yaml_comment_issues(path)
    return strict + loose


def main() -> int:
    p = argparse.ArgumentParser(description="スライド内容・デザインの入力契約 v0.1 を検証")
    p.add_argument("--content", required=True, type=Path)
    p.add_argument("--design", required=True, type=Path)
    p.add_argument("--public-repo-check", action="store_true", help="公開リポジトリに適さないメタデータを拒否")
    a = p.parse_args()
    try:
        content = load_yaml(a.content)
        design = load_yaml(a.design)
        errors = schema_errors(content, Path("content")) + schema_errors(design, Path("design"))
        errors += cross_validate(content, design, a.content.parent)
        if a.public_repo_check and (content.get("metadata", {}).get("classification") != "public" or not content.get("metadata", {}).get("synthetic")):
            errors.append("公開用サンプルは classification: public かつ synthetic: true が必要")
        strict_comments, loose_comments = yaml_comment_issues(a.content)
        if a.public_repo_check:
            # 公開サンプルで文言が黙って欠けるのを防ぐため、文言中の「 #」（直後が空白でない）は FAIL
            errors += [f"{c}（公開リポジトリ検査では FAIL）" for c in strict_comments]
        if errors:
            print("FAIL: 入力契約違反")
            for error in errors:
                print(" -", error)
            return 1
        for warning in (loose_comments if a.public_repo_check else strict_comments + loose_comments):
            print("WARN:", warning)
        canonical = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        print(f"PASS: {len(content['slides'])} スライドの入力契約を検証")
        print(f"content_sha256: {hashlib.sha256(canonical).hexdigest()}")
        print("注: レンダリング・視覚QA・PPTX編集可能性は未検証です")
        return 0
    except (ValueError, OSError, yaml.YAMLError, json.JSONDecodeError) as error:
        print("FAIL:", error, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
