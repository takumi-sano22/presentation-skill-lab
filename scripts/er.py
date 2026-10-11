#!/usr/bin/env python3
"""ER 図（エンティティ・属性・PK/FK・関係・多重度）の決定論的配置と、高密度時の SVG 生成。

ADR-0002: 通常の ER 図はネイティブ図形（エンティティ枠・属性行・関係線・多重度ラベル）で描く。
ネイティブ配置が読みやすさ（最小 9pt）・非重なり・線の貫通なしを満たせない場合だけ、
構造データから SVG を生成して埋め込む（理由と元ソースのハッシュを manifest に残す）。

関係の向き: edge.from は外部キーを持つ側（子）、edge.to は参照される側（親）。
多重度 cardinality.from は from 側の端、cardinality.to は to 側の端に表示する。
座標の単位はインチ。同じ入力からは常に同じ座標・同じ SVG になる。
"""
from __future__ import annotations

import hashlib
import html
from dataclasses import dataclass

import unicodedata

from diagram import AREA_H, AREA_W, AREA_X, AREA_Y, Box, assign_ranks, segment_hits_box
from diagram import text_width_in as base_text_width_in


def text_width_in(text: str, pt: float) -> float:
    """文字幅の見積もり（インチ）。和文と欧文の境目には描画環境（LibreOffice / PowerPoint）が自動で
    約 1/4em の空きを入れるため（「受注ID」→「受注 ID」）、その分と 3% の余裕を足す。"""
    wide = [unicodedata.east_asian_width(c) not in ("Na", "H") for c in text if not c.isspace()]
    boundaries = sum(1 for a, b in zip(wide, wide[1:]) if a != b)
    return (base_text_width_in(text, pt) + boundaries * 0.25 * pt / 72) * 1.03

HEADER_FONT_PT = 11
# 属性行の文字サイズ。読みやすさを保てる範囲で 10pt から 0.5pt 刻みで下げる（最小 9pt = J-1）
ATTR_FONT_STEPS = (10.0, 9.5, 9.0)
CARD_FONT_PT = 9
LABEL_FONT_PT = 9
HEADER_H = 0.32
PAD_X = 0.08
ENTITY_MIN_W = 1.0
ENTITY_MAX_W = 3.0
COL_GAP_MAX = 1.6
# 列間の縦の線分どうしの最小間隔、多重度ラベルの帯がない側の余白、ラベルと縦の線の間隔（インチ）
LANE_PITCH = 0.15
LANE_MARGIN = 0.1
CARD_CLEARANCE = 0.07
ENTITY_GAP_MIN = 0.22
# 辺どうしの交差がこれを超える配置は読みにくいとみなす（再現可能なフォールバック基準の一つ）
MAX_CROSSINGS = 2
CARDINALITIES = ("1", "0..1", "1..N", "0..N")
POLICIES = {"auto", "native_only", "svg"}


class ERLayoutError(ValueError):
    """ネイティブで安全に配置できない。reason と測定値（metrics）を持つ。"""

    def __init__(self, reason: str, metrics: dict | None = None):
        super().__init__(reason)
        self.reason = reason
        self.metrics = metrics or {}


def key_marker(attr: dict) -> str:
    pk, fk = bool(attr.get("pk")), bool(attr.get("fk"))
    return "PK/FK" if pk and fk else "PK" if pk else "FK" if fk else ""


def attribute_text(attr: dict) -> str:
    """属性行の表示文字列（PPTX・SVG・内容検査で共通に使う唯一の定義）。

    例: 「PK 受注ID : INT」「FK 顧客ID : INT NULL可」「備考 : TEXT NOT NULL」
    nullable は明示されたときだけ表示する（PK は NOT NULL が自明なので false は表示しない）。
    """
    marker = key_marker(attr)
    text = (marker + " " if marker else "") + attr["name"]
    if attr.get("type"):
        text += f" : {attr['type']}"
    if attr.get("nullable") is True:
        text += " NULL可"
    elif attr.get("nullable") is False and not attr.get("pk"):
        text += " NOT NULL"
    return text


def edge_fk_attributes(nodes: dict[str, dict], edge: dict) -> list[str]:
    """関係が表す from 側の外部キー属性名。edge.fk があればそれ、無ければ to を参照する FK 属性（複合 FK は複数）。"""
    if edge.get("fk"):
        return list(edge["fk"])
    return [a["name"] for a in nodes[edge["from"]].get("attributes", [])
            if str(a.get("fk", "")).split(".")[0] == edge["to"]]


def entity_rows(node: dict) -> list[dict]:
    """エンティティ枠の中の行。属性があれば属性行、無ければ説明（v0.1 の description）を1行で表示する。"""
    if node.get("attributes"):
        return [{"kind": "attr", "name": a["name"], "text": attribute_text(a), "pk": bool(a.get("pk")),
                 "fk": a.get("fk", "")} for a in node["attributes"]]
    if node.get("description"):
        return [{"kind": "desc", "name": "", "text": node["description"], "pk": False, "fk": ""}]
    return []


def row_h(pt: float) -> float:
    return pt * 1.45 / 72 + 0.05


def entity_size(node: dict, pt: float) -> tuple[float, float]:
    rows = entity_rows(node)
    need = max([text_width_in(node["label"], HEADER_FONT_PT) + 2 * PAD_X + 0.06] +
               [text_width_in(r["text"], pt) + 2 * PAD_X + 0.04 for r in rows])
    h = HEADER_H + len(rows) * row_h(pt) + (0.06 if rows else 0.0)
    return max(ENTITY_MIN_W, need), h


def metrics_of(diagram: dict) -> dict:
    nodes = diagram["nodes"]
    return {"entities": len(nodes), "attribute_rows": sum(len(entity_rows(n)) for n in nodes),
            "relationships": len(diagram.get("edges", []))}


def layout(diagram: dict, area: tuple[float, float, float, float] = (AREA_X, AREA_Y, AREA_W, AREA_H),
           fit: bool = True) -> dict:
    """ネイティブ配置。fit=False は SVG 用（領域に収める制約と交差上限を外し、自然な大きさで配置する）。

    文字サイズを 10→9.5→9pt の順に試し、最初に全条件を満たした配置を返す。満たせなければ ERLayoutError。
    """
    reasons = []
    for pt in ATTR_FONT_STEPS if fit else ATTR_FONT_STEPS[:1]:
        try:
            return _layout(diagram, area, pt, fit)
        except ERLayoutError as exc:
            reasons.append(f"{pt:g}pt: {exc.reason}")
    raise ERLayoutError("; ".join(reasons), metrics_of(diagram))


def _layout(diagram: dict, area: tuple[float, float, float, float], pt: float, fit: bool) -> dict:
    ax, ay, aw, ah = area
    nodes = {n["id"]: n for n in diagram["nodes"]}
    ids = list(nodes)
    edges = diagram.get("edges", [])
    if any(e["from"] == e["to"] for e in edges):
        raise ERLayoutError("自己参照の関係は未対応です")
    sizes = {nid: entity_size(nodes[nid], pt) for nid in ids}
    wide = [nid for nid, (w, _) in sizes.items() if w > ENTITY_MAX_W]
    if wide and fit:
        raise ERLayoutError(f"属性行がエンティティ幅 {ENTITY_MAX_W}in に収まりません（{', '.join(wide)}）")

    # 列: 外部キーを持つ側（from）を左、参照される側（to）を右に並べる
    rank = assign_ranks(ids, edges)
    n_cols = max(rank.values()) + 1
    cols: list[list[str]] = [[n for n in ids if rank[n] == r] for r in range(n_cols)]
    neighbors: dict[str, list[str]] = {n: [] for n in ids}
    for e in edges:
        neighbors[e["from"]].append(e["to"])
        neighbors[e["to"]].append(e["from"])
    # 重心法で列内の順序を決める（固定回数・安定ソート）
    for sweep in range(6):
        order = range(1, n_cols) if sweep % 2 == 0 else range(n_cols - 2, -1, -1)
        for r in order:
            ref = cols[r - 1] if sweep % 2 == 0 else cols[r + 1]
            pos = {v: i for i, v in enumerate(ref)}
            def bary(v: str, col=cols[r]) -> float:
                linked = [pos[u] for u in neighbors[v] if u in pos]
                return sum(linked) / len(linked) if linked else col.index(v)
            cols[r] = sorted(cols[r], key=bary)

    # 経路の計画: 端点の辺（左/右）と、通る列間（gap k = 列 k と k+1 の間）を決める
    #   同じ列: 列の右側（最終列なら左側）の列間を往復する
    #   隣の列: その列間で折れる
    #   2列以上離れる: 出発側の列間で折れ、途中の列はエンティティの無い高さ（通路）を横切り、到着側の列間で折れる
    plans = []
    for i, e in enumerate(edges):
        ra, rb = rank[e["from"]], rank[e["to"]]
        if ra == rb:
            side = "R" if ra < n_cols - 1 or n_cols == 1 else "L"
            plans.append({"sides": (side, side), "gaps": [ra if side == "R" else ra - 1]})
        else:
            lo, hi = sorted((ra, rb))
            gaps = [lo] if hi - lo == 1 else ([lo, hi - 1] if ra < rb else [hi - 1, lo])
            plans.append({"sides": ("R", "L") if ra < rb else ("L", "R"), "gaps": gaps})

    # 列間の幅: 両側にエンティティの側面に沿った「多重度ラベルの帯」を取り、縦の線分（レーン）はその内側だけを通す。
    # 帯の幅はその側に付く多重度ラベルの最大幅で決める（列間ごと・左右別）
    lane_count: dict[int, int] = {}
    zones: dict[tuple[int, str], float] = {}
    for i, (e, plan) in enumerate(zip(edges, plans)):
        for g in plan["gaps"]:
            lane_count[g] = lane_count.get(g, 0) + 1
        card = e.get("cardinality") or {}
        for end, side in zip(("from", "to"), plan["sides"]):
            col = rank[e[end]]
            key = (col, "l") if side == "R" else (col - 1, "r")  # 列の右側 = 列間 col の左帯
            w = text_width_in(card[end], CARD_FONT_PT) + 0.06 + CARD_CLEARANCE if card.get(end) else 0.0
            zones[key] = max(zones.get(key, LANE_MARGIN), w)
    n_gaps = max(n_cols - 1, 1 if lane_count else 0)
    zone_l = [zones.get((g, "l"), LANE_MARGIN) for g in range(n_gaps)]
    zone_r = [zones.get((g, "r"), LANE_MARGIN) for g in range(n_gaps)]
    need = [zone_l[g] + zone_r[g] + LANE_PITCH * (lane_count.get(g, 0) + 1) for g in range(n_gaps)]
    # 関係名は列間の縦の線の脇か横の線の上に置くため、2行に折り返した幅が列間に入るようにする
    for e, plan in zip(edges, plans):
        if e.get("label"):
            lw = min(w for w, _ in label_sizes(e["label"]))
            for g in plan["gaps"]:
                need[g] = max(need[g], zone_l[g] + zone_r[g] + lw + 0.1)
    col_w = [max(sizes[n][0] for n in col) for col in cols]
    total_w = sum(col_w)
    if fit and n_gaps:
        # 余った幅は列間へ均等に配る（列間 1 つあたり COL_GAP_MAX までは広げる）
        spare = max(0.0, (aw - total_w - sum(need)) / n_gaps)
        gaps = [n + min(spare, max(0.0, COL_GAP_MAX - n)) for n in need]
    else:
        gaps = [max(COL_GAP_MAX, n) for n in need]
    width = total_w + sum(gaps)
    if fit and width > aw + 1e-6:
        raise ERLayoutError(f"横幅が不足します（必要 {width:.2f}in > {aw:.2f}in）")
    heights = []
    for col in cols:
        hs = [sizes[n][1] for n in col]
        heights.append(sum(hs) + (ENTITY_GAP_MIN if fit else 0.6) * (len(hs) - 1))
    if fit and max(heights) > ah + 1e-6:
        raise ERLayoutError(f"縦に収まりません（必要 {max(heights):.2f}in > {ah:.2f}in）")
    area_h = ah if fit else max(heights)
    x = ax + ((aw - width) / 2 if fit else 0.0)
    boxes: dict[str, Box] = {}
    col_x = []
    for r, col in enumerate(cols):
        hs = [sizes[n][1] for n in col]
        spare = (area_h - sum(hs)) / (len(col) + 1) if fit else 0.6
        y = ay + spare
        for n in col:
            w, h = sizes[n]
            boxes[n] = Box(x + (col_w[r] - w) / 2, y, w, h)
            y += h + spare
        col_x.append((x, x + col_w[r]))
        x += col_w[r] + (gaps[r] if r < len(gaps) else 0.0)

    entities = []
    row_center: dict[tuple[str, str], float] = {}
    for nid in ids:
        b = boxes[nid]
        rows = []
        y = b.y + HEADER_H + 0.03
        for r in entity_rows(nodes[nid]):
            rows.append({**r, **Box(b.x, y, b.w, row_h(pt)).as_dict()})
            if r["name"]:
                row_center[(nid, r["name"])] = y + row_h(pt) / 2
            y += row_h(pt)
        entities.append({"id": nid, "label": nodes[nid]["label"], "header_h": HEADER_H, "rows": rows, **b.as_dict()})

    # 関係線: 子の FK 行 → 親の参照先（無ければ最初の PK 行、無ければ枠の中央）を直交の折れ線で結ぶ。
    # 同じ列間の線は縦の線分が重ならないよう、列間の位置をずらす
    def attach_y(e: dict, end: str) -> float:
        nid = e[end]
        fk_names = edge_fk_attributes(nodes, e)
        if end == "from":
            if fk_names:
                return row_center[(nid, fk_names[0])]
        else:
            src = next((a for a in nodes[e["from"]].get("attributes", []) if fk_names and a["name"] == fk_names[0]), None)
            target = src["fk"].split(".", 1)[1] if src else None
            if target and (nid, target) in row_center:
                return row_center[(nid, target)]
            pk = next((a for a in nodes[nid].get("attributes", []) if a.get("pk")), None)
            if pk:
                return row_center[(nid, pk["name"])]
        return boxes[nid].cy

    # 同じエンティティの同じ辺に集まる端点は最小間隔で上下に振り分ける
    # （複数の子が同じ親の主キー行を参照すると、線と多重度ラベルが重なるため）
    ends: dict[tuple[str, str], list[tuple[float, int, str]]] = {}
    for i, e in enumerate(edges):
        sa, sb = plans[i]["sides"]
        ends.setdefault((e["from"], sa), []).append((attach_y(e, "from"), i, "from"))
        ends.setdefault((e["to"], sb), []).append((attach_y(e, "to"), i, "to"))
    attach: dict[tuple[int, str], float] = {}
    sep = 0.24
    for (nid, _), items in ends.items():
        box = boxes[nid]
        lo, hi = box.y + HEADER_H / 2, box.y + box.h - 0.06
        items.sort()
        ys = [y for y, _, _ in items]
        for k in range(1, len(ys)):
            ys[k] = max(ys[k], ys[k - 1] + sep)
        # 下端を超えたら全体を上へ寄せる。それでも収まらなければ間隔を詰める
        if ys and ys[-1] > hi:
            shift = ys[-1] - hi
            ys = [y - shift for y in ys]
        if ys and ys[0] < lo:
            ys = [lo + (hi - lo) * (k + 0.5) / len(ys) for k in range(len(ys))] if len(ys) > 1 else [lo]
        for y, (_, i, end) in zip(ys, items):
            attach[(i, end)] = y

    # 2列以上離れる関係の通路の高さ: 途中の列のエンティティを避け、両端の高さの中間に近いところ
    top = ay if fit else min(b.y for b in boxes.values()) - 0.5
    bottom = ay + area_h if fit else max(b.y + b.h for b in boxes.values()) + 0.5
    used_channels: list[tuple[int, int, float]] = []
    channel: dict[int, float] = {}
    for i, e in enumerate(edges):
        if len(plans[i]["gaps"]) < 2:
            continue
        lo_c, hi_c = sorted((rank[e["from"]], rank[e["to"]]))
        blocked = [(boxes[n].y - 0.1, boxes[n].y + boxes[n].h + 0.1) for c in range(lo_c + 1, hi_c) for n in cols[c]]
        blocked += [(y - 0.14, y + 0.14) for a, b, y in used_channels if a < hi_c and lo_c < b]
        want = (attach[(i, "from")] + attach[(i, "to")]) / 2
        free, cursor = [], top + 0.05
        for b0, b1 in sorted(blocked):
            if b0 > cursor:
                free.append((cursor, b0))
            cursor = max(cursor, b1)
        if cursor < bottom - 0.05:
            free.append((cursor, bottom - 0.05))
        if not free:
            raise ERLayoutError(f"関係 {e['from']}->{e['to']} が途中の列を通る通路がありません")
        y = min((min(max(want, f0), f1) for f0, f1 in free), key=lambda v: abs(v - want))
        channel[i] = y
        used_channels.append((lo_c, hi_c, y))

    # 列間ごとに縦の線分の位置（レーン）を割り当てる。縦の線分が重ならないよう等間隔にずらす
    lanes: dict[int, list[tuple[int, int]]] = {}
    for i in range(len(edges)):
        for slot, g in enumerate(plans[i]["gaps"]):
            lanes.setdefault(g, []).append((i, slot))

    def lane_x(i: int, slot: int) -> float:
        g = plans[i]["gaps"][slot]
        members = lanes[g]
        inner = gaps[g] - zone_l[g] - zone_r[g]
        return col_x[g][1] + zone_l[g] + inner * (members.index((i, slot)) + 1) / (len(members) + 1)

    edge_out = []
    for i, e in enumerate(edges):
        a, b = boxes[e["from"]], boxes[e["to"]]
        sa, sb = plans[i]["sides"]
        ya, yb = attach[(i, "from")], attach[(i, "to")]
        xa = a.x + a.w if sa == "R" else a.x
        xb = b.x + b.w if sb == "R" else b.x
        if i in channel:
            m1, m2, yc = lane_x(i, 0), lane_x(i, 1), channel[i]
            pts = [(xa, ya), (m1, ya), (m1, yc), (m2, yc), (m2, yb), (xb, yb)]
        else:
            mx = lane_x(i, 0)
            pts = [(xa, ya), (mx, ya), (mx, yb), (xb, yb)]
        # 長さ 0 の線分（同じ高さ）を除く
        clean = [pts[0]]
        for p in pts[1:]:
            if abs(p[0] - clean[-1][0]) > 1e-6 or abs(p[1] - clean[-1][1]) > 1e-6:
                clean.append(p)
        card = e.get("cardinality") or {}
        edge_out.append({"index": i, "id": e.get("id", ""), "from": e["from"], "to": e["to"], "label": e.get("label", ""),
                         "kind": e.get("kind", "relationship"), "cardinality": {k: card[k] for k in ("from", "to") if card.get(k)},
                         "points": [[round(px, 4), round(py, 4)] for px, py in clean]})

    result = {"version": 1, "kind": "er", "area": Box(*area).as_dict() if fit else None,
              "header_font_pt": HEADER_FONT_PT, "attr_font_pt": pt, "card_font_pt": CARD_FONT_PT,
              "label_font_pt": LABEL_FONT_PT, "entities": entities, "edges": edge_out}
    place_labels(result, fit)
    check(result, fit)
    result["metrics"] = {**metrics_of(diagram), "attr_font_pt": pt, "crossings": count_crossings(result),
                         "width_in": round(width, 3), "height_in": round(max(heights), 3)}
    if fit and result["metrics"]["crossings"] > MAX_CROSSINGS:
        raise ERLayoutError(f"関係線の交差が {result['metrics']['crossings']} 箇所（上限 {MAX_CROSSINGS}）")
    return result


def entity_boxes(result: dict) -> dict[str, Box]:
    return {en["id"]: Box(en["x"], en["y"], en["w"], en["h"]) for en in result["entities"]}


def segments(result: dict) -> list[tuple[int, tuple[float, float], tuple[float, float]]]:
    return [(e["index"], tuple(p), tuple(q)) for e in result["edges"] for p, q in zip(e["points"], e["points"][1:])]


def place_labels(result: dict, fit: bool) -> None:
    """多重度ラベルを線の両端（エンティティの外側・線の上）に、関係名を最長の線分の脇に置く。"""
    boxes = list(entity_boxes(result).values())
    segs = segments(result)
    placed: list[Box] = []
    area = Box(**result["area"]) if fit else None

    def free(box: Box, own: int, allow_own_line: bool) -> bool:
        if area and not (area.x - 1e-6 <= box.x and box.x + box.w <= area.x + area.w + 1e-6 and
                         area.y - 1e-6 <= box.y and box.y + box.h <= area.y + area.h + 1e-6):
            return False
        if any(box.intersects(b) for b in boxes + placed):
            return False
        return not any(segment_hits_box(p, q, box) for k, p, q in segs if not (allow_own_line and k == own))

    h_card = CARD_FONT_PT * 1.3 / 72 + 0.02
    for e in result["edges"]:
        e["card_boxes"] = {}
        pts = e["points"]
        for end, (p, q) in (("from", (pts[0], pts[1])), ("to", (pts[-1], pts[-2]))):
            text = e["cardinality"].get(end)
            if not text:
                continue
            w = text_width_in(text, CARD_FONT_PT) + 0.06
            direction = 1 if q[0] > p[0] else -1
            reach = abs(q[0] - p[0])
            # 端に近い順に、線の上・下の候補を試す（線分の長さの範囲内）
            cands = [(p[0] + direction * dx if direction > 0 else p[0] - dx - w, y0)
                     for dx in (0.04, 0.2, 0.36) if dx + w <= max(reach, 0.04 + w)
                     for y0 in (p[1] - h_card - 0.02, p[1] + 0.02)]
            for x0, y0 in cands:
                box = Box(x0, y0, w, h_card)
                if free(box, e["index"], False):
                    break
            else:
                raise ERLayoutError(f"関係 {e['from']}->{e['to']} の多重度「{text}」を重ならずに置けません")
            placed.append(box)
            e["card_boxes"][end] = {"text": text, **box.as_dict()}
    for e in result["edges"]:
        if not e["label"]:
            continue
        pts = e["points"]
        segs_e = sorted(zip(pts, pts[1:]), key=lambda s: -(abs(s[1][0] - s[0][0]) + abs(s[1][1] - s[0][1])))
        chosen = None
        # 1行で置けなければ2行に折り返す（文字は縮めない）。長い線分から順に、線分上の位置 t を中央→端の順で試す
        positions = [(size, p, q, t) for size in label_sizes(e["label"])
                     for p, q in segs_e for t in (0.5, 0.3, 0.7, 0.15, 0.85)]
        for (w, h), p, q, t in positions:
            cx, cy = p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t
            vertical = abs(q[0] - p[0]) < 1e-6
            cands = ([(cx + 0.04, cy - h / 2), (cx - 0.04 - w, cy - h / 2)] if vertical else
                     [(cx - w / 2, cy - h - 0.03), (cx - w / 2, cy + 0.03)])
            # 脇に置けなければ線上（背景で線を隠す）を許す
            for on_line, (x0, y0) in [(False, c) for c in cands] + [(True, (cx - w / 2, cy - h / 2))]:
                box = Box(x0, y0, w, h)
                if free(box, e["index"], on_line):
                    chosen = box
                    break
            if chosen:
                break
        if chosen is None:
            raise ERLayoutError(f"関係 {e['from']}->{e['to']} の名前「{e['label']}」を重ならずに置けません")
        placed.append(chosen)
        e["label_box"] = chosen.as_dict()


def label_sizes(label: str) -> list[tuple[float, float]]:
    """関係名の枠の候補（1行、2行折返し）。幅・高さはインチ。"""
    one = text_width_in(label, LABEL_FONT_PT)
    line_h = LABEL_FONT_PT * 1.3 / 72
    sizes = [(one + 0.08, line_h + 0.04)]
    if len(label) >= 4:
        sizes.append((one / 2 + LABEL_FONT_PT / 72 + 0.08, 2 * line_h + 0.04))
    return sizes


def check(result: dict, fit: bool) -> None:
    """重なり 0・領域内・線がエンティティを貫通しない・線分の重複なし、を検査する。"""
    boxes = entity_boxes(result)
    errors = []
    ids = list(boxes)
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            if boxes[a].intersects(boxes[b], margin=0.05):
                errors.append(f"エンティティ {a} と {b} が重なります")
        if fit:
            area = Box(**result["area"])
            bx = boxes[a]
            if bx.x < area.x - 1e-6 or bx.y < area.y - 1e-6 or bx.x + bx.w > area.x + area.w + 1e-6 or \
                    bx.y + bx.h > area.y + area.h + 1e-6:
                errors.append(f"エンティティ {a} が描画領域からはみ出します")
    for e in result["edges"]:
        for p, q in zip(e["points"], e["points"][1:]):
            for nid, box in boxes.items():
                if segment_hits_box(tuple(p), tuple(q), box):
                    errors.append(f"関係 {e['from']}->{e['to']} の線がエンティティ {nid} を貫通します")
    # 別の関係の線分が同じ直線上で重なると、どの線がどこへ行くか読めない
    segs = segments(result)
    for i, (ka, a1, a2) in enumerate(segs):
        for kb, b1, b2 in segs[i + 1:]:
            if ka != kb and collinear_overlap(a1, a2, b1, b2):
                errors.append(f"関係の線が重なります（辺 {ka} と {kb}）")
    if errors:
        raise ERLayoutError("; ".join(dict.fromkeys(errors)))


def collinear_overlap(a1, a2, b1, b2, tol: float = 0.02) -> bool:
    if abs(a1[0] - a2[0]) < 1e-6 and abs(b1[0] - b2[0]) < 1e-6 and abs(a1[0] - b1[0]) < tol:
        lo, hi = max(min(a1[1], a2[1]), min(b1[1], b2[1])), min(max(a1[1], a2[1]), max(b1[1], b2[1]))
        return hi - lo > tol
    if abs(a1[1] - a2[1]) < 1e-6 and abs(b1[1] - b2[1]) < 1e-6 and abs(a1[1] - b1[1]) < tol:
        lo, hi = max(min(a1[0], a2[0]), min(b1[0], b2[0])), min(max(a1[0], a2[0]), max(b1[0], b2[0]))
        return hi - lo > tol
    return False


def count_crossings(result: dict) -> int:
    def ccw(a, b, c):
        return (c[1] - a[1]) * (b[0] - a[0]) - (b[1] - a[1]) * (c[0] - a[0])
    segs = segments(result)
    n = 0
    for i, (ka, a1, a2) in enumerate(segs):
        for kb, b1, b2 in segs[i + 1:]:
            if ka == kb or {a1, a2} & {b1, b2}:
                continue
            if ccw(a1, b1, b2) * ccw(a2, b1, b2) < 0 and ccw(a1, a2, b1) * ccw(a1, a2, b2) < 0:
                n += 1
    return n


# ---------------------------------------------------------------------------
# SVG フォールバック（高密度の例外）
# ---------------------------------------------------------------------------

SVG_FONT = "Noto Sans JP, Noto Sans CJK JP, sans-serif"
PX = 96  # 1in あたりの SVG 座標


def to_svg(diagram: dict, colors: dict) -> tuple[str, dict]:
    """構造データから SVG を生成する（図の唯一の正本は content.yaml。SVG は再生成可能な派生物）。

    戻り値は（SVG 文字列, 自然な大きさの配置結果）。各要素に data-* 属性で ID を残し、出自を検査できるようにする。
    """
    lay = layout(diagram, area=(0.1, 0.1, 0.0, 0.0), fit=False)
    w = max(en["x"] + en["w"] for en in lay["entities"]) + 0.3
    h = max(en["y"] + en["h"] for en in lay["entities"]) + 0.2
    for e in lay["edges"]:
        for b in list(e.get("card_boxes", {}).values()) + ([e["label_box"]] if e.get("label_box") else []):
            w, h = max(w, b["x"] + b["w"] + 0.1), max(h, b["y"] + b["h"] + 0.1)
    fg, bg, accent, muted = (colors["foreground"], colors["background"], colors["accent"],
                             colors.get("muted", colors["foreground"]))
    esc = lambda s: html.escape(str(s), quote=True)  # noqa: E731
    px = lambda v: f"{v * PX:.2f}"  # noqa: E731
    pt = lambda p: f"{p * PX / 72:.2f}"  # noqa: E731
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{px(w)}" height="{px(h)}" viewBox="0 0 {px(w)} {px(h)}" '
           f'font-family="{esc(SVG_FONT)}" data-generator="presentation-skill-lab/er.py">',
           f'<rect x="0" y="0" width="{px(w)}" height="{px(h)}" fill="{esc(bg)}"/>']
    for e in lay["edges"]:
        d = " ".join(("M" if i == 0 else "L") + f"{px(x)},{px(y)}" for i, (x, y) in enumerate(e["points"]))
        out.append(f'<g data-edge="{e["index"]}" data-from="{esc(e["from"])}" data-to="{esc(e["to"])}" '
                   f'data-id="{esc(e["id"])}"><path d="{d}" fill="none" stroke="{esc(muted)}" stroke-width="1.5"/>')
        for end, b in e.get("card_boxes", {}).items():
            out.append(f'<text data-card="{end}" x="{px(b["x"] + 0.03)}" y="{px(b["y"] + b["h"] - 0.04)}" '
                       f'font-size="{pt(CARD_FONT_PT)}" fill="{esc(fg)}">{esc(b["text"])}</text>')
        if e.get("label_box"):
            b = e["label_box"]
            out.append(f'<rect x="{px(b["x"])}" y="{px(b["y"])}" width="{px(b["w"])}" height="{px(b["h"])}" fill="{esc(bg)}"/>'
                       f'<text data-label="1" x="{px(b["x"] + 0.04)}" y="{px(b["y"] + b["h"] - 0.05)}" '
                       f'font-size="{pt(LABEL_FONT_PT)}" fill="{esc(fg)}">{esc(e["label"])}</text>')
        out.append("</g>")
    for en in lay["entities"]:
        out.append(f'<g data-entity="{esc(en["id"])}">'
                   f'<rect x="{px(en["x"])}" y="{px(en["y"])}" width="{px(en["w"])}" height="{px(en["h"])}" '
                   f'fill="{esc(bg)}" stroke="{esc(accent)}" stroke-width="1.5"/>'
                   f'<rect x="{px(en["x"])}" y="{px(en["y"])}" width="{px(en["w"])}" height="{px(en["header_h"])}" fill="{esc(accent)}"/>'
                   f'<text data-header="1" x="{px(en["x"] + PAD_X)}" y="{px(en["y"] + en["header_h"] - 0.09)}" '
                   f'font-size="{pt(HEADER_FONT_PT)}" font-weight="bold" fill="#FFFFFF">{esc(en["label"])}</text>')
        for r in en["rows"]:
            weight = ' font-weight="bold"' if r["pk"] else ""
            out.append(f'<text data-row="{esc(r["name"])}" x="{px(r["x"] + PAD_X)}" y="{px(r["y"] + r["h"] - 0.07)}" '
                       f'font-size="{pt(lay["attr_font_pt"])}"{weight} fill="{esc(fg)}">{esc(r["text"])}</text>')
        out.append("</g>")
    out.append("</svg>")
    lay["size_in"] = {"w": round(w, 4), "h": round(h, 4)}
    return "\n".join(out) + "\n", lay


def svg_texts(svg: str) -> list[str]:
    """SVG の text 要素の文字列（内容検査用）。"""
    import re
    return [html.unescape(t) for t in re.findall(r"<text\b[^>]*>([^<]*)</text>", svg)]


def svg_edges(svg: str) -> list[tuple[str, str]]:
    import re
    return [(html.unescape(a), html.unescape(b)) for a, b in re.findall(r'<g data-edge="\d+" data-from="([^"]*)" data-to="([^"]*)"', svg)]


def expected_texts(diagram: dict) -> list[str]:
    """ER 図に現れるべき文字列（エンティティ名・属性行・関係名・多重度）。PPTX・SVG の検査で共通に使う。"""
    texts = []
    for n in diagram["nodes"]:
        texts.append(n["label"])
        texts += [r["text"] for r in entity_rows(n)]
    for e in diagram.get("edges", []):
        if e.get("label"):
            texts.append(e["label"])
        texts += [e["cardinality"][k] for k in ("from", "to") if e.get("cardinality", {}).get(k)]
    return texts


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
