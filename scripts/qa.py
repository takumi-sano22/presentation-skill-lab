#!/usr/bin/env python3
"""生成 PPTX の総合 QA（幾何・文字サイズ・編集性）。

build.py の内容保持検査（PPTX/PDF のテキスト照合）・図の関係検査と合わせて使う。
ここでは PPTX パッケージの XML だけから、次を決定論的に検査する:
  - geometry: スライド外へのはみ出し、文字を持つ図形どうしの重なり、文字量の推定あふれ
  - typography: 最小文字サイズ
  - connector: 図の線分がノード以外の図形（他ノード・ラベル）を貫通しない
  - editability: 表・グラフ・図・本文が画像化されていない（ネイティブの表/グラフ/図形/テキスト）
誤検知の除外は qa-exceptions.yaml（Slide ID・検査ID・対象・理由が必須）でだけ行う。
"""
from __future__ import annotations

import html
import re
import unicodedata
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import yaml

EMU = 914400
SLIDE_W, SLIDE_H = 10.0, 5.625
# 本文・注記の最小文字サイズ（pt）。グラフ内の軸ラベルは別パーツなので対象外
MIN_FONT_PT = 9.0
# 文字あふれの推定: 行高 = 文字サイズ × 係数、許容率
LINE_HEIGHT = 1.25
OVERFLOW_TOLERANCE = 1.15
HALF_WIDTH_EM = 0.55
# あふれがここより下（フッタ・出典行の領域）に達したら崩れとみなす
FOOTER_RESERVED = 0.5
EXCEPTIONS_FILE = "qa-exceptions.yaml"
CHECK_IDS = {"out-of-bounds", "text-overlap", "text-overflow", "min-font", "connector-crossing",
             "rasterized-table", "rasterized-chart", "rasterized-diagram", "missing-native-table",
             "missing-native-chart", "autofit-expansion"}


@dataclass
class Shape:
    name: str
    kind: str  # sp / pic / graphicFrame / cxnSp
    x: float
    y: float
    w: float
    h: float
    texts: list[str] = field(default_factory=list)
    font_sizes: list[float] = field(default_factory=list)
    graphic: str = ""  # tbl / chart
    filled: bool = False
    flip: bool = False  # 線: flipH と flipV のどちらか一方だけなら右上がりの対角線
    insets: tuple[float, float, float, float] = (0.1, 0.05, 0.1, 0.05)  # 左・上・右・下（インチ）
    # 文字の自動調整（OOXML の bodyPr 子要素）。2 つは意味が逆なので区別する:
    #   "norm" = normAutofit: 文字を縮小して枠に収める（枠は不変）
    #   "shape" = spAutoFit: 枠そのものを文字に合わせて伸ばす（文字は縮まない。伸びた枠が他要素と衝突し得る）
    autofit: str = ""
    anchor: str = "t"  # 文字の縦位置。spAutoFit で枠が上下どちらへ伸びるかを決める
    wrap: bool = True  # bodyPr wrap="none" なら折り返さず、spAutoFit で枠が横にも伸びる
    # 段落ごとの水平位置（l / ctr / r。texts と同じ順）。折り返さない spAutoFit で各段落が左右どちらへ伸びるかを決める
    aligns: list[str] = field(default_factory=list)
    font_scale: float = 1.0  # normAutofit に記録された縮小率（PowerPoint が保存した場合）

    @property
    def text(self) -> str:
        return "".join(self.texts)

    def intersection(self, other: "Shape") -> float:
        dx = min(self.x + self.w, other.x + other.w) - max(self.x, other.x)
        dy = min(self.y + self.h, other.y + other.h) - max(self.y, other.y)
        return dx * dy if dx > 0 and dy > 0 else 0.0


@dataclass
class Finding:
    slide_id: str
    check: str
    target: str
    message: str
    severity: str = "error"  # error（FAIL）/ warning


def paragraph_align(para: str) -> str:
    """段落の水平位置（a:pPr の algn。省略時は左揃え）。"""
    m = re.search(r'<a:pPr[^>]*\salgn="(\w+)"', para)
    return m.group(1) if m else "l"


def parse_shapes(xml: str) -> list[Shape]:
    shapes = []
    for m in re.finditer(r"<p:(sp|pic|graphicFrame|cxnSp)>.*?</p:\1>", xml, re.S):
        kind, block = m.group(1), m.group(0)
        name_m = re.search(r'<p:cNvPr[^>]*name="([^"]*)"', block)
        off = re.search(r'<a:off x="(-?\d+)" y="(-?\d+)"/>\s*<a:ext cx="(\d+)" cy="(\d+)"/>', block)
        if not off:
            continue
        x, y, cx, cy = (int(v) / EMU for v in off.groups())
        paras = re.findall(r"<a:p>.*?</a:p>|<a:p .*?</a:p>", block, re.S)
        texts = [html.unescape("".join(re.findall(r"<a:t(?:\s[^>]*)?>([^<]*)</a:t>", p))) for p in paras]
        aligns = [paragraph_align(p) for p in paras]
        sizes = [int(v) / 100 for v in re.findall(r'<a:rPr[^>]*\ssz="(\d+)"', block)]
        graphic = "tbl" if "<a:tbl>" in block else ("chart" if "/chart\"" in block or "c:chart" in block else "")
        filled = bool(re.search(r"<p:spPr>.*?<a:solidFill>", block, re.S))
        xfrm = re.search(r"<a:xfrm([^>]*)>", block)
        attrs = xfrm.group(1) if xfrm else ""
        flip = ('flipH="1"' in attrs) != ('flipV="1"' in attrs)
        body = re.search(r"<a:bodyPr([^>]*)>", block)
        battrs = body.group(1) if body else ""
        def inset(key: str, default: float) -> float:
            m = re.search(rf'{key}="(\d+)"', battrs)
            return int(m.group(1)) / EMU if m else default
        insets = (inset("lIns", 0.1), inset("tIns", 0.05), inset("rIns", 0.1), inset("bIns", 0.05))
        autofit = "norm" if "<a:normAutofit" in block else ("shape" if "<a:spAutoFit" in block else "")
        anchor_m = re.search(r'anchor="(\w+)"', battrs)
        scale_m = re.search(r'<a:normAutofit[^>]*fontScale="(\d+)"', block)
        font_scale = int(scale_m.group(1)) / 100000 if scale_m else 1.0
        shapes.append(Shape(html.unescape(name_m.group(1)) if name_m else "", kind, x, y, cx, cy,
                            [t for t in texts if t.strip()], sizes, graphic, filled, flip, insets, autofit=autofit, font_scale=font_scale,
                            anchor=anchor_m.group(1) if anchor_m else "t", wrap='wrap="none"' not in battrs,
                            aligns=[a for t, a in zip(texts, aligns) if t.strip()]))
    return shapes


def text_width_in(text: str, pt: float) -> float:
    em = sum(HALF_WIDTH_EM if unicodedata.east_asian_width(c) in ("Na", "H") else 1.0 for c in text)
    return em * pt / 72


def estimated_text_height(shape: Shape, pt: float | None = None) -> float:
    """段落ごとに折返し行数を見積もった文字の高さ（インチ）。内側余白は bodyPr の値を使う。"""
    pt = pt or (max(shape.font_sizes) if shape.font_sizes else 18.0)
    left, top, right, bottom = shape.insets
    usable = max(0.1, shape.w - left - right)
    # 折り返さない spAutoFit の枠は段落ごとに1行（横へ伸びる）。それ以外は従来どおり枠幅で折り返して見積もる
    if not shape.wrap and shape.autofit == "shape":
        lines = len(shape.texts)
    else:
        lines = sum(max(1, -(-text_width_in(t, pt) // usable)) for t in shape.texts)
    return lines * pt * LINE_HEIGHT / 72 + top + bottom


def autofit_font_pt(shape: Shape) -> float:
    """自動縮小の枠で、文字が収まるまで縮めたときの推定文字サイズ（pt）。

    PowerPoint が保存した縮小率があればそれを使い、無ければ 0.5pt 刻みで収まる最大サイズを探す。
    """
    base = max(shape.font_sizes) if shape.font_sizes else 18.0
    if shape.font_scale < 1.0:
        return base * shape.font_scale
    pt = base
    while pt > 1.0 and estimated_text_height(shape, pt) > shape.h * OVERFLOW_TOLERANCE:
        pt -= 0.5
    return pt


def load_exceptions(deck_dir: Path) -> list[dict]:
    """誤検知の除外。Slide ID・検査ID・対象・理由のいずれかが欠けていれば例外として不正。"""
    path = deck_dir / EXCEPTIONS_FILE
    if not path.is_file():
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"{EXCEPTIONS_FILE}: YAML として読めません（{exc}）") from exc
    if not isinstance(data, dict) or not isinstance(data.get("exceptions", []), list):
        raise ValueError(f"{EXCEPTIONS_FILE}: ルートは exceptions のリストを持つオブジェクトにしてください")
    items = data.get("exceptions", [])
    for i, e in enumerate(items):
        if not isinstance(e, dict):
            raise ValueError(f"{EXCEPTIONS_FILE}: exceptions[{i}] はオブジェクトにしてください")
        missing = [k for k in ("slide_id", "check", "target", "reason") if not str(e.get(k, "")).strip()]
        if missing:
            raise ValueError(f"{EXCEPTIONS_FILE}: exceptions[{i}] に {missing} がありません（Slide ID と理由は必須）")
        if e["check"] not in CHECK_IDS:
            raise ValueError(f"{EXCEPTIONS_FILE}: exceptions[{i}] の check「{e['check']}」は存在しません")
    return items


def check_slide(sid: str, slide: dict, o_slide: dict, shapes: list[Shape]) -> list[Finding]:
    findings: list[Finding] = []
    add = lambda check, target, msg, sev="error": findings.append(Finding(sid, check, target, msg, sev))  # noqa: E731
    # geometry: スライド外へのはみ出し（0.01in の誤差は許容）
    for s in shapes:
        if s.x < -0.01 or s.y < -0.01 or s.x + s.w > SLIDE_W + 0.01 or s.y + s.h > SLIDE_H + 0.01:
            # 文字・表・グラフ・画像のはみ出しは重大。文字のない装飾図形は見えないだけなので警告
            severe = bool(s.text.strip()) or s.kind in ("pic", "graphicFrame")
            add("out-of-bounds", s.name, f"図形がスライド外にはみ出します（{s.x:.2f},{s.y:.2f} {s.w:.2f}x{s.h:.2f}）",
                "error" if severe else "warning")
    # geometry: 文字を持つ図形どうしの重なり（重なり面積が小さい方の 10% 超）
    texted = [s for s in shapes if s.text.strip() and s.kind == "sp"]
    for i, a in enumerate(texted):
        for b in texted[i + 1:]:
            area = a.intersection(b)
            if area > 0.1 * min(a.w * a.h, b.w * b.h):
                add("text-overlap", f"{a.name} / {b.name}", f"文字を持つ図形が重なります（「{a.text[:12]}」と「{b.text[:12]}」）")
    # geometry: 文字量の推定あふれ
    visible = texted + [o for o in shapes if o.kind in ("pic", "graphicFrame")]
    for s in texted:
        if s.autofit == "shape":
            findings += check_shape_autofit(sid, s, visible)
            continue
        if s.autofit == "norm":
            # 縮小して収める枠はあふれないが、縮小後の実効サイズが最小を下回れば J-1 違反
            effective = autofit_font_pt(s)
            if effective < MIN_FONT_PT:
                add("min-font", s.name, f"自動縮小で約 {effective:.1f}pt まで縮む見込み（最小 {MIN_FONT_PT}pt）「{s.text[:16]}」")
            continue
        need = estimated_text_height(s)
        if need > s.h * OVERFLOW_TOLERANCE and need - s.h > 0.12:
            # あふれた部分（枠の下に伸びる範囲）が他の文字図形と重なるかスライド外に出れば崩れ（FAIL）。
            # 空き領域に収まるだけなら見た目は崩れないため警告に留める
            spill = Shape(s.name, s.kind, s.x, s.y + s.h, s.w, need - s.h)
            # 文字図形に加え、画像・表・グラフ（可視の内容）との衝突も崩れとみなす。文字のない装飾図形は除く
            collides = [o for o in visible if o is not s and spill.intersection(o) > 0.01]
            beyond = s.y + need > SLIDE_H - FOOTER_RESERVED
            severity = "error" if collides or beyond else "warning"
            hit = collides[0].text[:10] or collides[0].name if collides else ""
            where = f"「{hit}」と重なる" if collides else ("スライド下端に達する" if beyond else "下の空き領域に収まる")
            add("text-overflow", s.name,
                f"文字が枠からあふれる見込み（必要 {need:.2f}in > 枠 {s.h:.2f}in、{where}）「{s.text[:16]}」", severity)
    # typography: 最小文字サイズ
    for s in texted:
        small = [pt for pt in s.font_sizes if pt < MIN_FONT_PT]
        if small:
            add("min-font", s.name, f"{min(small)}pt の文字があります（最小 {MIN_FONT_PT}pt）「{s.text[:16]}」")
    # connector: 図の線分がノード以外の文字図形を貫通しない
    lay = o_slide["psl"].get("diagram_layout")
    if lay:
        obstacles = [s for s in texted if s.name.startswith(("node:", "edge-label:", "group-label:", "legend:"))]
        for seg in (s for s in shapes if s.name.startswith("edge:")):
            key = seg.name.split("#")[0][len("edge:"):]
            index, ends = key.split(":", 1)
            src, dst = ends.split("->")
            for ob in obstacles:
                # 端点のノードと、その辺自身のラベル（密な図では線上配置を許している）は除く
                if ob.name in (f"node:{src}", f"node:{dst}") or ob.name.startswith(f"edge-label:{index}:"):
                    continue
                if segment_crosses(seg, ob):
                    add("connector-crossing", f"{seg.name} / {ob.name}", f"線が「{ob.text[:12]}」を貫通します")
    # editability: 表・グラフ・図・本文が画像化されていない
    pics = [s for s in shapes if s.kind == "pic"]
    allowed_pics = {f"asset:{o_slide['psl']['image']['asset_ref']}"} if o_slide["psl"].get("image") else set()
    for p in pics:
        if p.name in allowed_pics or p.w * p.h < 0.25:  # 登録アセットと小さな装飾アイコンは対象外
            continue
        check = "rasterized-table" if slide.get("table") else "rasterized-chart" if slide.get("chart") else \
            "rasterized-diagram" if slide.get("diagram") else "rasterized-diagram"
        add(check, p.name, "manifest に登録のない画像があります（表・グラフ・図・本文の画像化の疑い）")
    if slide.get("table") and not any(s.graphic == "tbl" for s in shapes):
        add("missing-native-table", "table", "表がネイティブの表オブジェクトになっていません")
    if slide.get("chart") and not any(s.graphic == "chart" for s in shapes):
        add("missing-native-chart", "chart", "グラフがネイティブのグラフオブジェクトになっていません")
    return findings


def check_shape_autofit(sid: str, s: Shape, visible: list[Shape]) -> list[Finding]:
    """spAutoFit の枠が文字量に合わせて伸びたとき、伸びた部分が他の要素やスライド端と衝突しないか。

    PowerPoint は開いた時点で枠の大きさを文字に合わせ直す。保存された枠の大きさだけを見ると見逃す。
      - 縦: 縦位置（anchor）で決まり、上揃えは下へ、下揃えは上へ、中央揃えは上下へ半分ずつ伸びる。
      - 横: 折り返さない枠（wrap="none"）だけ。段落の水平位置で決まり、左揃えは右へ、右揃えは左へ、中央は左右へ伸びる。
    """
    pt = max(s.font_sizes) if s.font_sizes else 18.0
    left_in, _, right_in, _ = s.insets
    # 横: 段落ごとに必要幅と水平位置から左右の伸長量を求め、全段落の最大を合成する（長い段落が右揃えなら左へ伸びる）
    grow_left = grow_right = 0.0
    if not s.wrap:
        for text, align in zip(s.texts, s.aligns or ["l"] * len(s.texts)):
            extra = max(0.0, text_width_in(text, pt) + left_in + right_in - s.w)
            left = {"r": extra, "ctr": extra / 2}.get(align, 0.0)
            grow_left, grow_right = max(grow_left, left), max(grow_right, extra - left)
    grow_h = max(0.0, estimated_text_height(s) - s.h)
    if grow_left + grow_right <= 0.05 and grow_h <= 0.05:
        return []
    up = {"b": grow_h, "ctr": grow_h / 2}.get(s.anchor, 0.0)
    x0, y0, w, h = s.x - grow_left, s.y - up, s.w + grow_left + grow_right, s.h + grow_h
    expanded = Shape(s.name, s.kind, x0, y0, w, h)
    original = Shape(s.name, s.kind, s.x, s.y, s.w, s.h)
    # 伸びた部分だけを見る（元の枠との重なりは text-overlap が担当）
    collides = [o for o in visible if o is not s and expanded.intersection(o) - original.intersection(o) > 0.01]
    outside = x0 < -0.01 or y0 < -0.01 or x0 + w > SLIDE_W + 0.01 or y0 + h > SLIDE_H + 0.01
    if not collides and not outside:
        return []
    where = f"「{collides[0].text[:10] or collides[0].name}」と重なる" if collides else "スライド外に出る"
    return [Finding(sid, "autofit-expansion", s.name,
                    f"図形の自動伸長（spAutoFit）で枠が約 {w:.2f}x{h:.2f}in まで伸び、{where}「{s.text[:16]}」")]


def segment_crosses(seg: Shape, box: Shape, samples: int = 40) -> bool:
    """線分が箱の内部を通るか。端の 0.03in は除く。"""
    ix0, iy0, ix1, iy1 = box.x + 0.03, box.y + 0.03, box.x + box.w - 0.03, box.y + box.h - 0.03
    # 線は外接矩形の対角線。flipH/flipV の一方だけなら右上がり、それ以外は右下がり
    (x1, y1), (x2, y2) = (((seg.x, seg.y + seg.h), (seg.x + seg.w, seg.y)) if seg.flip
                          else ((seg.x, seg.y), (seg.x + seg.w, seg.y + seg.h)))
    return any(ix0 < x1 + (x2 - x1) * t / samples < ix1 and iy0 < y1 + (y2 - y1) * t / samples < iy1
               for t in range(1, samples))


def run_qa(content: dict, outline: dict, pptx: Path, deck_dir: Path) -> dict:
    """QA を実行し、除外適用後の結果を返す。errors が空なら重大 FAIL 0。"""
    exceptions = load_exceptions(deck_dir)
    with zipfile.ZipFile(pptx) as z:
        names = sorted((n for n in z.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
                       key=lambda n: int(re.findall(r"\d+", n)[0]))
        xmls = [z.read(n).decode("utf-8") for n in names]
    findings: list[Finding] = []
    for slide, o_slide, xml in zip(content["slides"], outline["slides"], xmls):
        findings += check_slide(slide["id"], slide, o_slide, parse_shapes(xml))
    excused, active, used = [], [], set()
    for f in findings:
        hit = next((i for i, e in enumerate(exceptions) if e["slide_id"] == f.slide_id and e["check"] == f.check
                    and e["target"] in f.target), None)
        if hit is None:
            active.append(f)
        else:
            used.add(hit)
            excused.append({**f.__dict__, "reason": exceptions[hit]["reason"]})
    # 使われない除外は放置すると本物の不具合を隠すため警告する
    stale = [e for i, e in enumerate(exceptions) if i not in used]
    return {
        "errors": [f.__dict__ for f in active if f.severity == "error"],
        "warnings": [f.__dict__ for f in active if f.severity == "warning"],
        "excused": excused,
        "stale_exceptions": stale,
    }
