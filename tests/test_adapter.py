"""adapter（content/design → outline.json）の変換・内容保持・決定性テスト。"""
from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import adapter  # noqa: E402

CONTENT = ROOT / "examples/technical-architecture/content.yaml"
DESIGN = ROOT / "examples/technical-architecture/design.yaml"
OUTLINE_SCHEMA = json.loads((ROOT / "schemas/outline-adapter.schema.json").read_text(encoding="utf-8"))


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.content, self.design = adapter.load_and_validate(CONTENT, DESIGN)

    def convert(self, mutate=None):
        c, d = copy.deepcopy(self.content), copy.deepcopy(self.design)
        if mutate:
            mutate(c, d)
        return adapter.convert(c, d)

    def test_sample_six_slides_convert(self):
        outline = self.convert()
        self.assertEqual(len(outline["slides"]), 6)
        Draft202012Validator(OUTLINE_SCHEMA).validate(outline)
        self.assertEqual(outline["psl"]["deck_id"], "sample-cloud-architecture")
        self.assertEqual(outline["psl"]["content_sha256"], adapter.content_hash(self.content))

    def test_order_and_stable_ids_preserved(self):
        outline = self.convert()
        self.assertEqual([s["psl"]["slide_id"] for s in outline["slides"]], [s["id"] for s in self.content["slides"]])

    def test_semantic_items_roundtrip_without_loss(self):
        outline = self.convert()
        before = adapter.semantic_items(self.content)
        self.assertEqual(before, adapter.outline_semantic_items(outline))
        kinds = {k.split("[")[0] for _, k, _ in before}
        # サンプルが検査対象の種別を網羅していること（タイトル/本文/数値/単位/表セル/図/出典/注記）
        for kind in ("title", "takeaway", "body", "table.header", "table.cell", "chart.value",
                     "chart.unit", "chart.category", "diagram.node", "diagram.edge", "source_ref", "notes"):
            self.assertIn(kind, kinds)

    def test_values_stay_numeric(self):
        chart = next(s for s in self.convert()["slides"] if s["variant"] == "chart")["chart"]
        self.assertEqual(chart["series"][0]["values"], [20, 28, 36])
        self.assertEqual(chart["options"]["valAxisTitle"], "単位: 件")

    def test_table_cells_and_note_visible(self):
        s004 = self.convert()["slides"][3]
        self.assertEqual(s004["table"]["rows"][2], ["故障時の既定動作", "拒否", "実装次第"])
        self.assertEqual(s004["footer"], self.content["slides"][3]["notes"])

    def test_diagram_fallback_keeps_all_labels(self):
        s003 = self.convert()["slides"][2]
        self.assertEqual(s003["psl"]["fallback"], "diagram-as-text")
        self.assertIn("利用者 → オーケストレータ（質問）", s003["bullets"])
        self.assertIn("Query Tool → 分析DB（架空）（フィルタ付き取得）", s003["bullets"])

    def test_diagram_attributes_are_kept(self):
        def enrich(c, _):
            node = c["slides"][2]["diagram"]["nodes"][1]
            node["group"] = "制御"
            node["description"] = "共通ポリシーで判定"
        outline = self.convert(enrich)
        self.assertIn("統合認可［制御］：共通ポリシーで判定", outline["slides"][2]["bullets"])
        items = adapter.outline_semantic_items(outline)
        self.assertIn(("s003", "diagram.node.kind", "policy:policy"), items)
        self.assertIn(("s003", "diagram.edge", "user->agent:質問:data"), items)
        # メタデータ側の属性を消すと往復検査で検出される
        outline = self.convert()
        del outline["slides"][2]["psl"]["diagram"]["nodes"][1]["kind"]
        with self.assertRaises(adapter.ContentMismatch):
            adapter.verify_roundtrip(self.content, outline)

    def test_asset_path_is_relative_to_outline(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d) / "deck"
            (base / "assets").mkdir(parents=True)
            (base / "assets/fig.png").write_bytes(b"x")
            c = copy.deepcopy(self.content)
            c["slides"].append({"id": "s007", "type": "illustration", "title": "図", "takeaway": "", "asset_ref": "assets/fig.png"})
            out_dir = Path(d) / "build/out"
            outline = adapter.convert(c, self.design, base, out_dir)
            image = outline["slides"][-1]["assets"]["image"]
            self.assertEqual((out_dir / image).resolve(), (base / "assets/fig.png").resolve())

    def test_tampered_outline_fails(self):
        cases = {
            "表セル改変": lambda o: o["slides"][3]["table"]["rows"][0].__setitem__(1, "不可"),
            "数値改変": lambda o: o["slides"][4]["chart"]["series"][0]["values"].__setitem__(0, 21),
            "本文欠落": lambda o: o["slides"][1]["bullets"].pop(),
            "出典欠落": lambda o: o["slides"][4].pop("sources"),
            "順序入替": lambda o: o["slides"].reverse(),
            "audience欠落": lambda o: o["psl"]["metadata"].pop("audience"),
            "objective改変": lambda o: o["psl"]["metadata"].__setitem__("objective", "別の目的"),
            "デッキタイトル改変": lambda o: o.__setitem__("title", "別タイトル"),
            "単位表示改変": lambda o: o["slides"][4]["chart"]["options"].__setitem__("valAxisTitle", "単位: 個"),
            "注記表示欠落": lambda o: o["slides"][3].pop("footer"),
        }
        for name, tamper in cases.items():
            with self.subTest(name):
                outline = self.convert()
                tamper(outline)
                with self.assertRaises(adapter.ContentMismatch):
                    adapter.verify_roundtrip(self.content, outline)

    def test_design_changes_do_not_change_content(self):
        def restyle(_, d):
            d["theme"]["name"] = "technical-dark"
            d["theme"]["colors"]["accent"] = "#FF0000"
            d["overrides"]["s004"] = {"layout": "table", "density": "dense"}
        a, b = self.convert(), self.convert(restyle)
        self.assertEqual(adapter.outline_semantic_items(a), adapter.outline_semantic_items(b))
        self.assertNotEqual(a["deck_style"], b["deck_style"])

    def test_unsupported_fails_explicitly(self):
        cases = {
            "図のsvgモード": lambda c, d: d["overrides"]["s003"].__setitem__("diagram_mode", "svg"),
            "表をグラフlayoutで": lambda c, d: d["overrides"].__setitem__("s004", {"layout": "chart"}),
            "表紙に出典": lambda c, d: c["slides"][0].__setitem__("source_refs", ["x"]),
            "未知のschema": lambda c, d: c.__setitem__("schema_version", "9.9"),
            "asset_fit": lambda c, d: d["overrides"]["s003"].__setitem__("asset_fit", "cover"),
            "override notes": lambda c, d: d["overrides"]["s003"].__setitem__("notes", "メモ"),
            "中扉に本文": lambda c, d: c["slides"][5].update(type="section"),
            "グラフに本文": lambda c, d: c["slides"][4].__setitem__("body", ["補足"]),
            "表なしでtable layout": lambda c, d: d["overrides"].__setitem__("s002", {"layout": "table"}),
            "グラフなしでchart layout": lambda c, d: d["overrides"].__setitem__("s002", {"layout": "chart"}),
            "画像なしでillustration": lambda c, d: d["overrides"].__setitem__("s002", {"layout": "illustration"}),
            "図を表layoutで": lambda c, d: c["slides"][3].__setitem__("diagram", c["slides"][2]["diagram"]),
            "図なしでdiagram_mode": lambda c, d: d["overrides"].__setitem__("s002", {"layout": "claim", "diagram_mode": "native"}),
            "円グラフ": lambda c, d: c["slides"][4]["chart"].__setitem__("type", "pie"),
            "NaN値": lambda c, d: c["slides"][4]["chart"]["series"][0]["values"].__setitem__(0, float("nan")),
            "無限大値": lambda c, d: c["slides"][4]["chart"]["series"][0]["values"].__setitem__(1, float("inf")),
        }
        for name, mutate in cases.items():
            with self.subTest(name):
                with self.assertRaises(adapter.UnsupportedContent):
                    self.convert(mutate)

    def test_table_unit_period_caption(self):
        def add_unit(c, _):
            c["slides"][3]["table"]["unit"] = "件"
            c["slides"][3]["table"]["period"] = "2026年"
        s004 = self.convert(add_unit)["slides"][3]
        self.assertEqual(s004["table"]["caption"], "単位: 件 / 期間: 2026年")

    def test_table_body_becomes_visible_footnotes(self):
        def add_body(c, _):
            c["slides"][3]["body"] = ["比較は概念上のもの"]
        outline = self.convert(add_body)
        Draft202012Validator(OUTLINE_SCHEMA).validate(outline)
        s004 = outline["slides"][3]
        self.assertEqual(s004["table"]["footnotes"], ["比較は概念上のもの"])
        self.assertNotIn("bullets", s004)

    def test_unapplied_design_is_explicit(self):
        unapplied = self.convert()["psl"]["unapplied_design"]
        self.assertIn("theme.fonts", unapplied)
        self.assertIn("overrides.s001.density", unapplied)

    def test_number_format_is_stable(self):
        self.assertEqual(adapter.format_number(20), adapter.format_number(20.0))
        self.assertEqual(adapter.format_number(0.1), "0.1")

    def test_cli_output_hash_is_stable(self):
        with tempfile.TemporaryDirectory() as d:
            outs = []
            for i in range(2):
                out = Path(d) / f"outline{i}.json"
                r = subprocess.run([sys.executable, str(ROOT / "scripts/adapter.py"), "--content", str(CONTENT),
                                    "--design", str(DESIGN), "--output", str(out)], capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stderr)
                outs.append(out.read_bytes())
            self.assertEqual(outs[0], outs[1])

    def test_cli_rejects_broken_yaml_without_traceback(self):
        with tempfile.TemporaryDirectory() as d:
            broken = Path(d) / "content.yaml"
            broken.write_text("slides: [unclosed\n", encoding="utf-8")
            r = subprocess.run([sys.executable, str(ROOT / "scripts/adapter.py"), "--content", str(broken),
                                "--design", str(DESIGN), "--output", str(Path(d) / "o.json")], capture_output=True, text=True)
            self.assertEqual(r.returncode, 1)
            self.assertIn("FAIL", r.stderr)
            self.assertNotIn("Traceback", r.stderr)

    def test_cli_write_failure_is_reported(self):
        with tempfile.TemporaryDirectory() as d:
            r = subprocess.run([sys.executable, str(ROOT / "scripts/adapter.py"), "--content", str(CONTENT),
                                "--design", str(DESIGN), "--output", d], capture_output=True, text=True)
            self.assertEqual(r.returncode, 1)
            self.assertNotIn("Traceback", r.stderr)

    def test_section_with_title_only_is_supported(self):
        def to_section(c, _):
            c["slides"][5] = {"id": "s006", "type": "section", "title": "付録", "takeaway": "補足資料"}
        s006 = self.convert(to_section)["slides"][5]
        self.assertEqual((s006["type"], s006["subtitle"]), ("section", "補足資料"))

    def test_key_order_does_not_change_output(self):
        reordered = json.loads(json.dumps(self.content, sort_keys=True))
        reordered["slides"] = [dict(reversed(list(s.items()))) for s in reordered["slides"]]
        a = adapter.canonical_json(adapter.convert(self.content, self.design))
        b = adapter.canonical_json(adapter.convert(reordered, self.design))
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
