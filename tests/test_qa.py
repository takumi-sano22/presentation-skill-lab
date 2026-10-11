"""総合 QA（幾何・文字サイズ・図の線・編集性・除外）の単体テストと、壊した PPTX で FAIL する結合テスト。"""
from __future__ import annotations

import copy
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import adapter  # noqa: E402
import build  # noqa: E402
import qa  # noqa: E402

EMU = 914400


def sp(name, x, y, w, h, texts=(), sz=1200, flip="", ins=None, autofit=False, kind="sp", anchor="", wrap="", algn=""):
    """合成の図形 XML（単位はインチ）。"""
    off = f'<a:off x="{int(x * EMU)}" y="{int(y * EMU)}"/><a:ext cx="{int(w * EMU)}" cy="{int(h * EMU)}"/>'
    body = ""
    if texts:
        attrs = "" if ins is None else " ".join(f'{k}="{int(v * EMU)}"' for k, v in zip(("lIns", "tIns", "rIns", "bIns"), ins))
        # autofit=True / "norm" は文字縮小（normAutofit）、"shape" は枠の自動伸長（spAutoFit）
        fit = "<a:spAutoFit/>" if autofit == "shape" else ("<a:normAutofit/>" if autofit else "")
        attrs += (f' anchor="{anchor}"' if anchor else "") + (f' wrap="{wrap}"' if wrap else "")
        ppr = f'<a:pPr algn="{algn}"/>' if algn else ""
        paras = "".join(f'<a:p>{ppr}<a:r><a:rPr sz="{sz}"/><a:t>{t}</a:t></a:r></a:p>' for t in texts)
        body = f"<p:txBody><a:bodyPr {attrs}>{fit}</a:bodyPr>{paras}</p:txBody>"
    return (f'<p:{kind}><p:nvSpPr><p:cNvPr id="1" name="{name}"/></p:nvSpPr><p:spPr><a:xfrm{flip}>{off}</a:xfrm>'
            f'</p:spPr>{body}</p:{kind}>')


def frame(name, graphic):
    inner = "<a:tbl></a:tbl>" if graphic == "tbl" else '<c:chart r:id="rId1"/>'
    return (f'<p:graphicFrame><p:nvGraphicFramePr><p:cNvPr id="1" name="{name}"/></p:nvGraphicFramePr>'
            f'<p:xfrm><a:off x="{EMU}" y="{EMU}"/><a:ext cx="{EMU}" cy="{EMU}"/></p:xfrm><a:graphic>{inner}</a:graphic></p:graphicFrame>')


def run_slide(xml, slide=None, psl=None):
    slide = slide or {"id": "s1"}
    return qa.check_slide("s1", slide, {"psl": psl or {}}, qa.parse_shapes(xml))


def checks(findings, severity="error"):
    return {f.check for f in findings if f.severity == severity}


class QaUnitTests(unittest.TestCase):
    def test_out_of_bounds_text_is_error_and_decoration_is_warning(self):
        f = run_slide(sp("t", 9.5, 1, 1, 0.5, ["はみ出す文字"]) + sp("deco", 9.8, 6.0, 0.2, 0.1))
        self.assertIn("out-of-bounds", checks(f))
        self.assertIn("out-of-bounds", checks(f, "warning"))

    def test_text_overlap(self):
        self.assertIn("text-overlap", checks(run_slide(sp("a", 1, 1, 3, 1, ["文字A"]) + sp("b", 2, 1.2, 3, 1, ["文字B"]))))
        self.assertNotIn("text-overlap", checks(run_slide(sp("a", 1, 1, 2, 1, ["文字A"]) + sp("b", 4, 1, 2, 1, ["文字B"]))))

    def test_text_overflow_uses_insets_and_respects_autofit(self):
        long = "長い本文" * 20
        # あふれが下の文字図形と重なれば FAIL、空き領域に収まるだけなら警告
        self.assertIn("text-overflow", checks(run_slide(sp("a", 1, 1, 2, 0.4, [long]) + sp("below", 1, 1.6, 2, 0.4, ["下の文字"]))))
        self.assertIn("text-overflow", checks(run_slide(sp("a", 1, 1, 2, 0.4, [long])), "warning"))
        self.assertNotIn("text-overflow", checks(run_slide(sp("a", 1, 1, 2, 0.4, [long]))))
        self.assertIn("text-overflow", checks(run_slide(sp("a", 1, 4.5, 2, 0.4, [long]))))  # スライド下端に達する
        # あふれ先に表・画像があれば FAIL
        self.assertIn("text-overflow", checks(run_slide(sp("a", 1, 1, 2, 0.4, [long]) + frame("t", "tbl"))))
        self.assertIn("text-overflow", checks(run_slide(sp("a", 1, 1, 2, 0.4, [long]) + sp("asset:x", 1, 1.6, 2, 1, kind="pic"))))
        self.assertNotIn("text-overflow", checks(run_slide(sp("a", 1, 1, 2, 0.4, [long], autofit=True))))
        # 内側余白 0 の小さなラベル（図の辺ラベル）は1行で収まる
        self.assertNotIn("text-overflow", checks(run_slide(sp("l", 1, 1, 0.62, 0.21, ["認可照会"], sz=900, ins=(0, 0, 0, 0)))))

    def test_autofit_shrink_below_minimum_is_detected(self):
        long = "長い本文" * 40
        self.assertIn("min-font", checks(run_slide(sp("a", 1, 1, 2, 0.4, [long], sz=1600, autofit=True))))
        # 少し縮めれば収まる程度なら問題なし
        self.assertNotIn("min-font", checks(run_slide(sp("a", 1, 1, 4, 0.6, ["見出しの文言"], sz=2800, autofit=True))))
        # PowerPoint が保存した縮小率（fontScale）も使う
        xml = sp("b", 1, 1, 4, 1, ["本文"], sz=1200, autofit=True).replace("<a:normAutofit/>", '<a:normAutofit fontScale="62500"/>')
        self.assertIn("min-font", checks(run_slide(xml)))

    def test_shape_autofit_is_distinguished_from_normal_autofit(self):
        long = "長い本文" * 20
        self.assertEqual(qa.parse_shapes(sp("a", 1, 1, 2, 0.4, [long], autofit="shape"))[0].autofit, "shape")
        self.assertEqual(qa.parse_shapes(sp("a", 1, 1, 2, 0.4, [long], autofit=True))[0].autofit, "norm")
        # spAutoFit は文字を縮めず枠を伸ばすので、自動縮小の min-font 推定の対象にしない
        self.assertNotIn("min-font", checks(run_slide(sp("a", 1, 1, 2, 0.4, [long * 2], sz=1600, autofit="shape"))))

    def test_shape_autofit_expansion_collision(self):
        long = "長い本文" * 20
        below = sp("below", 1, 1.6, 2, 0.4, ["下の文字"])
        # 上揃え: 下へ伸びて下の文字と重なれば FAIL、空き領域なら問題なし
        self.assertIn("autofit-expansion", checks(run_slide(sp("a", 1, 1, 2, 0.4, [long], autofit="shape") + below)))
        self.assertEqual(run_slide(sp("a", 1, 1, 2, 0.4, [long], autofit="shape")), [])
        # 下揃え: 上へ伸びる。上にある見出しと衝突、下の文字とは衝突しない
        mid = "長い本文" * 10  # 4 行ほど → 上へ約 0.5in 伸びる
        above = sp("title", 1, 0.4, 2, 0.4, ["見出し"])
        f = run_slide(above + sp("a", 1, 1.2, 2, 0.4, [mid], autofit="shape", anchor="b"))
        self.assertIn("autofit-expansion", checks(f))
        self.assertNotIn("autofit-expansion", checks(run_slide(sp("a", 1, 1.2, 2, 0.4, [mid], autofit="shape", anchor="b") + below)))
        # スライド下端の外へ伸びれば FAIL、表・画像との衝突も FAIL
        self.assertIn("autofit-expansion", checks(run_slide(sp("a", 1, 5.0, 2, 0.4, [long], autofit="shape"))))
        self.assertIn("autofit-expansion", checks(run_slide(sp("a", 1, 0.5, 2, 0.4, [long], autofit="shape") + frame("t", "tbl"))))
        # 折り返さない枠（wrap="none"）は横へ伸びる: 左揃えは右へ、右揃えは左へ（Codex 指摘）
        line = "折り返さない一行の長い見出し文字列" * 2  # 12pt で約 5.7in
        right = sp("right", 7.5, 1, 1.5, 0.4, ["右の文字"])
        self.assertIn("autofit-expansion", checks(run_slide(sp("a", 4, 1, 3, 0.4, [line], autofit="shape", wrap="none") + right)))
        self.assertNotIn("autofit-expansion", checks(run_slide(sp("a", 4, 1, 3, 0.4, [line], autofit="shape", wrap="none", algn="r") + right)))
        self.assertIn("autofit-expansion", checks(run_slide(sp("a", 0.5, 1, 3, 0.4, [line], autofit="shape", wrap="none", algn="r"))))
        self.assertIn("autofit-expansion", checks(run_slide(sp("a", 7, 1, 2.5, 0.4, [line], autofit="shape", wrap="none"))))
        # 文字が収まっていれば伸びない
        self.assertEqual(run_slide(sp("a", 1, 1, 3, 0.6, ["短い"], autofit="shape") + below), [])

    def test_min_font(self):
        self.assertIn("min-font", checks(run_slide(sp("a", 1, 1, 3, 1, ["小さい"], sz=800))))
        self.assertNotIn("min-font", checks(run_slide(sp("a", 1, 1, 3, 1, ["九ポ"], sz=900))))

    def test_connector_crossing_uses_flip_direction(self):
        psl = {"diagram_layout": {"nodes": []}}
        label = sp("edge-label:5:x:y", 2.0, 1.4, 0.6, 0.2, ["ラベル"], sz=900, ins=(0, 0, 0, 0))
        # 右下がりの線 (1,1)→(4,2) は（別の辺の）ラベルの中を通る
        crossing = sp("edge:0:a->b#0", 1, 1, 3, 1, kind="sp") + label
        self.assertIn("connector-crossing", checks(run_slide(crossing, psl=psl)))
        # 自分の辺のラベルは線上にあってよい（密な図のフォールバック）
        own = sp("edge:0:a->b#0", 1, 1, 3, 1) + sp("edge-label:0:a:b", 2.0, 1.4, 0.6, 0.2, ["自分"], sz=900, ins=(0, 0, 0, 0))
        self.assertNotIn("connector-crossing", checks(run_slide(own, psl=psl)))
        other = sp("edge:1:c->d#0", 1, 1, 3, 1) + sp("edge-label:0:a:b", 2.0, 1.4, 0.6, 0.2, ["他人"], sz=900, ins=(0, 0, 0, 0))
        self.assertIn("connector-crossing", checks(run_slide(other, psl=psl)))
        # 右上がり（flipV）の線 (1,2)→(4,1) はラベルの下側を通らない
        flipped = sp("edge:0:a->b#0", 1, 1, 3, 1, flip=' flipV="1"') + sp("edge-label:0:a:b", 1.2, 1.05, 0.6, 0.2, ["ラベル"], sz=900, ins=(0, 0, 0, 0))
        self.assertNotIn("connector-crossing", checks(run_slide(flipped, psl=psl)))

    def test_rasterized_table_and_chart_are_detected(self):
        table_slide = {"id": "s1", "table": {"headers": ["a", "b"], "rows": [["1", "2"]]}}
        pic = sp("Picture 3", 1, 1, 6, 3, kind="pic")
        self.assertTrue({"rasterized-table", "missing-native-table"} <= checks(run_slide(pic, table_slide)))
        self.assertEqual(checks(run_slide(frame("t", "tbl"), table_slide)), set())
        chart_slide = {"id": "s1", "chart": {"type": "bar"}}
        self.assertTrue({"rasterized-chart", "missing-native-chart"} <= checks(run_slide(pic, chart_slide)))
        self.assertEqual(checks(run_slide(frame("c", "chart"), chart_slide)), set())

    def test_registered_asset_image_is_allowed(self):
        psl = {"image": {"asset_ref": "assets/a.svg"}}
        self.assertEqual(checks(run_slide(sp("asset:assets/a.svg", 1, 1, 6, 3, kind="pic"), psl=psl)), set())


class QaExceptionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.deck = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, text):
        (self.deck / qa.EXCEPTIONS_FILE).write_text(text, encoding="utf-8")

    def test_exception_requires_slide_id_and_reason(self):
        self.write("exceptions:\n  - {slide_id: s1, check: min-font, target: Text 3}\n")
        with self.assertRaises(ValueError):
            qa.load_exceptions(self.deck)
        self.write("exceptions:\n  - {slide_id: s1, check: no-such-check, target: x, reason: y}\n")
        with self.assertRaises(ValueError):
            qa.load_exceptions(self.deck)

    def test_malformed_exception_file_is_reported(self):
        for text in ("exceptions: foo\n", "- a\n- b\n", "exceptions:\n  - just-a-string\n", "exceptions: [unclosed\n"):
            with self.subTest(text=text):
                self.write(text)
                with self.assertRaises(ValueError):
                    qa.load_exceptions(self.deck)

    def test_exception_excuses_only_matching_finding_and_reports_stale(self):
        self.write("exceptions:\n"
                   "  - {slide_id: s1, check: min-font, target: small, reason: 法定表記のため 8pt を許容}\n"
                   "  - {slide_id: s9, check: text-overlap, target: x, reason: 使われない除外}\n")
        xml = sp("small", 1, 1, 3, 1, ["注記"], sz=800) + sp("other", 1, 3, 3, 1, ["本文"], sz=800)
        pptx = self.deck / "x.pptx"
        with zipfile.ZipFile(pptx, "w") as z:
            z.writestr("ppt/slides/slide1.xml", f"<p:sld>{xml}</p:sld>")
        r = qa.run_qa({"slides": [{"id": "s1"}]}, {"slides": [{"psl": {}}]}, pptx, self.deck)
        self.assertEqual([e["target"] for e in r["errors"]], ["other"])
        self.assertEqual(r["excused"][0]["reason"], "法定表記のため 8pt を許容")
        self.assertEqual([e["slide_id"] for e in r["stale_exceptions"]], ["s9"])


def mutate(src: Path, dst: Path, part: str, func) -> Path:
    """PPTX の1パーツを書き換えた複製を作る（意図的に壊したサンプル）。"""
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename == part:
                data = func(data.decode("utf-8")).encode("utf-8")
            zout.writestr(info, data)
    return dst


@unittest.skipUnless(os.environ.get("PPTX_NODE_MODULES"), "Docker イメージ内でのみ実行")
class BrokenSampleTests(unittest.TestCase):
    """正常サンプルは重大 FAIL 0、意図的に壊すと各検査が FAIL する（#8 DoD）。"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name) / "deck"
        deck = ROOT / "examples/technical-architecture"
        r = subprocess.run([sys.executable, str(ROOT / "scripts/build.py"), "--content", str(deck / "content.yaml"),
                            "--design", str(deck / "design.yaml"), "--out", str(cls.out)], capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr
        cls.content, _ = adapter.load_and_validate(deck / "content.yaml", deck / "design.yaml")
        cls.outline = json.loads((cls.out / "outline.json").read_text(encoding="utf-8"))
        cls.deck = deck
        cls.pptx = cls.out / "deck.pptx"

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def broken(self, name, part, func):
        return mutate(self.pptx, Path(self.tmp.name) / f"{name}.pptx", part, func)

    def qa_checks(self, pptx):
        return {e["check"] for e in qa.run_qa(self.content, self.outline, pptx, self.deck)["errors"]}

    def test_normal_sample_has_no_severe_failure(self):
        report = json.loads((self.out / "qa/report.json").read_text(encoding="utf-8"))
        self.assertTrue(report["passed"])
        self.assertEqual(report["checks"]["qa"]["errors"], [])

    def test_table_rasterized(self):
        # 表のグラフィックフレームを画像に置き換える
        def to_picture(xml):
            return re.sub(r"<p:graphicFrame>.*?</p:graphicFrame>",
                          sp("Picture 9", 0.5, 1.5, 9, 2.5, kind="pic"), xml, count=1, flags=re.S)
        pptx = self.broken("raster", "ppt/slides/slide4.xml", to_picture)
        self.assertTrue({"rasterized-table", "missing-native-table"} <= self.qa_checks(pptx))
        self.assertTrue(build.check_content_in_pptx(self.content, pptx, self.outline))  # 表セルも欠落

    def test_cell_dropped(self):
        pptx = self.broken("cell", "ppt/slides/slide4.xml", lambda x: x.replace("<a:t>実装次第</a:t>", "<a:t></a:t>", 1))
        self.assertIn("s004: 「実装次第」", build.check_content_in_pptx(self.content, pptx, self.outline))

    def test_number_changed_or_rounded(self):
        pptx = self.broken("value", "ppt/charts/chart1.xml", lambda x: x.replace("<c:v>28</c:v>", "<c:v>27</c:v>", 1))
        self.assertIn("s005: 「28」", build.check_content_in_pptx(self.content, pptx, self.outline))
        # 丸め: 入力 28.4 に対し出力が 28 なら欠落（完全一致で照合）
        rounded = copy.deepcopy(self.content)
        rounded["slides"][4]["chart"]["series"][0]["values"][1] = 28.4
        self.assertIn("s005: 「28.4」", build.check_content_in_pptx(rounded, self.pptx, self.outline))

    def test_shape_moved_out_of_slide(self):
        # 本文（文字を持つ図形）の枠をスライド右端の外へ動かす
        def push_out(xml):
            return re.sub(r'(<p:sp>(?:(?!</p:sp>).)*?複数データソース(?:(?!</p:sp>).)*?</p:sp>)',
                          lambda m: re.sub(r'<a:off x="\d+"', f'<a:off x="{int(9.8 * EMU)}"', m.group(1), count=1),
                          xml, count=1, flags=re.S)
        pptx = self.broken("oob", "ppt/slides/slide2.xml", push_out)
        self.assertIn("out-of-bounds", self.qa_checks(pptx))

    def test_shape_autofit_expansion_in_real_pptx(self):
        # 本文枠を spAutoFit に変え、文字を大幅に増やしてスライド下端の外まで伸びるようにする（空き領域に収まる伸長は問題にしない）
        def grow(xml):
            def edit(m):
                block = re.sub(r"<a:normAutofit/>|<a:noAutofit/>", "", m.group(1))
                block = re.sub(r"(<a:bodyPr[^>]*?)(/?)>", lambda b: b.group(1) + "><a:spAutoFit/></a:bodyPr>" if b.group(2)
                               else b.group(1) + "><a:spAutoFit/>", block, count=1)
                return block.replace("複数データソース", "複数データソース" * 100, 1)
            return re.sub(r'(<p:sp>(?:(?!</p:sp>).)*?複数データソース(?:(?!</p:sp>).)*?</p:sp>)', edit, xml, count=1, flags=re.S)
        pptx = self.broken("spautofit", "ppt/slides/slide2.xml", grow)
        self.assertIn("autofit-expansion", self.qa_checks(pptx))

    def test_tiny_font(self):
        pptx = self.broken("tiny", "ppt/slides/slide6.xml", lambda x: re.sub(r'sz="\d+"', 'sz="700"', x, count=3))
        self.assertIn("min-font", self.qa_checks(pptx))

    def test_overlapping_text(self):
        # 本文の枠を見出しの位置へ動かして重ねる
        def overlap(xml):
            return re.sub(r'(<p:sp>(?:(?!</p:sp>).)*?複数データソース(?:(?!</p:sp>).)*?</p:sp>)',
                          lambda m: re.sub(r'<a:off x="\d+" y="\d+"/>', f'<a:off x="{int(0.5 * EMU)}" y="{int(0.1 * EMU)}"/>', m.group(1), count=1),
                          xml, count=1, flags=re.S)
        pptx = self.broken("overlap", "ppt/slides/slide2.xml", overlap)
        self.assertIn("text-overlap", self.qa_checks(pptx))

    def test_diagram_line_through_label(self):
        # 辺 agent->tool のラベルを、配置結果から求めた別の辺（user->agent）の中点へ動かす
        lay = self.outline["slides"][2]["psl"]["diagram_layout"]
        (x1, y1), (x2, y2) = lay["edges"][0]["points"][:2]
        box = lay["edges"][3]["label_box"]
        x, y = (x1 + x2) / 2 - box["w"] / 2, (y1 + y2) / 2 - box["h"] / 2

        def move_label(xml):
            return re.sub(r'(name="edge-label:3:agent:tool".*?<a:off x=")\d+(" y=")\d+',
                          lambda m: m.group(1) + str(int(x * EMU)) + m.group(2) + str(int(y * EMU)), xml, count=1, flags=re.S)
        pptx = self.broken("cross", "ppt/slides/slide3.xml", move_label)
        self.assertIn("connector-crossing", self.qa_checks(pptx))


if __name__ == "__main__":
    unittest.main()
