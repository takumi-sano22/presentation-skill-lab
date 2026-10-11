"""装飾品質の仕上げ（#22）: 内容を変えずに見せ方だけを調整することのテスト。"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import adapter  # noqa: E402
import diagram  # noqa: E402
import polish  # noqa: E402
import validate  # noqa: E402

EMU = 914400


def cell(text: str, sz: int = 1000) -> str:
    return (f'<a:tc><a:txBody><a:bodyPr/><a:p><a:r><a:rPr lang="en-US" sz="{sz}"><a:latin typeface="Noto Sans JP"/>'
            f'<a:ea typeface="Noto Sans JP"/></a:rPr><a:t>{text}</a:t></a:r></a:p></a:txBody><a:tcPr anchor="ctr"/></a:tc>')


def table(rows: list[list[str]], width_in: float = 9.0, row_h_in: float = 0.42, y_in: float = 1.37) -> str:
    n = len(rows[0])
    grid = "".join(f'<a:gridCol w="{int(width_in / n * EMU)}"/>' for _ in range(n))
    trs = "".join(f'<a:tr h="{int(row_h_in * EMU)}">' + "".join(cell(c) for c in r) + "</a:tr>" for r in rows)
    return (f'<p:graphicFrame><p:nvGraphicFramePr><p:cNvPr id="4" name="Table 0"/></p:nvGraphicFramePr>'
            f'<p:xfrm><a:off x="{int(0.5 * EMU)}" y="{int(y_in * EMU)}"/><a:ext cx="{int(width_in * EMU)}" '
            f'cy="{int(row_h_in * len(rows) * EMU)}"/></p:xfrm><a:graphic><a:graphicData><a:tbl><a:tblGrid>{grid}</a:tblGrid>'
            f'{trs}</a:tbl></a:graphicData></a:graphic></p:graphicFrame>')


def texts(block: str) -> list[str]:
    return re.findall(r"<a:t>([^<]*)</a:t>", block)


class ChartTests(unittest.TestCase):
    def test_single_series_bar_becomes_one_color(self):
        xml = ('<c:barChart><c:varyColors val="0"/><c:ser><c:spPr><a:solidFill><a:srgbClr val="1876A3"/></a:solidFill></c:spPr>'
               '<c:dPt><c:idx val="0"/><c:spPr>A</c:spPr></c:dPt><c:dPt><c:idx val="1"/><c:spPr>B</c:spPr></c:dPt>'
               '<c:val><c:v>84</c:v></c:val></c:ser></c:barChart>')
        out, changed = polish.single_series_bar(xml)
        self.assertTrue(changed)
        self.assertNotIn("<c:dPt>", out)
        self.assertIn("<c:v>84</c:v>", out)  # 値は変えない

    def test_multi_series_and_line_charts_are_untouched(self):
        two = "<c:barChart><c:ser><c:dPt>x</c:dPt></c:ser><c:ser></c:ser></c:barChart>"
        line = "<c:lineChart><c:ser><c:dPt>x</c:dPt></c:ser></c:lineChart>"
        self.assertEqual(polish.single_series_bar(two), (two, False))
        self.assertEqual(polish.single_series_bar(line), (line, False))


class TableTests(unittest.TestCase):
    ROWS = [["検査", "SQL", "期待値"],
            ["孤立した明細", "SELECT COUNT(*) FROM item i LEFT JOIN orders o ON i.order_id = o.order_id WHERE o.order_id IS NULL", "0件"],
            ["負の数量", "SELECT COUNT(*) FROM item WHERE quantity <= 0", "0件"]]

    def test_columns_follow_text_length_and_keep_total_width(self):
        block = table(self.ROWS)
        out, widths = polish.balance_columns(block)
        self.assertIsNotNone(widths)
        self.assertEqual(max(widths), widths[1])  # SQL の列が最も広い
        before = sum(int(w) for w in re.findall(r'<a:gridCol w="(\d+)"', block))
        after = sum(int(w) for w in re.findall(r'<a:gridCol w="(\d+)"', out))
        self.assertEqual(before, after)
        self.assertEqual(texts(out), texts(block))

    def test_even_short_table_is_untouched(self):
        block = table([["A", "B"], ["1", "2"]])
        self.assertEqual(polish.balance_columns(block), (block, None))

    def test_sparse_table_rows_grow_but_stop_before_next_shape(self):
        block = table(self.ROWS)
        out, height = polish.enlarge_rows(block, limit_bottom_in=5.0)
        self.assertAlmostEqual(height, round(min(polish.CONTENT_H * polish.TABLE_FILL_TARGET, 3 * polish.TABLE_ROW_MAX_IN), 3))
        rows = [int(h) for h in re.findall(r'<a:tr h="(\d+)"', out)]
        self.assertIn(f'cy="{sum(rows)}"', out)  # 枠の高さも行の合計に合わせる
        # 下に注記があれば、その手前（0.1in）で止める
        _, limited = polish.enlarge_rows(block, limit_bottom_in=1.37 + 1.6)
        self.assertAlmostEqual(limited, 1.5, places=3)
        # 十分な高さの表は変えない
        self.assertEqual(polish.enlarge_rows(table(self.ROWS, row_h_in=0.7), 5.0)[1], None)

    def test_rows_stop_before_picture_chart_or_line_below(self):
        # 表の下に画像・グラフ・線があれば、文字が無くてもその手前で止める（Codex 指摘）
        block = table(self.ROWS)
        below = (f'<p:pic><p:nvPicPr><p:cNvPr id="9" name="Picture 9"/></p:nvPicPr><p:spPr><a:xfrm>'
                 f'<a:off x="{int(1 * EMU)}" y="{int(2.9 * EMU)}"/><a:ext cx="{int(2 * EMU)}" cy="{int(1 * EMU)}"/></a:xfrm></p:spPr></p:pic>')
        self.assertAlmostEqual(polish.shapes_below(block + below, block), 2.9, places=3)
        side = below.replace(f'x="{int(1 * EMU)}"', f'x="{int(9.6 * EMU)}"')  # 横に重ならない（右の装飾）は対象外
        self.assertAlmostEqual(polish.shapes_below(block + side, block), polish.SLIDE_H - 0.75, places=3)

    def test_monospace_only_body_cells_of_selected_columns(self):
        out, count = polish.monospace_columns(table(self.ROWS), [1], "Consolas")
        self.assertEqual(count, 2)
        rows = re.findall(r"<a:tr .*?</a:tr>", out, re.S)
        self.assertNotIn("Consolas", rows[0])  # 見出し行は本文書体
        for row in rows[1:]:
            cells = re.findall(r"<a:tc>.*?</a:tc>", row, re.S)
            self.assertIn('<a:latin typeface="Consolas"', cells[1])
            self.assertIn('<a:ea typeface="Noto Sans JP"', cells[1])  # 和文書体は残す
            self.assertNotIn("Consolas", cells[0] + cells[2])


class TitleTests(unittest.TestCase):
    @staticmethod
    def title_shape(text: str, w: float, h: float, sz: int, autofit: bool = True) -> str:
        fit = "<a:normAutofit/>" if autofit else ""
        return (f'<p:sp><p:spPr><a:xfrm><a:off x="457200" y="1005840"/><a:ext cx="{int(w * EMU)}" cy="{int(h * EMU)}"/>'
                f'</a:xfrm></p:spPr><p:txBody><a:bodyPr wrap="square" lIns="0" rIns="0">{fit}</a:bodyPr><a:p><a:r>'
                f'<a:rPr lang="en-US" sz="{sz}" b="1"/><a:t>{text}</a:t></a:r><a:endParaRPr sz="{sz}"/></a:p></p:txBody></p:sp>')

    def test_cover_orphan_is_balanced_at_word_boundary(self):
        title = "受注データの関係と整合性検査を共有する"
        block = self.title_shape(title, 7.4, 0.99, 4200)
        out, info = polish.balance_title(block, title)
        self.assertEqual(info["lines"], ["受注データの関係と", "整合性検査を共有する"])
        self.assertIn("<a:br>", out)
        self.assertEqual("".join(texts(out)), title)  # 文字列は変えない
        self.assertEqual(polish.para_texts(out), [title])  # 段落も1つのまま
        self.assertGreaterEqual(info["pt"], info["from_pt"] * polish.TITLE_MIN_RATIO)

    def test_title_without_orphan_is_untouched(self):
        title = "4方式の比較で選定理由を示す"
        block = self.title_shape(title, 7.4, 0.99, 4200)
        self.assertEqual(polish.balance_title(block, title), (block, None))


class LabelLineTests(unittest.TestCase):
    def test_breaks_at_word_boundary_without_single_char_line(self):
        cases = {"取り込みジョブ": ["取り込み", "ジョブ"], "行レベル認可": ["行レベル", "認可"],
                 "生データ保管": ["生データ", "保管"], "認可済み条件": ["認可済み", "条件"]}
        for label, expected in cases.items():
            self.assertEqual(diagram.label_lines(label, 0.65, 11), expected, label)
        self.assertEqual(diagram.label_lines("外部ファイル", 2.0, 11), ["外部ファイル"])  # 収まれば改行しない
        # どの改行位置でも片方の行がはみ出すなら明示改行しない（Codex 指摘）
        self.assertEqual(diagram.label_lines("Authorization認可", 0.6, 11), ["Authorization認可"])
        for label in ("データー", "あいうえおかきく", "Query Tool Server"):
            lines = diagram.label_lines(label, 0.5, 11)
            self.assertEqual("".join(lines).replace(" ", ""), label.replace(" ", ""))
            self.assertTrue(all(lines[1][0] not in diagram.NO_LINE_START for _ in [0]) if len(lines) > 1 else True)
            self.assertTrue(min(len(x) for x in lines) >= 2)

    def test_text_area_follows_shape_geometry(self):
        # 円柱・矩形は全幅、六角形・楕円は狭い（以前の一律 -0.16in より実際の文字領域に近い）
        self.assertGreater(diagram.text_area_width("datastore", 0.98), diagram.text_area_width("tool", 0.98))
        self.assertGreater(diagram.text_area_width("tool", 0.98), diagram.text_area_width("policy", 0.98))
        self.assertAlmostEqual(diagram.text_area_width("actor", 1.0), 0.7071 - 0.04, places=4)
        self.assertGreaterEqual(diagram.text_area_width("datastore", 0.98), diagram.text_width_in("外部ファイル", 11))


class DesignContractTests(unittest.TestCase):
    def load(self):
        deck = ROOT / "examples/bench-dense-tech"
        return (yaml.safe_load((deck / "content.yaml").read_text(encoding="utf-8")),
                yaml.safe_load((deck / "design.yaml").read_text(encoding="utf-8")), deck)

    def errors(self, c, d, deck):
        return validate.schema_errors(d, Path("design")) + validate.cross_validate(c, d, deck)

    def test_design_v02_sample_is_valid(self):
        self.assertEqual(self.errors(*self.load()), [])

    def test_v02_fields_require_v02_and_a_table(self):
        c, d, deck = self.load()
        d["schema_version"] = "0.1"
        self.assertTrue(any("schema_version: '0.2'" in e for e in self.errors(c, d, deck)))
        c, d, deck = self.load()
        d["overrides"]["d302"]["monospace_columns"] = [0]
        self.assertTrue(any("表のないスライド" in e for e in self.errors(c, d, deck)))
        c, d, deck = self.load()
        d["overrides"]["d303"]["monospace_columns"] = [3]
        self.assertTrue(any("列数" in e for e in self.errors(c, d, deck)))

    def test_v01_designs_remain_valid(self):
        for deck in ("technical-architecture", "bench-architecture", "bench-table-chart", "gate4-chatgpt-origin", "bench-er"):
            with self.subTest(deck):
                c = yaml.safe_load((ROOT / "examples" / deck / "content.yaml").read_text(encoding="utf-8"))
                d = yaml.safe_load((ROOT / "examples" / deck / "design.yaml").read_text(encoding="utf-8"))
                self.assertEqual(d["schema_version"], "0.1")
                self.assertEqual(self.errors(c, d, ROOT / "examples" / deck), [])

    def test_dark_band_contrast_is_checked(self):
        theme = {"name": "technical-dark", "fonts": {"heading": "Noto Sans JP", "body": "Noto Sans JP"},
                 "colors": {"background": "#0F172A", "foreground": "#E2E8F0", "accent": "#0284C7", "muted": "#94A3B8"}}
        adapter.check_theme_contrast(theme)  # 既存の暗色テーマは帯の上でも読める
        theme["colors"]["muted"] = "#56657A"  # 背景に対しては 3.x、帯の上ではさらに低い
        with self.assertRaisesRegex(adapter.DesignError, "要点"):
            adapter.check_theme_contrast(theme)


@unittest.skipUnless(os.environ.get("PPTX_NODE_MODULES"), "Docker イメージ内でのみ実行")
class BuiltDeckTests(unittest.TestCase):
    def build(self, deck: str):
        out = Path(self.tmp.name) / deck
        src = ROOT / "examples" / deck
        r = subprocess.run([sys.executable, str(ROOT / "scripts/build.py"), "--content", str(src / "content.yaml"),
                            "--design", str(src / "design.yaml"), "--out", str(out)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return out, json.loads((out / "manifest.json").read_text(encoding="utf-8"))

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_dense_tech_polish_is_applied_and_content_kept(self):
        out, m = self.build("bench-dense-tech")
        fixes = {(p.get("slide_id"), p["fix"]) for p in m["polish"]}
        self.assertTrue({("d301", "title-balance"), ("d303", "table-columns"), ("d303", "table-monospace")} <= fixes)
        self.assertEqual((m["checks"]["content_missing_in_pptx"], m["checks"]["content_missing_in_pdf"],
                          m["checks"]["qa"]["errors"], m["checks"]["japanese_warnings"]), ([], [], [], []))
        with zipfile.ZipFile(out / "deck.pptx") as z:
            xml = z.read("ppt/slides/slide3.xml").decode("utf-8")
        # SQL 列の本文3セル × （文字の rPr と段落末の endParaRPr）
        self.assertEqual(xml.count('<a:latin typeface="Consolas"'), 6)

    def test_single_series_chart_is_one_color(self):
        out, m = self.build("bench-table-chart")
        self.assertIn("chart-single-series", {p["fix"] for p in m["polish"]})
        with zipfile.ZipFile(out / "deck.pptx") as z:
            charts = [z.read(n).decode("utf-8") for n in z.namelist() if re.fullmatch(r"ppt/charts/chart\d+\.xml", n)]
        bar = next(c for c in charts if "<c:barChart>" in c)
        self.assertNotIn("<c:dPt>", bar)


if __name__ == "__main__":
    unittest.main()
