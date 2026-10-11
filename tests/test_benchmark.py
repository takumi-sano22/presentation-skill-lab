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

    def test_gate_requires_initial_and_theme_only(self):
        ok = {"built": True, "content_missing": 0, "qa_errors": 0}
        self.assertEqual(benchmark.status(None), "未実行")
        self.assertIn("内容欠落 0", benchmark.status({**ok, "qa_warnings": 0, "japanese_warnings": []}))


if __name__ == "__main__":
    unittest.main()
