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
import zlib
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
MEDIA_TYPES = {".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}


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
    """(幅, 高さ, 透過あり, 色)。署名だけでなくチャンク構造・CRC・IDAT の展開サイズまで検証する。

    透過は IHDR の色タイプ（4/6）または tRNS チャンクで判定する。
    """
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise AssetError("PNG の署名がありません")
    pos, chunks = 8, []
    while pos < len(data):
        if pos + 12 > len(data):
            raise AssetError("PNG のチャンクが途中で切れています")
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        kind = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + length]
        if len(body) != length or pos + 12 + length > len(data):
            raise AssetError(f"PNG の {kind!r} チャンクが途中で切れています")
        crc = struct.unpack(">I", data[pos + 8 + length:pos + 12 + length])[0]
        if zlib.crc32(kind + body) != crc:
            raise AssetError(f"PNG の {kind!r} チャンクの CRC が一致しません")
        chunks.append((kind, body))
        pos += 12 + length
        if kind == b"IEND":
            break
    if not chunks or chunks[0][0] != b"IHDR" or len(chunks[0][1]) != 13:
        raise AssetError("PNG の先頭が IHDR ではありません")
    if chunks[-1][0] != b"IEND" or pos != len(data):
        raise AssetError("PNG が IEND で終わっていません")
    width, height, depth, color_type, _, _, interlace = struct.unpack(">IIBBBBB", chunks[0][1])
    idat = b"".join(body for kind, body in chunks if kind == b"IDAT")
    if not idat:
        raise AssetError("PNG に画素データ（IDAT）がありません")
    try:
        raw = zlib.decompress(idat)
    except zlib.error as exc:
        raise AssetError(f"PNG の画素データを展開できません（{exc}）") from exc
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color_type)
    if channels is None:
        raise AssetError(f"PNG の色タイプ {color_type} は不正です")
    if interlace == 0 and len(raw) != height * (1 + (width * channels * depth + 7) // 8):
        raise AssetError("PNG の画素データの大きさが寸法と一致しません")
    alpha = color_type in (4, 6) or any(kind == b"tRNS" for kind, _ in chunks)
    color = {0: "gray", 2: "rgb", 3: "indexed", 4: "gray", 6: "rgb"}[color_type]
    return width, height, alpha, color


def jpeg_info(data: bytes) -> tuple[int, int, bool, str]:
    """(幅, 高さ, False, 色) — SOF マーカーから寸法と成分数（4 = CMYK）を読む。"""
    i = 2
    while i + 4 <= len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker, length = data[i + 1], struct.unpack(">H", data[i + 2:i + 4])[0]
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            if i + 10 > len(data):
                break  # 途中で切れた JPEG
            height, width, comps = struct.unpack(">HHB", data[i + 5:i + 10])
            return width, height, False, "cmyk" if comps == 4 else "rgb"
        i += 2 + length
    raise AssetError("JPEG の寸法を読めません")


# SVG の長さ単位 → px（CSS の 96dpi 基準）
SVG_UNITS = {"": 1.0, "px": 1.0, "pt": 96 / 72, "pc": 16.0, "in": 96.0, "cm": 96 / 2.54, "mm": 96 / 25.4}


def svg_length(value: str | None) -> float | None:
    m = re.fullmatch(r"\s*([0-9.]+)\s*([a-z]*)\s*", value or "")
    if not m or m.group(2) not in SVG_UNITS:
        return None  # 未指定・% 等は固有サイズにならない
    return float(m.group(1)) * SVG_UNITS[m.group(2)]


def svg_info(data: bytes) -> tuple[int, int, ET.Element]:
    """固有サイズ（px）。Office と同じく width/height を優先し、無い・% のときだけ viewBox を使う。"""
    root = ET.fromstring(data)
    w, h = svg_length(root.get("width")), svg_length(root.get("height"))
    if w is None or h is None:
        view_box = root.get("viewBox")
        if not view_box:
            raise AssetError("SVG に width/height も viewBox もありません")
        _, _, vw, vh = (float(v) for v in re.split(r"[\s,]+", view_box.strip()))
        w, h = (w if w is not None else vw), (h if h is not None else vh)
    return round(w), round(h), root


def svg_has_opaque_background(root: ET.Element, width: int, height: int) -> bool:
    """最初に描かれる図形が全面を覆う不透明な矩形なら背景あり（透過なし）とみなす。

    SVG の透過は描画結果でしか厳密に決まらないため、背景矩形の有無で判定する（docs/assets.md）。
    """
    for el in root:
        tag = el.tag.replace(SVG_NS, "")
        if tag in ("defs", "title", "desc", "metadata", "style"):
            continue
        if tag != "rect":
            return False
        def num(key: str, default: str) -> str:
            return el.get(key, default).strip()
        full_w = num("width", "0") in ("100%", str(width)) or num("width", "0").replace(".0", "") == str(width)
        full_h = num("height", "0") in ("100%", str(height)) or num("height", "0").replace(".0", "") == str(height)
        at_origin = float(re.sub(r"[a-z%]+$", "", num("x", "0")) or 0) == 0 and float(re.sub(r"[a-z%]+$", "", num("y", "0")) or 0) == 0
        style = el.get("style", "")
        fill = el.get("fill", "black")
        m = re.search(r"fill\s*:\s*([^;]+)", style)
        fill = (m.group(1) if m else fill).strip().lower()
        opacities = [el.get(k) for k in ("opacity", "fill-opacity")] + re.findall(r"(?:^|;)\s*(?:fill-)?opacity\s*:\s*([0-9.]+)", style)
        translucent = any(v is not None and float(v) < 1 for v in opacities)
        opaque_fill = fill not in ("none", "transparent") and not fill.startswith(("rgba", "hsla"))
        return full_w and full_h and at_origin and opaque_fill and not translucent
    return False


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
        # url(...) はすべての属性値（fill / filter / clip-path / style 等）と <style> 本文で検査する。
        # 参照先を引用符を除いて取り出し、同一文書内（#id）以外を外部参照とする
        values = list(el.attrib.values()) + ([el.text or ""] if tag == "style" else [])
        for value in values:
            targets = [t.strip().strip("'\"").strip() for t in re.findall(r"url\(([^)]*)\)", value)]
            if any(not t.startswith("#") for t in targets) or "@import" in value:
                errors.append(f"SVG に外部参照があります（url/@import）: {value[:60]}")
    return errors


def check_entry(deck_dir: Path, entry: dict) -> list[str]:
    path = deck_dir / entry["path"]
    tag = entry["path"]
    if not path.is_file():
        return [f"{tag}: ファイルがありません"]
    data = path.read_bytes()
    errors = []
    # レンダラは拡張子で形式を判断するため、拡張子と media_type の対応を必須にする
    if MEDIA_TYPES[path.suffix.lower()] != entry["media_type"]:
        errors.append(f"{tag}: 拡張子 {path.suffix} と media_type {entry['media_type']} が一致しません")
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
            alpha, color = not svg_has_opaque_background(root, width, height), "rgb"
        elif entry["media_type"] == "image/png":
            width, height, alpha, color = png_info(data)
        else:
            width, height, alpha, color = jpeg_info(data)
    except (AssetError, ET.ParseError, ValueError, struct.error, IndexError) as exc:
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
