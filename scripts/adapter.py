#!/usr/bin/env python3
"""content.yaml / design.yaml を上流レンダラの outline.json へ決定論的に変換する adapter。

- 内容（文言・数値・単位・表セル）は content.yaml からのみ写し、design.yaml からは見せ方だけを写す。
- 変換後に意味項目（semantic items）を往復比較し、欠落・改変があれば FAIL する。
- 写像できない内容は黙って捨てたり画像化したりせず UnsupportedContent で FAIL する。
"""
from __future__ import annotations

import argparse
import hashlib
import copy
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import validate  # noqa: E402  入力契約の検証を共有する

ADAPTER_VERSION = "0.1.0"
SUPPORTED_SCHEMA_VERSIONS = {"0.1"}

# design.theme.name → 上流 deck_style（日本語テーマの本実装は #5）
# - renderer_role_systems_v1: v1 レイアウトに固定し、v2 契約が足す英語ラベル・プレースホルダ
#   （"TABLE INDEX" / "READOUT" / "Key readout" 等）を出さない（上流 B:1406 の互換ピン）
# - footer_source_label: 出典ラベルを日本語にする
_BASE_STYLE = {"renderer_role_systems_v1": {"pin": "v1"}, "footer_source_label": "出典"}
THEME_STYLES = {
    "technical-light": {"style_preset": "arctic-minimal", **_BASE_STYLE},
    "technical-dark": {"style_preset": "midnight-neon", **_BASE_STYLE},
}

# content.slide.type → (上流 type, variant)。layout override があればそちらを優先。
# role は指定しない（上流の role 契約が本文を quadrant 等へ組み替えるのを避け、variant 既定に任せる）
TYPE_MAP = {
    "cover": ("title", "title"),
    "section": ("section", "section"),
    "claim": ("content", "standard"),
    "appendix": ("content", "standard"),
    "comparison": ("content", "table"),
    "table": ("content", "table"),
    "chart": ("content", "chart"),
    "architecture": ("content", "standard"),
    "flow": ("content", "standard"),
    "er": ("content", "standard"),
}


# 上流 variant ごとに「描画される内容フィールド」と「必須フィールド」。
# ここにない組み合わせは描画で消えるため、写像前に一括で FAIL させる（個別分岐の取りこぼしを防ぐ）
VARIANT_FIELDS = {
    "title": ({"body", "notes"}, set()),
    "section": (set(), set()),
    "standard": ({"body", "diagram", "notes", "source_refs"}, set()),
    "table": ({"table", "body", "notes", "source_refs"}, {"table"}),
    "chart": ({"chart", "notes", "source_refs"}, {"chart"}),
}
CONTENT_FIELDS = {"body", "diagram", "table", "chart", "asset_ref", "source_refs", "notes"}
# 描画を確認済みのグラフ種別（円グラフは単位表示・凡例の検証が未了のため #5 まで対象外）
SUPPORTED_CHART_TYPES = {"bar", "line"}


class UnsupportedContent(ValueError):
    """outline.json へ忠実に写せない内容。黙って捨てずに FAIL させる。"""


class ContentMismatch(ValueError):
    """変換前後で意味項目が一致しない（欠落・改変・追加）。"""


def canonical_json(value: object) -> str:
    """正規化 JSON（キー順固定・UTF-8・末尾改行）。ハッシュ安定性の基準。NaN/Infinity は標準 JSON でないため拒否。"""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def content_hash(content: dict) -> str:
    # validate.py の content_sha256 と同じ正規化
    canonical = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256_text(canonical)


def format_number(value: float | int) -> str:
    """数値の文字列表現を固定する（20 と 20.0 を区別しない）。"""
    if isinstance(value, bool):
        raise UnsupportedContent(f"真偽値は数値として扱えません: {value}")
    if not math.isfinite(value):
        raise UnsupportedContent(f"有限でない数値は扱えません: {value}")
    return str(int(value)) if float(value).is_integer() else repr(float(value))


def table_caption(unit: str | None, period: str | None) -> str:
    """表の単位・期間を表示用 caption にする（逆写像でも同じ関数で照合する）。"""
    return " / ".join(f"{label}: {v}" for label, v in (("単位", unit), ("期間", period)) if v)


def chart_unit_title(unit: str) -> str:
    return f"単位: {unit}"


def diagram_lines(diagram: dict) -> list[str]:
    """図をテキスト行へ写す暫定フォールバック（ネイティブ図は #6）。

    すべてのノードラベルと矢印ラベルを残し、接続関係を「A → B（ラベル）」で表す。
    """
    labels = {n["id"]: n["label"] for n in diagram["nodes"]}
    lines = []
    for e in diagram.get("edges", []):
        suffix = f"（{e['label']}）" if e.get("label") else ""
        lines.append(f"{labels[e['from']]} → {labels[e['to']]}{suffix}")
    connected = {e["from"] for e in diagram.get("edges", [])} | {e["to"] for e in diagram.get("edges", [])}
    for n in diagram["nodes"]:
        # 区画（group）・説明（description）は内容なので表示する。接続のないノードも欠落させない
        detail = (f"［{n['group']}］" if n.get("group") else "") + (f"：{n['description']}" if n.get("description") else "")
        if detail or n["id"] not in connected:
            lines.append(n["label"] + detail)
    return lines


def diagram_items(diagram: dict) -> list[tuple[str, str]]:
    """図の意味項目。kind 等の見せ方に関わる属性も #6 で使うため欠落を検査する。"""
    items = []
    for n in diagram["nodes"]:
        items.append(("diagram.node", f"{n['id']}:{n['label']}"))
        for key in ("kind", "group", "description"):
            if n.get(key):
                items.append((f"diagram.node.{key}", f"{n['id']}:{n[key]}"))
    for e in diagram.get("edges", []):
        items.append(("diagram.edge", f"{e['from']}->{e['to']}:{e.get('label', '')}:{e.get('kind', '')}"))
    return items


# ---------------------------------------------------------------------------
# 意味項目: (slide_id, 種別, 値) の列。content 側と outline 側を同じ形に揃えて比較する。
# ---------------------------------------------------------------------------

DECK = "_deck"  # デッキ単位の意味項目に使う疑似 slide_id


def deck_items(deck_id: str, metadata: dict) -> list[tuple[str, str, str]]:
    """デッキメタデータ（deck_id・title・audience・objective 等）も欠落検査の対象にする。"""
    items = [(DECK, "deck_id", deck_id)]
    items += [(DECK, f"metadata.{k}", json.dumps(metadata[k], ensure_ascii=False)) for k in sorted(metadata)]
    return items


def semantic_items(content: dict) -> list[tuple[str, str, str]]:
    items: list[tuple[str, str, str]] = deck_items(content["deck_id"], content["metadata"])
    for s in content["slides"]:
        sid = s["id"]
        add = lambda kind, value: items.append((sid, kind, value))  # noqa: E731
        add("type", s["type"])
        add("title", s["title"])
        if s.get("takeaway"):
            add("takeaway", s["takeaway"])
        for b in s.get("body", []):
            add("body", b)
        if t := s.get("table"):
            for h in t["headers"]:
                add("table.header", h)
            for r, row in enumerate(t["rows"]):
                for c, cell in enumerate(row):
                    add(f"table.cell[{r}][{c}]", cell)
            for key in ("unit", "period"):
                if t.get(key):
                    add(f"table.{key}", t[key])
        if ch := s.get("chart"):
            add("chart.type", ch["type"])
            add("chart.unit", ch["unit"])
            for c in ch["categories"]:
                add("chart.category", c)
            for se in ch["series"]:
                add("chart.series", se["name"])
                for i, v in enumerate(se["values"]):
                    add(f"chart.value[{se['name']}][{i}]", format_number(v))
        if d := s.get("diagram"):
            for kind, value in diagram_items(d):
                add(kind, value)
        for ref in s.get("source_refs", []):
            add("source_ref", ref)
        if s.get("notes"):
            add("notes", s["notes"])
        if s.get("asset_ref"):
            add("asset_ref", s["asset_ref"])
    return items


def outline_semantic_items(outline: dict) -> list[tuple[str, str, str]]:
    """outline.json から意味項目を復元する。adapter の写像規則の逆写像。"""
    psl = outline["psl"]
    if outline["title"] != psl["metadata"]["title"]:
        raise ContentMismatch("デッキタイトルの表示が metadata.title と一致しません")
    items: list[tuple[str, str, str]] = deck_items(psl["deck_id"], psl["metadata"])
    for s in outline["slides"]:
        meta = s["psl"]
        sid = meta["slide_id"]
        add = lambda kind, value: items.append((sid, kind, value))  # noqa: E731
        add("type", meta["content_type"])
        add("title", s["title"])
        if s.get("subtitle"):
            add("takeaway", s["subtitle"])
        diagram = meta.get("diagram")
        bullets = list(s.get("bullets", []))
        if meta.get("cover_body"):
            if s.get("footer") != " ／ ".join(meta["cover_body"]):
                raise ContentMismatch(f"{sid}: 表紙本文の footer が一致しません")
            bullets = list(meta["cover_body"])
        if diagram:
            # 図のフォールバック行は bullets 末尾に付く。本文と分けて復元する
            fallback = diagram_lines(diagram)
            if bullets[len(bullets) - len(fallback):] != fallback:
                raise ContentMismatch(f"{sid}: 図のフォールバック行が一致しません")
            bullets = bullets[: len(bullets) - len(fallback)]
        for b in bullets:
            add("body", b)
        if meta.get("table_body"):
            bullets = list(s["table"].get("footnotes", []))
            for b in bullets:
                add("body", b)
        if t := s.get("table"):
            for h in t["headers"]:
                add("table.header", h)
            for r, row in enumerate(t["rows"]):
                for c, cell in enumerate(row):
                    add(f"table.cell[{r}][{c}]", cell)
            # 単位・期間は可視の caption から復元する（メタデータだけで一致させない）
            if t.get("caption", "") != table_caption(meta.get("table_unit"), meta.get("table_period")):
                raise ContentMismatch(f"{sid}: 表の単位・期間の表示が一致しません")
            for key in ("unit", "period"):
                if meta.get(f"table_{key}"):
                    add(f"table.{key}", meta[f"table_{key}"])
        if ch := s.get("chart"):
            add("chart.type", ch["type"])
            if s.get("caption") != chart_unit_title(meta["chart_unit"]):
                raise ContentMismatch(f"{sid}: グラフの単位表示が一致しません")
            add("chart.unit", meta["chart_unit"])
            for c in ch["categories"]:
                add("chart.category", c)
            for se in ch["series"]:
                add("chart.series", se["name"])
                for i, v in enumerate(se["values"]):
                    add(f"chart.value[{se['name']}][{i}]", format_number(v))
        if diagram:
            for kind, value in diagram_items(diagram):
                add(kind, value)
        for ref in s.get("sources", []):
            add("source_ref", ref)
        if meta.get("visible_note"):
            if s.get("footer") != meta["visible_note"]:
                raise ContentMismatch(f"{sid}: 注記の表示が一致しません")
            add("notes", meta["visible_note"])
        if meta.get("asset_ref"):
            add("asset_ref", meta["asset_ref"])
    return items


def verify_roundtrip(content: dict, outline: dict) -> None:
    """意味項目の完全一致（順序込み）を検査する。欠落・改変・追加のいずれも FAIL。"""
    before, after = semantic_items(content), outline_semantic_items(outline)
    if before == after:
        return
    missing = [i for i in before if i not in after]
    added = [i for i in after if i not in before]
    detail = f"欠落 {missing[:5]} / 追加・改変 {added[:5]}" if missing or added else "順序が変わっています"
    raise ContentMismatch(detail)


# ---------------------------------------------------------------------------
# 変換
# ---------------------------------------------------------------------------

def convert_slide(s: dict, override: dict) -> dict:
    sid = s["id"]
    # 上流へ写像先がない design 指定は、成功扱いで無視せず FAIL させる
    for key in ("asset_fit", "notes"):
        if key in override:
            raise UnsupportedContent(f"{sid}: design.overrides.{key} は未対応です（上流 v0.14.0 に写像先なし）")
    layout = override.get("layout", "auto")
    key = s["type"] if layout == "auto" else layout
    if key == "illustration":
        # 上流の image-sidebar は説明欄が空だと英語のプレースホルダを表示するため、#7 まで未対応
        raise UnsupportedContent(f"{sid}: illustration（画像スライド）は #7 で対応予定のため未対応です")
    if key not in TYPE_MAP:
        raise UnsupportedContent(f"{sid}: layout '{key}' に対応する上流 variant がありません")
    up_type, variant = TYPE_MAP[key]
    allowed, required = VARIANT_FIELDS[variant]
    present = {f for f in CONTENT_FIELDS if s.get(f)}
    if extra := sorted(present - allowed):
        raise UnsupportedContent(f"{sid}: layout '{key}'（上流 {variant}）では {extra} を表示できません")
    if lacking := sorted(required - present):
        raise UnsupportedContent(f"{sid}: layout '{key}'（上流 {variant}）には {lacking} が必要です")
    if "diagram_mode" in override and not s.get("diagram"):
        raise UnsupportedContent(f"{sid}: 図のないスライドに diagram_mode が指定されています")
    if s.get("chart") and s["chart"]["type"] not in SUPPORTED_CHART_TYPES:
        raise UnsupportedContent(f"{sid}: chart.type '{s['chart']['type']}' は描画検証が未了のため未対応（#5）")
    # psl: 上流レンダラは解釈しない追跡用メタデータ（安定ID・逆写像に必要な情報）
    meta: dict = {"slide_id": sid, "content_type": s["type"], "layout": layout}
    out: dict = {"type": up_type, "variant": variant, "title": s["title"], "psl": meta}
    if s.get("takeaway"):
        out["subtitle"] = s["takeaway"]
    bullets = list(s.get("body", []))

    # 上流 v0.14.0 はスライド単位の density を読まないため、追跡用に保持するだけにする（適用は #5）
    if override.get("density"):
        meta["density"] = override["density"]

    if t := s.get("table"):
        if variant != "table":
            raise UnsupportedContent(f"{sid}: 表を layout '{key}' では表示できません")
        out["table"] = {"headers": list(t["headers"]), "rows": [list(r) for r in t["rows"]]}
        caption = table_caption(t.get("unit"), t.get("period"))
        if caption:
            out["table"]["caption"] = caption
        for k in ("unit", "period"):
            if t.get(k):
                meta[f"table_{k}"] = t[k]

    if ch := s.get("chart"):
        if variant != "chart":
            raise UnsupportedContent(f"{sid}: グラフを layout '{key}' では表示できません")
        out["chart"] = {
            "type": ch["type"],
            "categories": list(ch["categories"]),
            "series": [{"name": se["name"], "values": list(se["values"])} for se in ch["series"]],
        }
        # 単位はグラフ注記（caption）で表示する。v1 レイアウトは値軸タイトルを描画しないため（数値自体は変更しない）
        out["caption"] = chart_unit_title(ch["unit"])
        meta["chart_unit"] = ch["unit"]

    if d := s.get("diagram"):
        if override.get("diagram_mode", "native") != "native":
            raise UnsupportedContent(f"{sid}: diagram_mode '{override['diagram_mode']}' は未対応（#6/#7）")
        # ネイティブ図（#6）までは全ラベル・接続をテキストで保持する明示的フォールバック
        meta["diagram"] = d
        meta["fallback"] = "diagram-as-text"
        bullets += diagram_lines(d)

    if variant == "table" and bullets:
        # 上流の表描画は bullets を表示しないため、本文は表の脚注（可視）として渡す
        out["table"]["footnotes"] = bullets
        meta["table_body"] = True
        bullets = []
    if variant == "chart" and bullets:
        raise UnsupportedContent(f"{sid}: グラフのスライドは本文を表示できません（注記 notes か別スライドへ）")
    if up_type == "section":
        # 上流の renderSection は title / subtitle しか描画しないため、それ以外は FAIL させる
        if bullets or s.get("source_refs") or s.get("notes") or s.get("asset_ref"):
            raise UnsupportedContent(f"{sid}: 中扉（section）は本文・出典・注記・画像を表示できません")
    if up_type == "title":
        # 上流の表紙は title / subtitle / footer しか表示しないため、本文は footer 行として表示する
        if s.get("source_refs") or (bullets and s.get("notes")) or s.get("asset_ref"):
            raise UnsupportedContent(f"{sid}: 表紙で表示できない要素（出典・本文と注記の併用・画像）があります")
        if bullets:
            meta["cover_body"] = bullets
            out["footer"] = " ／ ".join(bullets)
            bullets = []
    if bullets:
        out["bullets"] = bullets
    if s.get("source_refs"):
        out["sources"] = list(s["source_refs"])
    if s.get("notes"):
        # content.notes はスライド上に表示する注記。話者ノートにも残して PPTX 内で追跡可能にする
        meta["visible_note"] = s["notes"]
        out["footer"] = s["notes"]
        out["notes"] = s["notes"]
    return out


def convert(content: dict, design: dict) -> dict:
    if content.get("schema_version") not in SUPPORTED_SCHEMA_VERSIONS:
        raise UnsupportedContent(f"schema_version {content.get('schema_version')} は未対応")
    overrides = design.get("overrides", {})
    theme = design["theme"]
    meta = content["metadata"]
    outline = {
        "title": meta["title"],
        "deck_style": copy.deepcopy(THEME_STYLES[theme["name"]]),
        "document_metadata": {"author": "presentation-skill-lab"},
        "psl": {
            "adapter_version": ADAPTER_VERSION,
            "schema_version": content["schema_version"],
            "deck_id": content["deck_id"],
            "content_sha256": content_hash(content),
            "synthetic": meta["synthetic"],
            "classification": meta["classification"],
            # audience / objective / language / content_locked を含むメタデータ全体を保持する
            "metadata": meta,
            "theme": theme,
        },
        "slides": [convert_slide(s, overrides.get(s["id"], {})) for s in content["slides"]],
    }
    # 上流 v0.14.0 に写像先がなく未適用の design 指定を明示する（黙って無視しない。適用は #5）
    unapplied = ["theme.fonts", "theme.colors"]
    unapplied += [f"overrides.{s['psl']['slide_id']}.density" for s in outline["slides"] if s["psl"].get("density")]
    outline["psl"]["unapplied_design"] = unapplied
    verify_roundtrip(content, outline)
    return outline


def load_and_validate(content_path: Path, design_path: Path) -> tuple[dict, dict]:
    content = validate.load_yaml(content_path)
    design = validate.load_yaml(design_path)
    errors = validate.schema_errors(content, Path("content")) + validate.schema_errors(design, Path("design"))
    errors += validate.cross_validate(content, design, content_path.parent)
    if errors:
        raise ValueError("入力契約違反:\n" + "\n".join(f" - {e}" for e in errors))
    return content, design


def main() -> int:
    p = argparse.ArgumentParser(description="content.yaml / design.yaml → outline.json")
    p.add_argument("--content", required=True, type=Path)
    p.add_argument("--design", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    a = p.parse_args()
    try:
        content, design = load_and_validate(a.content, a.design)
        text = canonical_json(convert(content, design))
        # 書き込み失敗（権限・既存ディレクトリ・容量不足）も入力エラーと同じ FAIL 応答にする
        a.output.parent.mkdir(parents=True, exist_ok=True)
        a.output.write_text(text, encoding="utf-8")
    except (ValueError, OSError, validate.yaml.YAMLError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    unapplied = json.loads(text)["psl"]["unapplied_design"]
    if unapplied:
        print(f"WARN: 上流レンダラ未対応のため未適用の design 指定: {', '.join(unapplied)}", file=sys.stderr)
    print(f"PASS: {len(content['slides'])} スライドを変換 → {a.output}")
    print(f"outline_sha256: {sha256_text(text)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
