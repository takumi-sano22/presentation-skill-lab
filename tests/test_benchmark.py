"""ベンチマークの条件生成（テーマ変更・文言増加）が内容の数値・表セル・図ラベルを変えないことのテスト。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import adapter  # noqa: E402
import benchmark  # noqa: E402


def load(deck: str) -> tuple[dict, dict]:
    src = ROOT / "examples" / deck
    return (yaml.safe_load((src / "content.yaml").read_text(encoding="utf-8")),
            yaml.safe_load((src / "design.yaml").read_text(encoding="utf-8")))


class BenchmarkVariantTests(unittest.TestCase):
    def test_benchmark_decks_are_valid_and_synthetic(self):
        for deck in benchmark.DECKS:
            with self.subTest(deck):
                content, design = adapter.load_and_validate(ROOT / "examples" / deck / "content.yaml",
                                                            ROOT / "examples" / deck / "design.yaml")
                self.assertTrue(content["metadata"]["synthetic"])
                self.assertEqual(content["metadata"]["classification"], "public")
                adapter.convert(content, design, ROOT / "examples" / deck, ROOT / "build")

    def test_theme_variant_changes_design_only(self):
        content, design = load("bench-table-chart")
        c2, d2 = benchmark.variant(content, design, "theme")
        self.assertEqual(adapter.content_hash(c2), adapter.content_hash(content))
        self.assertEqual(d2["theme"]["name"], "technical-dark")

    def test_text_plus_keeps_numbers_cells_and_labels(self):
        for deck in benchmark.DECKS:
            with self.subTest(deck):
                content, design = load(deck)
                c2, _ = benchmark.variant(content, design, "text_plus")
                for before, after in zip(content["slides"], c2["slides"]):
                    for key in ("title", "table", "chart", "diagram", "source_refs"):
                        self.assertEqual(before.get(key), after.get(key))
                    if before.get("body"):
                        self.assertTrue(all(len(new) > len(old) for old, new in zip(before["body"], after["body"])))

    def test_status_labels(self):
        ok = {"built": True, "content_missing": 0, "qa_errors": 0}
        self.assertEqual(benchmark.status(None), "未実行")
        self.assertIn("内容欠落 0", benchmark.status({**ok, "qa_warnings": 0, "japanese_warnings": []}))


def fake_manifest(missing=(), qa_errors=0, diagram_errors=()):
    """benchmark.metrics() に渡す最小の manifest。"""
    return {"fallbacks": {}, "checks": {
        "content_missing_in_pptx": list(missing), "content_missing_in_pdf": [], "diagram_errors": list(diagram_errors),
        "media_errors": [], "font_errors": [], "japanese_errors": [], "japanese_warnings": [], "non_content_text": {},
        "diagram_crossings": {}, "qa": {"errors": [{}] * qa_errors, "warnings": []}}}


def result(condition, manifest, built=True, deck="bench-architecture"):
    r = {"deck": deck, "condition": condition, **benchmark.metrics(manifest)}
    if not built:
        r.update(built=False, error="検査 FAIL")
    return r


class BenchmarkGateTests(unittest.TestCase):
    """#24: 文言増加（text_plus）も意味保持は必須、幾何の崩れは想定崩れとして記録する。"""

    def gate(self, results):
        return benchmark.gate_failures(results, Path("build/benchmark"))

    def test_all_clean_passes(self):
        failures, stress = self.gate([result(c, fake_manifest()) for c in benchmark.CONDITIONS])
        self.assertEqual((failures, stress), ([], []))

    def test_text_plus_meaning_loss_fails(self):
        for m in (fake_manifest(missing=["b102: 「12」"]), fake_manifest(diagram_errors=["edge 不明"])):
            failures, _ = self.gate([result("text_plus", m, built=False)])
            self.assertTrue(failures and "text_plus" in failures[0], failures)

    def test_text_plus_without_manifest_fails(self):
        failures, _ = self.gate([result("text_plus", None)])
        self.assertEqual(len(failures), 1)

    def test_text_plus_geometry_break_is_recorded_not_failed(self):
        failures, stress = self.gate([result("text_plus", fake_manifest(qa_errors=2), built=False)])
        self.assertEqual(failures, [])
        self.assertEqual(stress[0]["qa_errors"], 2)
        self.assertIn("scripts/build --content", stress[0]["repro"])

    def test_initial_and_theme_geometry_break_fails(self):
        for c in benchmark.REQUIRED_CLEAN:
            failures, _ = self.gate([result(c, fake_manifest(qa_errors=1), built=False)])
            self.assertEqual(len(failures), 1, c)


if __name__ == "__main__":
    unittest.main()
