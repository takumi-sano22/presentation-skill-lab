"""ネイティブ図の決定論的レイアウトと幾何検査、PPTX 上の関係検査のテスト。"""
from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build  # noqa: E402
import diagram  # noqa: E402

SAMPLE = yaml.safe_load((ROOT / "examples/technical-architecture/content.yaml").read_text(encoding="utf-8"))["slides"][2]["diagram"]


def boxes(result: dict) -> dict[str, diagram.Box]:
    return {n["id"]: diagram.Box(n["x"], n["y"], n["w"], n["h"]) for n in result["nodes"]}


class LayoutTests(unittest.TestCase):
    def test_sample_layout_has_no_overlap_and_no_crossing(self):
        r = diagram.layout(SAMPLE)
        b = boxes(r)
        ids = list(b)
        for i, a in enumerate(ids):
            for c in ids[i + 1:]:
                self.assertFalse(b[a].intersects(b[c]), (a, c))
        self.assertEqual(diagram.count_crossings(r), 0)

    def test_ranks_follow_edge_direction(self):
        ranks = diagram.assign_ranks([n["id"] for n in SAMPLE["nodes"]], SAMPLE["edges"])
        self.assertEqual(ranks, {"user": 0, "agent": 1, "policy": 2, "tool": 3, "db": 4})

    def test_edges_start_and_end_on_node_borders_and_follow_direction(self):
        r = diagram.layout(SAMPLE)
        b = boxes(r)
        for e in r["edges"]:
            start, end = e["points"][0], e["points"][-1]
            self.assertAlmostEqual(start[0], b[e["from"]].x + b[e["from"]].w, places=3)
            self.assertAlmostEqual(end[0], b[e["to"]].x, places=3)

    def test_long_edge_goes_around_intermediate_node(self):
        # agent→tool は2層をまたぐため中継点を通り、policy を貫通しない
        r = diagram.layout(SAMPLE)
        long_edge = next(e for e in r["edges"] if (e["from"], e["to"]) == ("agent", "tool"))
        self.assertEqual(len(long_edge["points"]), 3)

    def test_layout_is_deterministic_and_stable(self):
        a = json.dumps(diagram.layout(SAMPLE), sort_keys=True)
        b = json.dumps(diagram.layout(copy.deepcopy(SAMPLE)), sort_keys=True)
        self.assertEqual(a, b)
        # ラベル文言だけを変えてもノード位置は変わらない（再生成で位置が不安定にならない）
        relabeled = copy.deepcopy(SAMPLE)
        relabeled["edges"][0]["label"] = "問い合わせ"
        pos = lambda r: [(n["id"], n["x"], n["y"]) for n in r["nodes"]]  # noqa: E731
        self.assertEqual(pos(diagram.layout(SAMPLE)), pos(diagram.layout(relabeled)))

    def test_cycle_is_laid_out_without_error(self):
        cyc = {"nodes": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}, {"id": "c", "label": "C"}],
               "edges": [{"from": "a", "to": "b"}, {"from": "b", "to": "c"}, {"from": "c", "to": "a"}]}
        r = diagram.layout(cyc)
        self.assertEqual(len(r["edges"]), 3)
        # 逆向きの辺も、点列は from から to へ向かう
        back = next(e for e in r["edges"] if e["from"] == "c")
        b = boxes(r)
        self.assertAlmostEqual(back["points"][0][0], b["c"].x, places=3)

    def test_groups_contain_only_members(self):
        d = copy.deepcopy(SAMPLE)
        group = {"user": "利用者側", "agent": "制御面", "policy": "制御面", "tool": "データ面", "db": "データ面"}
        for n in d["nodes"]:
            n["group"] = group[n["id"]]
        r = diagram.layout(d)
        b = boxes(r)
        for g in r["groups"]:
            gb = diagram.Box(g["x"], g["y"], g["w"], g["h"])
            for nid, box in b.items():
                self.assertEqual(gb.intersects(box), nid in g["members"], (g["name"], nid))

    def test_parallel_and_bidirectional_edges_do_not_overlap(self):
        d = {"nodes": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
             "edges": [{"from": "a", "to": "b", "label": "要求", "kind": "data"},
                       {"from": "b", "to": "a", "label": "応答", "kind": "data"},
                       {"from": "a", "to": "b", "label": "監視", "kind": "control"}]}
        r = diagram.layout(d)
        paths = [tuple(map(tuple, e["points"])) for e in r["edges"]]
        self.assertEqual(len({frozenset(p) for p in paths}), 3)  # 3本とも異なる経路
        b = boxes(r)
        for e in r["edges"]:  # ずらしても端点はノード境界の範囲内
            for (x, y), nid in ((e["points"][0], e["from"]), (e["points"][-1], e["to"])):
                self.assertTrue(b[nid].y < y < b[nid].y + b[nid].h)

    def test_self_loop_fails_explicitly(self):
        with self.assertRaises(diagram.LayoutError):
            diagram.layout({"nodes": [{"id": "a", "label": "A"}], "edges": [{"from": "a", "to": "a"}]})

    def test_edge_labels_avoid_group_names(self):
        d = copy.deepcopy(SAMPLE)
        group = {"user": "利用者側", "agent": "制御面", "policy": "制御面", "tool": "データ面", "db": "データ面"}
        for n in d["nodes"]:
            n["group"] = group[n["id"]]
        r = diagram.layout(d)
        labels = [diagram.Box(**e["label_box"]) for e in r["edges"] if "label_box" in e]
        for gl in diagram.group_label_boxes(r):
            self.assertFalse(any(gl.intersects(lb) for lb in labels))

    def test_legend_lists_edge_kinds_in_japanese(self):
        r = diagram.layout(SAMPLE)
        self.assertEqual([(i["label"], i["dash"]) for i in r["legend"]], [("データ", "solid"), ("制御", "dash")])

    def test_unreadable_layouts_fail_explicitly(self):
        too_long = copy.deepcopy(SAMPLE)
        too_long["nodes"][0]["label"] = "とても長いノード名" * 4
        with self.assertRaises(diagram.LayoutError):
            diagram.layout(too_long)
        crowded = {"nodes": [{"id": f"n{i}", "label": f"N{i}"} for i in range(12)],
                   "edges": [{"from": "n0", "to": f"n{i}"} for i in range(1, 12)]}
        with self.assertRaises(diagram.LayoutError):
            diagram.layout(crowded)


def fake_diagram_pptx(path: Path, shapes: list[tuple[str, float, float, float, float, str, bool]]) -> Path:
    """名前付き図形だけの擬似 PPTX（name, x, y, w, h, flip 属性, 矢印あり）。単位はインチ。"""
    emu = lambda v: int(round(v * build.EMU_PER_INCH))  # noqa: E731
    body = ""
    for name, x, y, w, h, flip, arrow in shapes:
        tail = '<a:tailEnd type="triangle"/>' if arrow else ""
        body += (f'<p:sp><p:nvSpPr><p:cNvPr id="1" name="{name.replace(">", "&gt;")}"/></p:nvSpPr><p:spPr>'
                 f'<a:xfrm{flip}><a:off x="{emu(x)}" y="{emu(y)}"/><a:ext cx="{emu(w)}" cy="{emu(h)}"/></a:xfrm>'
                 f'<a:ln>{tail}</a:ln></p:spPr></p:sp>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("ppt/slides/slide1.xml", f"<p:sld>{body}</p:sld>")
    return path


class PptxDiagramCheckTests(unittest.TestCase):
    content = {"slides": [{"id": "s1", "diagram": {"nodes": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
                                                   "edges": [{"from": "a", "to": "b"}]}}]}
    outline = {"slides": [{"psl": {"diagram_layout": {"nodes": []}}}]}

    def check(self, shapes):
        with tempfile.TemporaryDirectory() as d:
            return build.check_diagram_in_pptx(self.content, self.outline, fake_diagram_pptx(Path(d) / "x.pptx", shapes))

    def test_correct_relationship_passes(self):
        ok = [("node:a", 1, 1, 1, 0.5, "", False), ("node:b", 3, 1, 1, 0.5, "", False),
              ("edge:0:a->b#0", 2, 1.25, 1, 0, "", True)]
        self.assertEqual(self.check(ok), [])

    def test_wrong_endpoint_and_missing_arrow_are_detected(self):
        ng = [("node:a", 1, 1, 1, 0.5, "", False), ("node:b", 3, 1, 1, 0.5, "", False),
              ("edge:0:a->b#0", 2, 1.25, 0.5, 0, "", False)]  # 終点が b に届かず矢印もない
        errors = self.check(ng)
        self.assertTrue(any("終点" in e and "境界" in e for e in errors))
        self.assertTrue(any("矢印" in e for e in errors))

    def test_reversed_drawing_is_detected(self):
        # flipH で描いた線は始点と終点が入れ替わる（b→a の向きに見える）
        ng = [("node:a", 1, 1, 1, 0.5, "", False), ("node:b", 3, 1, 1, 0.5, "", False),
              ("edge:0:a->b#0", 2, 1.25, 1, 0, ' flipH="1"', True)]
        self.assertTrue(any("始点" in e for e in self.check(ng)))

    def test_missing_parallel_edge_is_detected(self):
        content = {"slides": [{"id": "s1", "diagram": {"nodes": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
                                                       "edges": [{"from": "a", "to": "b"}, {"from": "a", "to": "b"}]}}]}
        shapes = [("node:a", 1, 1, 1, 0.5, "", False), ("node:b", 3, 1, 1, 0.5, "", False),
                  ("edge:0:a->b#0", 2, 1.2, 1, 0, "", True)]  # 2本目が描かれていない
        with tempfile.TemporaryDirectory() as d:
            errors = build.check_diagram_in_pptx(content, self.outline, fake_diagram_pptx(Path(d) / "x.pptx", shapes))
        self.assertEqual(errors, ["s1: 辺 1:a->b の線がありません"])

    def test_unknown_and_missing_shapes_and_overlap_are_detected(self):
        ng = [("node:a", 1, 1, 1, 0.5, "", False), ("node:x", 1.5, 1, 1, 0.5, "", False),
              ("edge:0:a->x#0", 2, 1.25, 1, 0, "", True)]
        errors = self.check(ng)
        self.assertTrue(any("ノード b の図形がありません" in e for e in errors))
        self.assertTrue(any("content に無いノード図形 node:x" in e for e in errors))
        self.assertTrue(any("content に無い辺" in e for e in errors))
        self.assertTrue(any("辺 0:a->b の線がありません" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
