"""adapter 出力が固定上流レンダラで意図どおり描画されるかの実描画テスト（Docker イメージ内でのみ実行）。

ホストでは上流の Node 依存を実行しない方針のため、PPTX_NODE_MODULES が無ければ skip する。
"""
from __future__ import annotations

import copy
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import adapter  # noqa: E402

RENDERER = ROOT / "vendor/presentation-skill/scripts/build_deck_pptxgenjs.js"
# 上流 v2 契約が足す英語ラベル・プレースホルダ（v1 固定で出ないこと）
V2_PLACEHOLDERS = {"TABLE INDEX", "READOUT", "Key readout", "PRESENTATION"}


def slide_texts(pptx: Path) -> list[str]:
    with zipfile.ZipFile(pptx) as z:
        names = [n for n in z.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)]
        return [t for n in names for t in re.findall(r"<a:t>([^<]*)</a:t>", z.read(n).decode("utf-8"))]


@unittest.skipUnless(os.environ.get("PPTX_NODE_MODULES") and RENDERER.is_file(), "Docker イメージ内でのみ実行")
class RenderContractTests(unittest.TestCase):
    def render(self, outline: dict) -> list[str]:
        with tempfile.TemporaryDirectory() as d:
            path, out = Path(d) / "outline.json", Path(d) / "deck.pptx"
            path.write_text(adapter.canonical_json(outline), encoding="utf-8")
            subprocess.run(["node", str(RENDERER), "--outline", str(path), "--output", str(out),
                            "--style-preset", outline["psl"]["render"]["style_preset"]],
                           check=True, capture_output=True, text=True)
            return slide_texts(out)

    def setUp(self):
        content, design = adapter.load_and_validate(ROOT / "examples/technical-architecture/content.yaml",
                                                    ROOT / "examples/technical-architecture/design.yaml")
        self.outline = adapter.convert(content, design)

    def test_v1_pin_suppresses_v2_placeholders(self):
        texts = set(self.render(self.outline))
        self.assertFalse(texts & V2_PLACEHOLDERS, texts & V2_PLACEHOLDERS)
        # 対照: pin を外すと上流は v2 契約に戻り、プレースホルダが出る（pin が実際に効いている証拠）
        unpinned = copy.deepcopy(self.outline)
        del unpinned["deck_style"]["renderer_role_systems_v1"]
        self.assertTrue(set(self.render(unpinned)) & V2_PLACEHOLDERS)

    def test_source_label_is_japanese(self):
        texts = self.render(self.outline)
        self.assertTrue(any(t.startswith("出典") for t in texts))
        self.assertFalse(any(t.startswith("Sources") for t in texts))


if __name__ == "__main__":
    unittest.main()
