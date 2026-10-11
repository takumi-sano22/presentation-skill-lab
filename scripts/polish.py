#!/usr/bin/env python3
"""描画後の装飾品質の仕上げ（#22）。上流レンダラが出力した PPTX の XML を決定論的に調整する。

内容（文字列・数値・表セル・グラフ値）は一切変えず、見せ方だけを変える。調整後の PPTX に対して
build.py の内容保持・幾何・編集性の検査をそのまま実行するため、仕上げで内容が崩れれば FAIL になる。

  - chart-single-series: 1系列の棒グラフでカテゴリごとに色を変えない（色に意味がないため。J-6）
  - table-columns: 表の列幅をセルの文字量に応じて配分する（長い SQL の列が4行に折り返す等を防ぐ）
  - table-rows: 行の少ない表は、下の要素に重ならない範囲で行の高さを広げ、版面の 55% を目安に埋める
  - table-monospace: design で指定した列（SQL・コード）を等幅フォントにする
  - title-balance: 折り返すタイトルの最終行が短すぎる（泣き別れ）とき、文字を縮めすぎずに行の長さを揃える
"""
from __future__ import annotations

import html
import math
import re
import unicodedata
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from diagram import label_lines  # noqa: E402  図のラベルと同じ改行位置の規則（禁則・語の切れ目）

EMU = 914400
SLIDE_H = 5.625
# 本文領域（見出し帯の下〜フッタの上）。diagram.py の描画領域と同じ
CONTENT_TOP, CONTENT_H = 1.35, 3.6
TABLE_FILL_TARGET = 0.55  # 版面に占める表の高さの目安（carnot 規約の翻案。docs/design-rules.md J-9）
TABLE_ROW_MAX_IN = 0.55
TABLE_MIN_COL_IN = 0.9
TABLE_MAX_COL_RATIO = 0.6
ORPHAN_MAX_CHARS = 3  # build.check_japanese と同じ（J-3）
TITLE_MIN_RATIO = 0.85  # 泣き別れの解消でタイトルを縮めるのは実効サイズの 85% まで
DEFAULT_CODE_FONT = "Consolas"


def text_width_in(text: str, pt: float) -> float:
    """文字幅の見積もり（インチ）。和欧文の境目の自動空き（約 1/4em）を含める。"""
    em, prev = 0.0, None
    for c in text:
        wide = unicodedata.east_asian_width(c) not in ("Na", "H")
        em += 1.0 if wide else 0.55
        if prev is not None and not c.isspace() and prev != wide:
            em += 0.25
        prev = None if c.isspace() else wide
    return em * pt / 72


def para_texts(block: str) -> list[str]:
    return [html.unescape("".join(re.findall(r"<a:t(?:\s[^>]*)?>([^<]*)</a:t>", p)))
            for p in re.findall(r"<a:p>.*?</a:p>|<a:p .*?</a:p>", block, re.S)]


# ---------------------------------------------------------------------------
# グラフ
# ---------------------------------------------------------------------------

def single_series_bar(chart_xml: str) -> tuple[str, bool]:
    """1系列の棒グラフのデータ点ごとの色指定（c:dPt）を外し、系列の色（アクセント）だけにする。"""
    if "<c:barChart>" not in chart_xml or chart_xml.count("<c:ser>") != 1 or "<c:dPt>" not in chart_xml:
        return chart_xml, False
    out = re.sub(r"\s*<c:dPt>.*?</c:dPt>", "", chart_xml, flags=re.S)
    out = re.sub(r'<c:varyColors val="1"/>', '<c:varyColors val="0"/>', out)
    return out, True


# ---------------------------------------------------------------------------
# 表
# ---------------------------------------------------------------------------

def table_blocks(xml: str):
    return list(re.finditer(r"<p:graphicFrame>.*?</p:graphicFrame>", xml, re.S))


def table_cells(block: str) -> list[list[str]]:
    return [re.findall(r"<a:tc>.*?</a:tc>", row, re.S) for row in re.findall(r"<a:tr .*?</a:tr>", block, re.S)]


def cell_pt(cell: str) -> float:
    m = re.search(r'<a:rPr[^>]*\ssz="(\d+)"', cell)
    return int(m.group(1)) / 100 if m else 12.0


def balance_columns(block: str) -> tuple[str, list[float] | None]:
    """列幅をセルの文字量（1行に並べた幅）に応じて配分する。差が小さければ変えない。"""
    widths = [int(w) for w in re.findall(r'<a:gridCol w="(\d+)"', block)]
    rows = table_cells(block)
    if len(widths) < 2 or not rows or any(len(r) != len(widths) for r in rows):
        return block, None
    total = sum(widths) / EMU
    need = []
    for c in range(len(widths)):
        cells = [r[c] for r in rows]
        need.append(max(text_width_in("".join(para_texts(cell)), cell_pt(cell)) + 0.2 for cell in cells))
    weights = [min(max(n, TABLE_MIN_COL_IN), total * TABLE_MAX_COL_RATIO) for n in need]
    if sum(need) <= total:
        # 全セルが1行に収まるなら、収まる幅を確保して残りを均等に配る
        spare = (total - sum(weights)) / len(weights)
        new = [w + spare for w in weights]
    else:
        new = [total * w / sum(weights) for w in weights]
    if max(new) / min(new) < 1.3 and max(widths) / min(widths) < 1.01:
        return block, None  # ほぼ均等で足りる表は上流の配分のまま
    emu = [round(w * EMU) for w in new]
    emu[-1] += sum(widths) - sum(emu)  # 丸め誤差で表の幅を変えない
    it = iter(emu)
    out = re.sub(r'<a:gridCol w="\d+"', lambda m: f'<a:gridCol w="{next(it)}"', block)
    return out, [round(w, 3) for w in new]


def frame_box(block: str) -> tuple[int, int, int, int]:
    m = re.search(r'<a:off x="(-?\d+)" y="(-?\d+)"/>\s*<a:ext cx="(\d+)" cy="(\d+)"/>', block)
    return tuple(int(v) for v in m.groups())


def enlarge_rows(block: str, limit_bottom_in: float) -> tuple[str, float | None]:
    """行の少ない表の行の高さを広げ、版面の TABLE_FILL_TARGET を目安に埋める（下の要素の手前まで）。"""
    heights = [int(h) for h in re.findall(r'<a:tr h="(\d+)"', block)]
    if not heights:
        return block, None
    x, y, cx, cy = frame_box(block)
    current = sum(heights) / EMU
    target = min(CONTENT_H * TABLE_FILL_TARGET, len(heights) * TABLE_ROW_MAX_IN, limit_bottom_in - y / EMU - 0.1)
    if target <= current + 0.05:
        return block, None
    scale = target / current
    new = [round(h * scale) for h in heights]
    it = iter(new)
    out = re.sub(r'<a:tr h="\d+"', lambda m: f'<a:tr h="{next(it)}"', block)
    out = out.replace(f'<a:ext cx="{cx}" cy="{cy}"/>', f'<a:ext cx="{cx}" cy="{sum(new)}"/>', 1)
    return out, round(target, 3)


def monospace_columns(block: str, columns: list[int], font: str) -> tuple[str, int]:
    """指定列（0 始まり、見出し行を除く）のセルの欧文書体を等幅にする。和文書体はそのまま（日本語の注記に備える）。"""
    count = 0

    def fix_row(row: str) -> str:
        nonlocal count
        cells = re.findall(r"<a:tc>.*?</a:tc>", row, re.S)
        for c in columns:
            if c < len(cells):
                new = re.sub(r'<a:latin typeface="[^"]*"', f'<a:latin typeface="{html.escape(font)}"', cells[c])
                row = row.replace(cells[c], new, 1)
                count += 1
        return row

    rows = re.findall(r"<a:tr .*?</a:tr>", block, re.S)
    out = block
    for row in rows[1:]:  # 見出し行は本文書体のまま
        out = out.replace(row, fix_row(row), 1)
    return out, count


def shapes_below(xml: str, table_block: str) -> float:
    """表の下にある描画オブジェクト（文字図形・画像・グラフ・別の表・線）のうち、表と横に重なるものの上端（インチ）。

    表を広げてよいのはその手前まで。無ければフッタの上端。表自身は除く。
    """
    tx, ty, tw, th = frame_box(table_block)
    tops = []
    for m in re.finditer(r"<p:(sp|pic|graphicFrame|cxnSp)>.*?</p:\1>", xml, re.S):
        block = m.group(0)
        if block == table_block:
            continue
        off = re.search(r'<a:off x="(-?\d+)" y="(-?\d+)"/>\s*<a:ext cx="(\d+)" cy="(\d+)"/>', block)
        if not off:
            continue
        x, y, w, _ = (int(v) for v in off.groups())
        if y >= ty + th - 1 and x < tx + tw and tx < x + w:
            tops.append(y / EMU)
    return min(tops, default=SLIDE_H - 0.75)


# ---------------------------------------------------------------------------
# タイトル
# ---------------------------------------------------------------------------

NO_LINE_START = set("、。，．・：；？！ー）」』】〕ぁぃぅぇぉっゃゅょゎァィゥェォッャュョヮヵヶ")


def wrap_lines(text: str, width_in: float, pt: float) -> list[str]:
    """文字単位の折返しの見積もり（行頭禁則の文字は前の行へ追い込む）。"""
    lines, cur = [], ""
    for c in text:
        if cur and text_width_in(cur + c, pt) > width_in and c not in NO_LINE_START:
            lines.append(cur)
            cur = c
        else:
            cur += c
    return lines + ([cur] if cur else [])


def fitted_pt(title: str, w: float, h: float, base: float, autofit: bool) -> float:
    """描画時の実効文字サイズ。縮小指定（normAutofit）の枠は、行数×行高が枠の高さに収まるまで縮む。"""
    pt = base
    while autofit and pt > 8 and len(wrap_lines(title, w, pt)) * pt * 1.2 / 72 > h + 0.01:
        pt -= 0.5
    return pt


def balance_title(block: str, title: str) -> tuple[str, dict | None]:
    """折り返すタイトルの最終行が ORPHAN_MAX_CHARS 以下（泣き別れ）なら、行の長さを揃える。

    自動縮小後の実効サイズで泣き別れを判定し、そのサイズから少しずつ下げて（実効サイズの TITLE_MIN_RATIO まで）、
    2行に収まるサイズで語の切れ目に明示改行（a:br）を入れる。文字列そのものは変えず、文字サイズは明示する。
    """
    sizes = [int(v) for v in re.findall(r'<a:rPr[^>]*\ssz="(\d+)"', block)]
    m = re.search(r'<a:off x="(-?\d+)" y="(-?\d+)"/>\s*<a:ext cx="(\d+)" cy="(\d+)"/>', block)
    if not sizes or not m:
        return block, None
    w, h = int(m.group(3)) / EMU, int(m.group(4)) / EMU
    effective = fitted_pt(title, w, h, sizes[0] / 100, "<a:normAutofit" in block)
    lines = wrap_lines(title, w, effective)
    if len(lines) < 2 or len(lines[-1]) > ORPHAN_MAX_CHARS:
        return block, None
    pt = effective
    while pt >= effective * TITLE_MIN_RATIO:
        # 2行に収まるサイズで、語の切れ目（diagram.label_lines と同じ規則）に明示改行を入れる
        split = label_lines(title, w, pt)
        if len(split) == 2 and 2 * pt * 1.2 / 72 <= h + 0.01 and all(text_width_in(t, pt) <= w for t in split) \
                and min(len(t) for t in split) > ORPHAN_MAX_CHARS:
            run = re.search(r"<a:r>(<a:rPr.*?</a:rPr>|<a:rPr[^>]*/>)<a:t>[^<]*</a:t></a:r>", block, re.S)
            if not run:
                return block, None
            rpr = run.group(1)
            two = (f"<a:r>{rpr}<a:t>{html.escape(split[0], quote=False)}</a:t></a:r><a:br>{rpr}</a:br>"
                   f"<a:r>{rpr}<a:t>{html.escape(split[1], quote=False)}</a:t></a:r>")
            out = block[:run.start()] + two + block[run.end():]
            out = re.sub(r'(<a:(?:rPr|endParaRPr)[^>]*\ssz=")\d+(")', lambda q: f"{q.group(1)}{round(pt * 100)}{q.group(2)}", out)
            return out, {"pt": round(pt, 1), "from_pt": round(effective, 1), "lines": split}
        pt -= 0.5
    return block, None


# ---------------------------------------------------------------------------
# 適用
# ---------------------------------------------------------------------------

def slide_names(z: zipfile.ZipFile) -> list[str]:
    return sorted((n for n in z.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
                  key=lambda n: int(re.findall(r"\d+", n)[0]))


def apply(pptx: Path, content: dict, outline: dict, design: dict) -> list[dict]:
    """PPTX を仕上げる。適用した調整の記録を返す（manifest の polish に残す）。"""
    with zipfile.ZipFile(pptx) as z:
        infos = z.infolist()
        items = {i.filename: z.read(i.filename) for i in infos}
        slides = slide_names(z)
    code_font = design["theme"]["fonts"].get("code", DEFAULT_CODE_FONT)
    record: list[dict] = []
    for name in [n for n in items if re.fullmatch(r"ppt/charts/chart\d+\.xml", n)]:
        xml, changed = single_series_bar(items[name].decode("utf-8"))
        if changed:
            items[name] = xml.encode("utf-8")
            record.append({"part": name, "fix": "chart-single-series"})
    for slide, o_slide, part in zip(content["slides"], outline["slides"], slides):
        sid = slide["id"]
        xml = items[part].decode("utf-8")
        override = design.get("overrides", {}).get(sid, {})
        for m in reversed(table_blocks(xml)):
            block = m.group(0)
            if "<a:tbl>" not in block:
                continue
            new, cols = balance_columns(block)
            if cols:
                record.append({"slide_id": sid, "fix": "table-columns", "widths_in": cols})
            if override.get("monospace_columns"):
                new, count = monospace_columns(new, override["monospace_columns"], code_font)
                record.append({"slide_id": sid, "fix": "table-monospace", "font": code_font, "cells": count})
            new, filled = enlarge_rows(new, shapes_below(xml, block))
            if filled:
                record.append({"slide_id": sid, "fix": "table-rows", "height_in": filled})
            xml = xml[:m.start()] + new + xml[m.end():]
        for m in reversed(list(re.finditer(r"<p:sp>.*?</p:sp>", xml, re.S))):
            block = m.group(0)
            if para_texts(block) != [slide["title"]]:
                continue
            new, info = balance_title(block, slide["title"])
            if info:
                record.append({"slide_id": sid, "fix": "title-balance", **info})
                xml = xml[:m.start()] + new + xml[m.end():]
            break
        items[part] = xml.encode("utf-8")
    tmp = pptx.with_suffix(".polish.pptx")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for info in infos:
            z.writestr(info, items[info.filename])
    tmp.replace(pptx)
    return record
