#!/usr/bin/env python3
"""画像アセット（<deck>/assets/）の manifest 検査。

権利不明素材・未登録ファイル・差し替え後のハッシュ不一致・解像度不足・透過や比率の不整合・
SVG の外部参照や文字の焼き込みを、決定論的に検出する（CI とビルドの両方で使う）。
    python3 scripts/assets.py examples/<deck>   # <deck>/assets/manifest.yaml を検査
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = json.loads((ROOT / "schemas" / "asset-manifest.schema.json").read_text(encoding="utf-8"))
MANIFEST = "assets/manifest.yaml"
# 再配布・改変に問題のないライセンスだけを自動で許可する。それ以外は人のレビュー（停止条件）へ回す
ALLOWED_LICENSES = {"MIT", "CC0-1.0", "CC-BY-4.0", "Apache-2.0"}
ATTRIBUTION_REQUIRED = {"CC-BY-4.0"}
# ラスタ画像は長辺この画素数以上（16:9 全面配置で約 175dpi）
MIN_RASTER_LONG_SIDE = 1600
# assets/ に置いてよい manifest 以外の補助ファイル（生成元の記録）
AUXILIARY_SUFFIXES = {".md", ".txt", ".html", ".css"}
SVG_NS = "{http://www.w3.org/2000/svg}"


class AssetError(ValueError):
    """アセット manifest の検査違反。"""


def load_manifest(deck_dir: Path) -> dict:
    path = deck_dir / MANIFEST
    if not path.is_file():
        return {"schema_version": "0.1", "assets": []}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    errors = [f"{MANIFEST}: {'.'.join(map(str, e.absolute_path)) or '(root)'}: {e.message}"
              for e in Draft202012Validator(SCHEMA).iter_errors(data)]
    if errors:
        raise AssetError("; ".join(errors))
    return data


def png_info(data: bytes) -> tuple[int, int, bool, str]:
    """(幅, 高さ, 透過あり, 色) — IHDR の色タイプと tRNS チャンクで透過を判定する。"""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise AssetError("PNG の署名がありません")
    width, height, _, color_type = struct.unpack(">IIBB", data[16:26])
    alpha = color_type in (4, 6) or b"tRNS" in data[:data.find(b"IDAT")]
    color = {0: "gray", 2: "rgb", 3: "indexed", 4: "gray", 6: "rgb"}.get(color_type, "unknown")
    return width, height, alpha, color


def jpeg_info(data: bytes) -> tuple[int, int, bool, str]:
    """(幅, 高さ, False, 色) — SOF マーカーから寸法と成分数（4 = CMYK）を読む。"""
    i = 2
    while i < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker, length = data[i + 1], struct.unpack(">H", data[i + 2:i + 4])[0]
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            height, width, comps = struct.unpack(">HHB", data[i + 5:i + 10])
            return width, height, False, "cmyk" if comps == 4 else "rgb"
        i += 2 + length
    raise AssetError("JPEG の寸法を読めません")


def svg_info(data: bytes) -> tuple[int, int, ET.Element]:
    root = ET.fromstring(data)
    view_box = root.get("viewBox")
    if view_box:
        _, _, w, h = (float(v) for v in re.split(r"[\s,]+", view_box.strip()))
    else:
        w, h = (float(re.sub(r"[a-z%]+$", "", root.get(k, "0"))) for k in ("width", "height"))
    return round(w), round(h), root


def check_svg(root: ET.Element, entry: dict) -> list[str]:
    errors = []
    text_nodes = [el for el in root.iter() if el.tag in (f"{SVG_NS}text", "text")]
    if text_nodes and not entry["contains_text"]:
        errors.append("SVG に文字（<text>）がありますが contains_text: false です")
    for el in root.iter():
        tag = el.tag.replace(SVG_NS, "")
        if tag in ("script", "foreignObject"):
            errors.append(f"SVG に <{tag}> は使えません")
        for key, value in el.attrib.items():
            # 外部参照は描画環境で欠落し、権利も追えないため禁止（同一文書内の #id 参照は可）
            if key.endswith("href") and not value.startswith("#"):
                errors.append(f"SVG に外部参照があります: {value[:60]}")
        style = (el.text or "") if tag == "style" else el.get("style", "")
        if re.search(r"url\(\s*['\"]?(?!#)", style) or "@import" in style:
            errors.append("SVG のスタイルに外部参照があります")
    return errors


def check_entry(deck_dir: Path, entry: dict) -> list[str]:
    path = deck_dir / entry["path"]
    tag = entry["path"]
    if not path.is_file():
        return [f"{tag}: ファイルがありません"]
    data = path.read_bytes()
    errors = []
    if hashlib.sha256(data).hexdigest() != entry["sha256"]:
        errors.append(f"{tag}: sha256 が manifest と一致しません（差し替え後は manifest を更新）")
    origin, lic = entry["origin"], entry["license"]
    # 権利: 許可ライセンスのみ自動通過。出自ごとの必須記録
    if lic not in ALLOWED_LICENSES:
        errors.append(f"{tag}: ライセンス「{lic}」は自動許可の対象外（権利不明・要レビュー）")
    if lic in ATTRIBUTION_REQUIRED and not entry.get("attribution"):
        errors.append(f"{tag}: {lic} には attribution（帰属表示）が必要です")
    if origin["type"] == "third_party" and not (origin.get("source_url") and entry.get("attribution")):
        errors.append(f"{tag}: 第三者素材には origin.source_url と attribution が必要です")
    if origin["type"] == "generated" and not (origin.get("tool") and origin.get("prompt_file")):
        errors.append(f"{tag}: 生成画像には origin.tool と origin.prompt_file（生成指示の記録）が必要です")
    if origin["type"] == "authored" and not origin.get("author"):
        errors.append(f"{tag}: 自作素材には origin.author が必要です")
    for key in ("prompt_file", "source_file"):
        if origin.get(key) and not (deck_dir / origin[key]).is_file():
            errors.append(f"{tag}: origin.{key} {origin[key]} がありません")
    if origin.get("source_file") and not origin.get("conversion"):
        errors.append(f"{tag}: source_file から作った画像には origin.conversion（変換手順）が必要です")
    if entry["contains_text"] and not entry.get("text_reason"):
        errors.append(f"{tag}: 文字を含む画像には text_reason（画像化してよい理由）が必要です")
    # 形式ごとの実体検査
    try:
        if entry["media_type"] == "image/svg+xml":
            width, height, root = svg_info(data)
            errors += [f"{tag}: {e}" for e in check_svg(root, entry)]
            alpha, color = entry["transparent"], "rgb"
        elif entry["media_type"] == "image/png":
            width, height, alpha, color = png_info(data)
        else:
            width, height, alpha, color = jpeg_info(data)
    except (AssetError, ET.ParseError, ValueError, struct.error) as exc:
        return errors + [f"{tag}: 画像を解析できません（{exc}）"]
    if (width, height) != (entry["width"], entry["height"]):
        errors.append(f"{tag}: 寸法 {width}x{height} が manifest の {entry['width']}x{entry['height']} と一致しません")
    if alpha != entry["transparent"]:
        errors.append(f"{tag}: 透過（実体 {alpha}）が manifest の transparent: {entry['transparent']} と一致しません")
    if color == "cmyk":
        errors.append(f"{tag}: CMYK 画像は使えません（RGB に変換）")
    if entry["media_type"] != "image/svg+xml" and max(width, height) < MIN_RASTER_LONG_SIDE:
        errors.append(f"{tag}: 解像度不足（長辺 {max(width, height)}px < {MIN_RASTER_LONG_SIDE}px）")
    return errors


def check_deck(deck_dir: Path) -> list[str]:
    """deck の assets/ 全体を検査し、違反の一覧を返す。"""
    try:
        manifest = load_manifest(deck_dir)
    except (AssetError, yaml.YAMLError) as exc:
        return [str(exc)]
    errors = []
    listed = [e["path"] for e in manifest["assets"]]
    if len(listed) != len(set(listed)):
        errors.append("manifest に同じ path が重複しています")
    referenced = set(listed) | {e["origin"][k] for e in manifest["assets"] for k in ("prompt_file", "source_file")
                                if e["origin"].get(k)}
    assets_dir = deck_dir / "assets"
    for f in sorted(assets_dir.rglob("*")) if assets_dir.is_dir() else []:
        rel = f.relative_to(deck_dir).as_posix()
        if f.is_dir() or rel in (MANIFEST, "assets/README.md"):
            continue
        # 未登録の画像・補助ファイルは出自が追えない（権利不明素材として扱う）
        if rel not in referenced:
            kind = "補助ファイル" if f.suffix in AUXILIARY_SUFFIXES else "ファイル"
            errors.append(f"{rel}: manifest に登録されていない{kind}です（出自・権利が不明）")
    for entry in manifest["assets"]:
        errors += check_entry(deck_dir, entry)
    return errors


def asset_entry(deck_dir: Path, asset_ref: str) -> dict:
    """content の asset_ref に対応する manifest のエントリ（無ければ AssetError）。"""
    for entry in load_manifest(deck_dir)["assets"]:
        if entry["path"] == asset_ref:
            return entry
    raise AssetError(f"{asset_ref} が {MANIFEST} に登録されていません")


def main() -> int:
    p = argparse.ArgumentParser(description="画像アセット manifest の検査")
    p.add_argument("decks", nargs="+", type=Path, help="content.yaml のあるディレクトリ")
    a = p.parse_args()
    failed = False
    for deck in a.decks:
        errors = check_deck(deck)
        if errors:
            failed = True
            print(f"FAIL: {deck}")
            for e in errors:
                print(f" - {e}")
        else:
            print(f"PASS: {deck}（アセット {len(load_manifest(deck)['assets'])} 件）")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
