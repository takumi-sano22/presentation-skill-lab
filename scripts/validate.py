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
        if diagram:
            errors += er_contract_errors(content.get("schema_version"), slide)
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


def er_contract_errors(version: str | None, slide: dict) -> list[str]:
    """v0.2 の ER 項目（属性・PK/FK・多重度・関係 ID）の整合性。JSON Schema で表せない相互参照を検査する。

    - v0.2 の項目は schema_version: '0.2' でだけ使える（0.1 の入力は従来どおり）
    - 属性は type: er のスライドだけ（他の図では表示先がなく黙って捨てられるため）
    - fk は同じ図の <エンティティID>.<属性名> を指し、その向き（子 → 親）の関係が edges にあること（関係の反転を検出）
    - 属性を持つエンティティから出る関係は、from 側に to を参照する FK があること（FK の無い逆向きの関係を拒否）
    - 同じ組の関係が複数あるときは、各関係がどの FK 属性を表すかを edge.fk で指定し、1つの FK を複数の関係で使わない
    """
    sid = slide.get("id", "unknown")
    diagram = slide["diagram"]
    nodes = [n for n in diagram.get("nodes", []) if isinstance(n, dict)]
    edges = [e for e in diagram.get("edges", []) if isinstance(e, dict)]
    uses_v02 = any("attributes" in n for n in nodes) or any(k in e for e in edges for k in ("id", "cardinality", "fk"))
    if not uses_v02:
        return []
    errors = []
    if version != "0.2":
        errors.append(f"{sid}: 属性・多重度・関係 ID は schema_version: '0.2' で使えます（現在 {version}）")
    if slide.get("type") != "er":
        errors.append(f"{sid}: 属性・多重度は type: er のスライドだけで使えます")
    attrs = {n.get("id"): [a.get("name") for a in n.get("attributes", [])] for n in nodes}
    for nid, names in attrs.items():
        if len(names) != len(set(names)):
            errors.append(f"{sid}: エンティティ {nid} の属性名が重複しています")
    pairs = {(e.get("from"), e.get("to")) for e in edges}
    for n in nodes:
        for a in n.get("attributes", []):
            if not a.get("fk"):
                continue
            target, _, column = a["fk"].partition(".")
            if column not in attrs.get(target, []):
                errors.append(f"{sid}: {n.get('id')}.{a.get('name')} の fk {a['fk']} の参照先がありません")
            elif (n.get("id"), target) not in pairs:
                errors.append(f"{sid}: {n.get('id')}.{a.get('name')} は {target} を参照しますが、"
                              f"関係 {n.get('id')} → {target}（from が外部キーを持つ側）がありません")
    by_id = {n.get("id"): n for n in nodes}
    claimed: dict[tuple[str, str], int] = {}
    for e in edges:
        src = by_id.get(e.get("from"), {})
        if not src.get("attributes"):
            if e.get("fk"):
                errors.append(f"{sid}: 関係 {e.get('from')} → {e.get('to')} の fk に対応する属性がありません")
            continue  # 属性の無い（v0.1 形式の）エンティティは FK を照合できない
        fks = {a["name"]: a["fk"].partition(".")[0] for a in src["attributes"] if a.get("fk")}
        candidates = [name for name, target in fks.items() if target == e.get("to")]
        if e.get("fk"):
            for name in e["fk"]:
                if fks.get(name) != e.get("to"):
                    errors.append(f"{sid}: 関係 {e.get('from')} → {e.get('to')} の fk「{name}」は {e.get('to')} を参照する外部キーではありません")
            used = e["fk"]
        else:
            if not candidates:
                errors.append(f"{sid}: 関係 {e.get('from')} → {e.get('to')} の from 側に {e.get('to')} を参照する外部キーがありません"
                              "（from は外部キーを持つ側。向きの反転の疑い）")
            elif sum(1 for o in edges if (o.get("from"), o.get("to")) == (e.get("from"), e.get("to"))) > 1:
                errors.append(f"{sid}: {e.get('from')} → {e.get('to')} の関係が複数あります。各関係の fk に外部キー属性名を指定してください")
            used = candidates
        for name in used:
            key = (e.get("from"), name)
            claimed[key] = claimed.get(key, 0) + 1
    errors += [f"{sid}: 外部キー {nid}.{name} が複数の関係で使われています" for (nid, name), n in claimed.items() if n > 1]
    ids = [e["id"] for e in edges if "id" in e]
    if len(ids) != len(set(ids)):
        errors.append(f"{sid}: 関係 ID が重複しています")
    return errors


# 引用符なしの値の途中にある「 #」は YAML ではコメントになり、以降の文言が黙って捨てられる
# （例: notes: 詳細は Issue #19 で検討 → 「詳細は Issue」になる）
TRAILING_COMMENT = re.compile(r"^[ \t]+#(.?)")


def yaml_comment_issues(path: Path) -> tuple[list[str], list[str]]:
    """文言の直後に「 #」があり、コメントとして切り捨てられている可能性のある値を返す。

    行の文字列ではなく YAML のスキャナのトークンで判定する。引用符付き・ブロックスカラー（| / >）の値は
    文字列として「#」を保持するため対象外で、引用符なしの値（plain scalar）の直後に同じ行でコメントが続く場合だけを見る。
    戻り値は（strict, loose）:
      - strict: 「#」の直後が空白でない（`Issue #19`、`#タグ` など）。値が一語でも文言の欠落とみなす。
        公開リポジトリ検査（--public-repo-check）では FAIL にする。
      - loose: 「 # 」と空白が続く。文言の後ろに意図して書いたコメントの可能性があるため警告に留める。
        識別子だけの設定値（`layout: cover  # 説明`）は意図したコメントとして対象外。
    意図したコメントを文言の後ろに書く場合は「 # 」（# の後ろに空白）とし、文言に # を含める場合は引用符で囲む。
    """
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    strict, loose = [], []
    for token in yaml.scan(text):
        if not isinstance(token, yaml.ScalarToken) or not token.plain:
            continue
        end = token.end_mark
        rest = lines[end.line][end.column:] if end.line < len(lines) else ""
        m = TRAILING_COMMENT.match(rest)
        if not m:
            continue
        line = lines[end.line]
        message = (f"{path.name}:{end.line + 1}: 「 #」以降が YAML のコメントとして捨てられます。"
                   f"文言なら引用符で囲んでください: {line.strip()[:60]}")
        if m.group(1) and not m.group(1).isspace():
            strict.append(message)
        # \w は和文も含むため、識別子は ASCII に限定する（「本文の文言  # メモ」は文言として警告）
        elif not re.fullmatch(r"[A-Za-z0-9_.-]+", token.value):
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
