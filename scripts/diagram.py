#!/usr/bin/env python3
"""技術構成図（nodes / edges）の決定論的レイアウトと幾何検査。

LLM がピクセル座標を書かなくてよいよう、構造（ノード ID と接続）だけから配置を計算する。
Sugiyama 方式の簡易版:
  1. 層割り当て: 入力順を保った最長路（閉路は入力順で後ろ向きの辺を逆向きに扱う）
  2. 長い辺に中継点（ダミー）を入れて、各層の並び順を重心法で決める（固定回数・安定ソート）
  3. 左→右に層を並べ、層内は等間隔に配置する
座標の単位はインチ（上流レンダラ・pptxgenjs と同じ）。同じ入力からは常に同じ座標になる。
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass

# 図の描画領域（16:9 = 10 x 5.625 in。見出し帯の下〜フッタの上）
AREA_X, AREA_Y, AREA_W, AREA_H = 0.5, 1.35, 9.0, 3.6
NODE_H = 0.62
NODE_H_WITH_DESC = 0.92
DESC_FONT_PT = 9
GROUP_PAD = 0.12
GROUP_LABEL_H = 0.24
LEGEND_H = 0.28
# 同じノード間の並行辺の間隔と上限（ノード高さの中に収める）
PARALLEL_GAP = 0.16
PARALLEL_MAX = 3
# 辺の種類 → 凡例の和文ラベルと線種（意味の違いを色だけに頼らず線種でも示す。docs/design-rules.md 4）
EDGE_KINDS = {
    "data": ("データ", "solid"),
    "control": ("制御", "dash"),
    "dependency": ("依存", "sysDot"),
    "sync": ("同期", "lgDash"),
    "relationship": ("関連", "sysDash"),
}
NODE_MAX_W = 1.9
NODE_FONT_PT = 11
EDGE_FONT_PT = 9
MIN_GAP_X = 0.62
ORDER_SWEEPS = 8
# 文字幅の見積もり（em）。和文は全角1em、欧文・数字は0.55em
HALF_WIDTH_EM = 0.55


class LayoutError(ValueError):
    """読みやすい配置を作れない（重なり・はみ出し・ラベル衝突など）。黙って崩れた図を出さない。"""


@dataclass(frozen=True)
class Box:
    x: float
    y: float
    w: float
    h: float

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2

    def intersects(self, other: "Box", margin: float = 0.0) -> bool:
        return not (self.x + self.w + margin <= other.x or other.x + other.w + margin <= self.x or
                    self.y + self.h + margin <= other.y or other.y + other.h + margin <= self.y)

    def as_dict(self) -> dict:
        return {k: round(v, 4) for k, v in (("x", self.x), ("y", self.y), ("w", self.w), ("h", self.h))}


def text_width_in(text: str, pt: float) -> float:
    em = sum(HALF_WIDTH_EM if unicodedata.east_asian_width(c) in ("Na", "H") else 1.0 for c in text)
    return em * pt / 72


def topo_order(node_ids: list[str], edges: list[dict]) -> list[str]:
    """入力順を優先した位相順（Kahn 法）。閉路で詰まったら入力順で最初の残りノードから再開する。"""
    remaining = list(node_ids)
    indeg = {n: 0 for n in node_ids}
    for e in edges:
        indeg[e["to"]] += 1
    order: list[str] = []
    while remaining:
        ready = [n for n in remaining if indeg[n] == 0] or remaining[:1]  # 閉路は入力順で切る
        n = ready[0]
        remaining.remove(n)
        order.append(n)
        for e in edges:
            if e["from"] == n and e["to"] in remaining:
                indeg[e["to"]] -= 1
    return order


def assign_ranks(node_ids: list[str], edges: list[dict]) -> dict[str, int]:
    """位相順に沿った最長路で層を決める。位相順で後ろ向きの辺（閉路）は逆向きに扱う。"""
    pos = {n: i for i, n in enumerate(topo_order(node_ids, edges))}
    forward = [(e["from"], e["to"]) if pos[e["from"]] < pos[e["to"]] else (e["to"], e["from"]) for e in edges]
    rank = {n: 0 for n in node_ids}
    for n in sorted(node_ids, key=pos.get):
        for a, b in forward:
            if a == n:
                rank[b] = max(rank[b], rank[a] + 1)
    return rank


def layout(diagram: dict) -> dict:
    nodes = diagram["nodes"]
    edges = diagram.get("edges", [])
    node_ids = [n["id"] for n in nodes]
    if any(e["from"] == e["to"] for e in edges):
        raise LayoutError("自己参照の辺は未対応です")
    group_of = {n["id"]: n.get("group", "") for n in nodes}
    group_names = list(dict.fromkeys(g for g in group_of.values() if g))
    kinds = list(dict.fromkeys(e.get("kind", "data") for e in edges))
    has_desc = any(n.get("description") for n in nodes)
    node_h = NODE_H_WITH_DESC if has_desc else NODE_H
    # 凡例（辺の種類が2つ以上のとき）と区画の見出しの分だけ、配置領域を縮める
    legend = len(kinds) >= 2
    area_y = AREA_Y + (GROUP_LABEL_H if group_names else 0.0)
    area_h = AREA_H - (GROUP_LABEL_H if group_names else 0.0) - (LEGEND_H if legend else 0.0)
    rank = assign_ranks(node_ids, edges)
    n_ranks = max(rank.values()) + 1

    # 長い辺をダミー点で分割する（ダミーは並び順と高さ配置にだけ参加する）
    layers: list[list[str]] = [[] for _ in range(n_ranks)]
    for n in node_ids:
        layers[rank[n]].append(n)
    chains: list[list[str]] = []
    for i, e in enumerate(edges):
        a, b = e["from"], e["to"]
        lo, hi = sorted((rank[a], rank[b]))
        chain = [a if rank[a] <= rank[b] else b]
        for r in range(lo + 1, hi):
            dummy = f"__d{i}_{r}"
            layers[r].append(dummy)
            chain.append(dummy)
        chain.append(b if rank[a] <= rank[b] else a)
        chains.append(chain)

    # 重心法: 隣接層の位置の平均で並べ替える（安定ソートで同値は元の順を保つ）
    neighbors: dict[str, set[str]] = {}
    for chain in chains:
        for u, v in zip(chain, chain[1:]):
            neighbors.setdefault(u, set()).add(v)
            neighbors.setdefault(v, set()).add(u)
    for sweep in range(ORDER_SWEEPS):
        order = range(1, n_ranks) if sweep % 2 == 0 else range(n_ranks - 2, -1, -1)
        for r in order:
            ref = layers[r - 1] if sweep % 2 == 0 else layers[r + 1]
            pos = {v: i / max(1, len(ref) - 1) for i, v in enumerate(ref)}
            def bary(v: str, layer=layers[r]) -> float:
                linked = [pos[u] for u in neighbors.get(v, ()) if u in pos]
                return sum(linked) / len(linked) if linked else layer.index(v) / max(1, len(layer) - 1)
            own = {v: bary(v) for v in layers[r]}
            # 同じ区画のノードは層内で隣接させる（区画の重心で区画どうしを並べ、区画内は各自の重心で並べる）
            members: dict[str, list[float]] = {}
            for v in layers[r]:
                if group_of.get(v):
                    members.setdefault(group_of[v], []).append(own[v])
            def key(v: str) -> tuple[float, float]:
                g = group_of.get(v, "")
                return (sum(members[g]) / len(members[g]), own[v]) if g else (own[v], own[v])
            layers[r] = sorted(layers[r], key=key)

    # 座標: 層は等幅の列、列内は等間隔
    node_w = min(NODE_MAX_W, (AREA_W - MIN_GAP_X * (n_ranks - 1)) / n_ranks)
    gap_x = (AREA_W - node_w * n_ranks) / (n_ranks - 1) if n_ranks > 1 else 0.0
    points: dict[str, tuple[float, float]] = {}
    boxes: dict[str, Box] = {}
    for r, layer in enumerate(layers):
        x = AREA_X + r * (node_w + gap_x)
        slot = area_h / len(layer)
        for i, v in enumerate(layer):
            cy = area_y + slot * (i + 0.5)
            if v.startswith("__d"):
                points[v] = (x + node_w / 2, cy)
            else:
                boxes[v] = Box(x, cy - node_h / 2, node_w, node_h)

    # 同じノード間の複数の辺（双方向を含む）は、重ならないよう上下にずらす
    pair_count: dict[frozenset, int] = {}
    for e in edges:
        pair_count[frozenset((e["from"], e["to"]))] = pair_count.get(frozenset((e["from"], e["to"])), 0) + 1
    if max(pair_count.values(), default=0) > PARALLEL_MAX:
        raise LayoutError(f"同じノード間の辺が {PARALLEL_MAX} 本を超えます")
    pair_seen: dict[frozenset, int] = {}

    # 辺: 始点ノードの右辺中央 → 中継点 → 終点ノードの左辺中央（右→左の辺は逆向きに描く）
    edge_shapes = []
    for i, (e, chain) in enumerate(zip(edges, chains)):
        start, end = boxes[chain[0]], boxes[chain[-1]]
        pair = frozenset((e["from"], e["to"]))
        k = pair_seen.get(pair, 0)
        pair_seen[pair] = k + 1
        dy = (k - (pair_count[pair] - 1) / 2) * PARALLEL_GAP
        path = ([(start.x + start.w, start.cy + dy)] + [(px, py + dy) for px, py in (points[d] for d in chain[1:-1])] +
                [(end.x, end.cy + dy)])
        reversed_ = chain[0] != e["from"]
        if reversed_:
            path = list(reversed(path))
        edge_shapes.append({"index": i, "from": e["from"], "to": e["to"], "kind": e.get("kind", "data"),
                            "label": e.get("label", ""), "points": [[round(x, 4), round(y, 4)] for x, y in path]})

    groups = []
    for g in group_names:
        member_boxes = [boxes[n] for n in node_ids if group_of[n] == g]
        x0 = min(b.x for b in member_boxes) - GROUP_PAD
        y0 = min(b.y for b in member_boxes) - GROUP_PAD - GROUP_LABEL_H
        x1 = max(b.x + b.w for b in member_boxes) + GROUP_PAD
        y1 = max(b.y + b.h for b in member_boxes) + GROUP_PAD
        groups.append({"name": g, "members": [n for n in node_ids if group_of[n] == g],
                       **Box(x0, y0, x1 - x0, y1 - y0).as_dict()})

    legend_items = []
    if legend:
        # 描画領域の右下に、線種の見本と和文ラベルを右から並べる
        x = AREA_X + AREA_W
        y = AREA_Y + AREA_H - LEGEND_H + 0.04
        for k in reversed(kinds):
            label, dash = EDGE_KINDS[k]
            w = 0.45 + text_width_in(label, EDGE_FONT_PT) + 0.1
            x -= w
            legend_items.insert(0, {"kind": k, "label": label, "dash": dash, "x": round(x, 4), "y": round(y, 4),
                                    "w": round(w, 4), "h": round(LEGEND_H - 0.08, 4)})

    result = {
        "version": 1,
        "area": Box(AREA_X, AREA_Y, AREA_W, AREA_H).as_dict(),
        "node_font_pt": NODE_FONT_PT,
        "desc_font_pt": DESC_FONT_PT,
        "edge_font_pt": EDGE_FONT_PT,
        "nodes": [{"id": n["id"], "label": n["label"], "description": n.get("description", ""),
                   "kind": n.get("kind", ""), **boxes[n["id"]].as_dict()} for n in nodes],
        "edges": [dict(e, dash=EDGE_KINDS[e["kind"]][1]) for e in edge_shapes],
        "groups": groups,
        "legend": legend_items,
    }
    place_edge_labels(result, gap_x)
    check_geometry(result)
    return result


def place_edge_labels(result: dict, gap_x: float) -> None:
    """辺ラベルを線分の脇（法線方向）に置く。ノード・他ラベル・線と重ならない候補を優先する。

    候補は「線分上の位置 t × 線の上側/下側」。どの線とも交わらない候補が無ければ、線上（背景で線を隠す）を許す。
    """
    area = Box(**result["area"])
    node_boxes = [Box(n["x"], n["y"], n["w"], n["h"]) for n in result["nodes"]]
    all_segments = [(tuple(p), tuple(q)) for e in result["edges"] for p, q in zip(e["points"], e["points"][1:])]
    placed: list[Box] = []
    label_w = max(0.6, gap_x - 0.08)
    for e in result["edges"]:
        if not e["label"]:
            continue
        lines = max(1, -(-text_width_in(e["label"], EDGE_FONT_PT) // label_w))  # 切り上げ
        w, h = label_w, lines * EDGE_FONT_PT * 1.35 / 72 + 0.04
        segs = list(zip(e["points"], e["points"][1:]))
        (x1, y1), (x2, y2) = max(segs, key=lambda s: (s[1][0] - s[0][0]) ** 2 + (s[1][1] - s[0][1]) ** 2)
        length = max(1e-9, ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5)
        nx, ny = -(y2 - y1) / length, (x2 - x1) / length  # 単位法線
        if ny > 0 or (ny == 0 and nx > 0):
            nx, ny = -nx, -ny  # 先に「上側」（y が小さい側）を試す
        offset = abs(ny) * h / 2 + abs(nx) * w / 2 + 0.03
        candidates = []
        for side in (1, -1, 0):
            for t in (0.5, 0.35, 0.65):
                cx = x1 + (x2 - x1) * t + nx * offset * side
                cy = y1 + (y2 - y1) * t + ny * offset * side
                candidates.append((side == 0, Box(cx - w / 2, cy - h / 2, w, h)))
        chosen = None
        for on_line, box in candidates:
            if not (area.x <= box.x and box.x + box.w <= area.x + area.w and area.y <= box.y and box.y + box.h <= area.y + area.h):
                continue
            if any(box.intersects(b) for b in node_boxes + placed):
                continue
            if not on_line and any(segment_hits_box(p, q, box) for p, q in all_segments):
                continue
            chosen = box
            break
        if chosen is None:
            raise LayoutError(f"辺 {e['from']}->{e['to']} のラベル「{e['label']}」を重ならずに置けません")
        placed.append(chosen)
        e["label_box"] = chosen.as_dict()


def segment_hits_box(p: tuple[float, float], q: tuple[float, float], box: Box, samples: int = 40) -> bool:
    """線分が箱の内部を通るか（端点の接触は除く）。サンプリングで判定する。"""
    inner = Box(box.x + 0.01, box.y + 0.01, box.w - 0.02, box.h - 0.02)
    for i in range(1, samples):
        t = i / samples
        x, y = p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t
        if inner.x < x < inner.x + inner.w and inner.y < y < inner.y + inner.h:
            return True
    return False


def check_geometry(result: dict) -> None:
    """重なり 0・領域内・辺がノードを貫通しない・ラベルがノード幅に収まる、を検査する。"""
    area = Box(**result["area"])
    boxes = {n["id"]: Box(n["x"], n["y"], n["w"], n["h"]) for n in result["nodes"]}
    errors = []
    ids = list(boxes)
    for i, a in enumerate(ids):
        b = boxes[a]
        if b.x < area.x - 1e-6 or b.y < area.y - 1e-6 or b.x + b.w > area.x + area.w + 1e-6 or b.y + b.h > area.y + area.h + 1e-6:
            errors.append(f"ノード {a} が描画領域からはみ出します")
        for other in ids[i + 1:]:
            if b.intersects(boxes[other], margin=0.05):
                errors.append(f"ノード {a} と {other} が重なります")
    for n in result["nodes"]:
        # ラベルは2行・説明は2行までに収まるか（ノード内の左右余白 0.08 in）
        if text_width_in(n["label"], result["node_font_pt"]) > 2 * (n["w"] - 0.16):
            errors.append(f"ノード {n['id']} のラベル「{n['label']}」が箱に収まりません")
        if n["description"] and text_width_in(n["description"], result["desc_font_pt"]) > 2 * (n["w"] - 0.16):
            errors.append(f"ノード {n['id']} の説明「{n['description']}」が箱に収まりません")
    for g in result["groups"]:
        gb = Box(g["x"], g["y"], g["w"], g["h"])
        if gb.y < area.y - 1e-6 or gb.x < area.x - GROUP_PAD - 1e-6 or gb.x + gb.w > area.x + area.w + GROUP_PAD + 1e-6:
            errors.append(f"区画 {g['name']} が描画領域からはみ出します")
        for nid, box in boxes.items():
            if nid not in g["members"] and gb.intersects(box):
                errors.append(f"区画 {g['name']} に区画外のノード {nid} が入ります")
        for other in result["groups"]:
            if other["name"] > g["name"] and gb.intersects(Box(other["x"], other["y"], other["w"], other["h"])):
                errors.append(f"区画 {g['name']} と {other['name']} が重なります")
    occupied = list(boxes.values()) + [Box(**e["label_box"]) for e in result["edges"] if "label_box" in e]
    for item in result["legend"]:
        if any(Box(item["x"], item["y"], item["w"], item["h"]).intersects(b) for b in occupied):
            errors.append(f"凡例「{item['label']}」がノード・ラベルと重なります")
    for e in result["edges"]:
        pts = [tuple(p) for p in e["points"]]
        for p, q in zip(pts, pts[1:]):
            for nid, box in boxes.items():
                if nid not in (e["from"], e["to"]) and segment_hits_box(p, q, box):
                    errors.append(f"辺 {e['from']}->{e['to']} がノード {nid} を貫通します")
    if errors:
        raise LayoutError("; ".join(errors))


def count_crossings(result: dict) -> int:
    """辺どうしの交差数（端点共有は除く）。品質指標として manifest に記録する。"""
    def ccw(a, b, c):
        return (c[1] - a[1]) * (b[0] - a[0]) - (b[1] - a[1]) * (c[0] - a[0])

    segs = []
    for k, e in enumerate(result["edges"]):
        pts = [tuple(p) for p in e["points"]]
        segs += [(k, p, q) for p, q in zip(pts, pts[1:])]
    crossings = 0
    for i, (ka, a1, a2) in enumerate(segs):
        for kb, b1, b2 in segs[i + 1:]:
            if ka == kb or {a1, a2} & {b1, b2}:
                continue
            if ccw(a1, b1, b2) * ccw(a2, b1, b2) < 0 and ccw(a1, a2, b1) * ccw(a1, a2, b2) < 0:
                crossings += 1
    return crossings
