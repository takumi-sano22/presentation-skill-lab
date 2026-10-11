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

    def test_tampered_outline_fails(self):
        cases = {
            "表セル改変": lambda o: o["slides"][3]["table"]["rows"][0].__setitem__(1, "不可"),
            "数値改変": lambda o: o["slides"][4]["chart"]["series"][0]["values"].__setitem__(0, 21),
            "本文欠落": lambda o: o["slides"][1]["bullets"].pop(),
            "出典欠落": lambda o: o["slides"][4].pop("sources"),
            "順序入替": lambda o: o["slides"].reverse(),
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
        }
        for name, mutate in cases.items():
            with self.subTest(name):
                with self.assertRaises(adapter.UnsupportedContent):
                    self.convert(mutate)

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

    def test_key_order_does_not_change_output(self):
        reordered = json.loads(json.dumps(self.content, sort_keys=True))
        reordered["slides"] = [dict(reversed(list(s.items()))) for s in reordered["slides"]]
        a = adapter.canonical_json(adapter.convert(self.content, self.design))
        b = adapter.canonical_json(adapter.convert(reordered, self.design))
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
