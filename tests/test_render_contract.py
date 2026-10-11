"""adapter 出力が固定上流レンダラで意図どおり描画されるかの実描画テスト（Docker イメージ内でのみ実行）。

ホストでは上流の Node 依存を実行しない方針のため、PPTX_NODE_MODULES が無ければ skip する。
"""
from __future__ import annotations

import copy
import html
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


WRAPPER = ROOT / "scripts/render.js"


def part_xml(pptx: Path, pattern: str) -> str:
    with zipfile.ZipFile(pptx) as z:
        return "".join(z.read(n).decode("utf-8") for n in z.namelist() if re.fullmatch(pattern, n))


@unittest.skipUnless(os.environ.get("PPTX_NODE_MODULES") and RENDERER.is_file(), "Docker イメージ内でのみ実行")
class RenderContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.content, self.design = adapter.load_and_validate(
            ROOT / "examples/technical-architecture/content.yaml", ROOT / "examples/technical-architecture/design.yaml")
        self.outline = adapter.convert(self.content, self.design)

    def tearDown(self):
        self.tmp.cleanup()

    def render(self, outline: dict, name: str = "deck", raw: bool = False) -> Path:
        """scripts/render.js（テーマ注入）経由で描画する。raw=True は上流を直接呼ぶ対照用。"""
        path, out = Path(self.tmp.name) / f"{name}.json", Path(self.tmp.name) / f"{name}.pptx"
        path.write_text(adapter.canonical_json(outline), encoding="utf-8")
        cmd = (["node", str(RENDERER), "--outline", str(path), "--output", str(out),
                "--style-preset", outline["psl"]["render"]["style_preset"]] if raw
               else ["node", str(WRAPPER), "--outline", str(path), "--output", str(out)])
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        return out

    def test_v1_pin_suppresses_v2_placeholders(self):
        texts = set(slide_texts(self.render(self.outline)))
        self.assertFalse(texts & V2_PLACEHOLDERS, texts & V2_PLACEHOLDERS)
        # 対照: v2 契約が表に "TABLE INDEX" を足す editorial-minimal で、pin の有無を比べる
        # （pin ありで出ず、外すと出る = pin が実際に効いている証拠）
        editorial = copy.deepcopy(self.outline)
        editorial["psl"]["render"]["style_preset"] = "editorial-minimal"
        self.assertFalse(set(slide_texts(self.render(editorial, "pinned"))) & V2_PLACEHOLDERS)
        del editorial["deck_style"]["renderer_role_systems_v1"]
        self.assertTrue(set(slide_texts(self.render(editorial, "unpinned"))) & V2_PLACEHOLDERS)

    def test_source_label_and_cover_kicker_are_japanese(self):
        texts = slide_texts(self.render(self.outline))
        self.assertTrue(any(t.startswith("出典") for t in texts))
        self.assertFalse(any(t.startswith("Sources") for t in texts))
        self.assertIn("公開資料", texts)
        self.assertNotIn("POLICY BRIEF", texts)

    def test_theme_fonts_and_colors_are_applied(self):
        xml = part_xml(self.render(self.outline), r"ppt/slides/slide\d+\.xml")
        # 欧文（latin）・和文（ea）とも design のフォント名だけになる
        self.assertEqual(set(re.findall(r'<a:(?:latin|ea) typeface="([^"]+)"', xml)), {"Noto Sans JP"})
        colors = set(re.findall(r'srgbClr val="([0-9A-F]{6})"', xml))
        self.assertTrue({"F8FAFC", "14213D", "1876A3", "627286"} <= colors, colors)
        # 基底プリセット（arctic-minimal）固有のアクセント・本文色が残っていない
        self.assertFalse({"0EA5E9", "0F172A", "64748B"} & colors, colors)
        # 対照: テーマ注入なしの上流直呼びではプリセットの色・フォントになる
        raw_xml = part_xml(self.render(self.outline, "raw", raw=True), r"ppt/slides/slide\d+\.xml")
        self.assertIn("0EA5E9", raw_xml)

    def test_chart_axis_text_uses_muted_color(self):
        chart = part_xml(self.render(self.outline), r"ppt/charts/chart\d+\.xml")
        axes = "".join(re.findall(r"<c:(?:catAx|valAx)>.*?</c:(?:catAx|valAx)>", chart, re.S))
        self.assertIn('srgbClr val="627286"', axes)
        self.assertNotIn('srgbClr val="000000"', axes)

    def test_diagram_is_editable_native_shapes(self):
        pptx = self.render(self.outline)
        with zipfile.ZipFile(pptx) as z:
            xml = z.read("ppt/slides/slide3.xml").decode("utf-8")
        # 画像として埋め込まない
        self.assertNotIn("<p:pic>", xml)
        shapes = {html.unescape(m.group(1)): m.group(0)
                  for m in re.finditer(r'<p:sp>.*?name="([^"]+)".*?</p:sp>', xml, re.S)}
        for node in self.content["slides"][2]["diagram"]["nodes"]:
            block = shapes[f"node:{node['id']}"]
            # ノードは文字を持つ図形（PowerPoint で文字・形・位置を編集できる）
            self.assertIn(node["label"], re.findall(r"<a:t[^>]*>([^<]*)</a:t>", block))
            self.assertIn("<a:prstGeom", block)
        edges = [n for n in shapes if n.startswith("edge:")]
        self.assertEqual({n.split("#")[0] for n in edges},
                         {f"edge:{i}:{e['from']}->{e['to']}" for i, e in enumerate(self.content["slides"][2]["diagram"]["edges"])})
        # 制御の辺は破線、データの辺は実線（線種で意味を示す）
        self.assertIn('prstDash val="dash"', shapes["edge:1:agent->policy#0"])
        self.assertNotIn('prstDash val="dash"', shapes["edge:0:user->agent#0"])

    def test_dark_theme_uses_dark_surfaces(self):
        _, dark = adapter.load_and_validate(ROOT / "examples/technical-architecture/content.yaml",
                                            ROOT / "examples/technical-architecture/design-dark.yaml")
        xml = part_xml(self.render(adapter.convert(self.content, dark), "dark"), r"ppt/slides/slide\d+\.xml")
        colors = set(re.findall(r'srgbClr val="([0-9A-F]{6})"', xml))
        self.assertTrue({"0F172A", "E2E8F0", "0284C7"} <= colors, colors)
        # midnight-neon 固有の色（アクセント・面・罫線）が残っていない
        self.assertFalse({"22D3EE", "F43F5E", "101A33", "1E293B"} & colors, colors)
        # 使われる色はすべて design 由来（背景・前景・アクセント・補助、面と罫線は背景/前景の混色、表ヘッダの白）
        allowed = {"0F172A", "E2E8F0", "0284C7", "94A3B8", "171F32", "353D4E", "FFFFFF"}
        self.assertTrue(colors <= allowed, colors - allowed)


if __name__ == "__main__":
    unittest.main()
