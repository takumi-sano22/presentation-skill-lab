"""ビルド CLI の検査関数（ホスト）と、実ビルドの結合テスト（Docker イメージ内のみ）。"""
from __future__ import annotations

import json
import os
import struct
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

CONTENT = ROOT / "examples/technical-architecture/content.yaml"
DESIGN = ROOT / "examples/technical-architecture/design.yaml"


def fake_pptx(path: Path, slides: list[list], chart_values: list[str] | None = None) -> Path:
    """段落（文字列、または複数ランのリスト）だけを持つ最小の PPTX 風 zip（検査関数のテスト用）。"""
    def para(p):
        runs = p if isinstance(p, list) else [p]
        return "<a:p>" + "".join(f"<a:r><a:t>{r}</a:t></a:r>" for r in runs) + "</a:p>"
    with zipfile.ZipFile(path, "w") as z:
        for i, paras in enumerate(slides, start=1):
            z.writestr(f"ppt/slides/slide{i}.xml", "<p:sld>" + "".join(para(p) for p in paras) + "</p:sld>")
        if chart_values is not None:
            z.writestr("ppt/slides/_rels/slide1.xml.rels", '<Relationships><Relationship Target="/ppt/charts/chart1.xml"/></Relationships>')
            z.writestr("ppt/charts/chart1.xml", "<c:chart>" + "".join(f"<c:v>{v}</c:v>" for v in chart_values) + "</c:chart>")
    return path


class BuildCheckTests(unittest.TestCase):
    def setUp(self):
        self.content, _ = adapter.load_and_validate(CONTENT, DESIGN)
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def one_slide(self, slide: dict) -> dict:
        return {"slides": [slide]}

    def test_normalize_ignores_wrapping_and_width(self):
        self.assertEqual(build.normalize("Ａ Ｂ\n１２"), build.normalize("AB12"))

    def test_missing_text_is_detected(self):
        slide = {"id": "s1", "title": "タイトル", "takeaway": "要点", "body": ["本文A", "本文B"]}
        pptx = fake_pptx(self.dir / "a.pptx", [["タイトル", "要点", "本文A"]])
        self.assertEqual(build.check_content_in_pptx(self.one_slide(slide), pptx), ["s1: 「本文B」"])

    def test_text_split_across_runs_is_accepted(self):
        # 折返しや装飾でランが分割されても、連結した文字列で照合する
        slide = {"id": "s1", "title": "長いタイトル", "takeaway": ""}
        pptx = fake_pptx(self.dir / "b.pptx", [[["長い", "タイ", "トル"]]])
        self.assertEqual(build.check_content_in_pptx(self.one_slide(slide), pptx), [])

    def test_chart_values_are_read_from_chart_part(self):
        slide = {"id": "s1", "title": "グラフ", "takeaway": "",
                 "chart": {"type": "bar", "unit": "件", "categories": ["A"], "series": [{"name": "系列", "values": [20]}]}}
        ok = fake_pptx(self.dir / "c.pptx", [["グラフ", "単位: 件"]], ["系列", "A", "20"])
        self.assertEqual(build.check_content_in_pptx(self.one_slide(slide), ok), [])
        ng = fake_pptx(self.dir / "d.pptx", [["グラフ", "単位: 件"]], ["系列", "A", "21"])
        self.assertEqual(build.check_content_in_pptx(self.one_slide(slide), ng), ["s1: 「20」"])

    def test_unit_is_matched_by_display_string(self):
        # 「件」が「検査件数」に部分一致して見逃されないよう、表示文字列「単位: 件」で照合する
        slide = {"id": "s1", "title": "検査件数", "takeaway": "",
                 "chart": {"type": "bar", "unit": "件", "categories": ["A"], "series": [{"name": "系列", "values": [1]}]}}
        pptx = fake_pptx(self.dir / "e.pptx", [["検査件数"]], ["系列", "A", "1"])
        self.assertIn("s1: 「単位: 件」", build.check_content_in_pptx(self.one_slide(slide), pptx))

    def test_short_value_is_not_matched_by_substring(self):
        # 「1」が欠落しても「10」に部分一致して PASS してはならない
        slide = {"id": "s1", "title": "表", "takeaway": "",
                 "table": {"headers": ["項目", "値"], "rows": [["A", "1"], ["B", "10"]]}}
        ng = fake_pptx(self.dir / "g.pptx", [["表", "項目", "値", "A", "B", "10"]])
        self.assertEqual(build.check_content_in_pptx(self.one_slide(slide), ng), ["s1: 「1」"])
        ok = fake_pptx(self.dir / "h.pptx", [["表", "項目", "値", "A", "1", "B", "10"]])
        self.assertEqual(build.check_content_in_pptx(self.one_slide(slide), ok), [])

    def test_repeated_items_require_each_occurrence(self):
        slide = {"id": "s1", "title": "比較", "takeaway": "", "body": ["同じ文", "同じ文"],
                 "table": {"headers": ["観点", "結果"], "rows": [["X", "可"], ["Y", "可"]]}}
        ng = fake_pptx(self.dir / "i.pptx", [["比較", "同じ文", "観点", "結果", "X", "可", "Y"]])
        self.assertEqual(sorted(build.check_content_in_pptx(self.one_slide(slide), ng)), ["s1: 「可」", "s1: 「同じ文」"])

    def test_text_joined_with_label_is_accepted(self):
        slide = {"id": "s1", "title": "T", "takeaway": "", "source_refs": ["出典A", "出典B"]}
        pptx = fake_pptx(self.dir / "j.pptx", [["T", "出典: 出典A; 出典B"]])
        self.assertEqual(build.check_content_in_pptx(self.one_slide(slide), pptx), [])

    def test_slide_count_mismatch(self):
        pptx = fake_pptx(self.dir / "f.pptx", [["x"]])
        self.assertTrue(build.check_content_in_pptx(self.content, pptx)[0].startswith("PPTX のスライド数"))

    def test_cli_rejects_broken_yaml_without_traceback(self):
        broken = self.dir / "content.yaml"
        broken.write_text("slides: [unclosed\n", encoding="utf-8")
        r = subprocess.run([sys.executable, str(ROOT / "scripts/build.py"), "--content", str(broken),
                            "--design", str(DESIGN), "--out", str(self.dir / "o")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        self.assertNotIn("Traceback", r.stderr)

    def test_missing_command_is_build_error(self):
        with self.assertRaises(build.BuildError):
            build.run(["psl-no-such-command-xyz"])

    def test_font_checks(self):
        ja = {"name": "AAAAAA+NotoSansCJKjp-Regular", "type": "CID Type 0C", "embedded": True, "unicode": True}
        self.assertEqual(build.check_fonts([ja]), [])
        self.assertTrue(build.check_fonts([dict(ja, embedded=False)]))
        self.assertTrue(build.check_fonts([dict(ja, name="DejaVuSans")]))
        self.assertTrue(build.check_fonts([ja, dict(ja, name="T3", type="Type 3")]))


def png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()[16:24]
    return struct.unpack(">II", data)


@unittest.skipUnless(os.environ.get("PPTX_NODE_MODULES"), "Docker イメージ内でのみ実行")
class BuildIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name) / "deck"
        cls.result = subprocess.run([sys.executable, str(ROOT / "scripts/build.py"), "--content", str(CONTENT),
                                     "--design", str(DESIGN), "--out", str(cls.out)], capture_output=True, text=True)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_build_passes_with_all_artifacts(self):
        self.assertEqual(self.result.returncode, 0, self.result.stdout + self.result.stderr)
        for name in ("outline.json", "deck.pptx", "deck.pdf", "manifest.json", "index.html"):
            self.assertTrue((self.out / name).is_file(), name)

    def test_pdf_pages_and_pngs_match_slides(self):
        m = json.loads((self.out / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual((m["slides"], m["pdf_pages"]), (6, 6))
        pngs = sorted((self.out / "png").glob("*.png"))
        self.assertEqual([p.name for p in pngs], [f"{i:02d}-s00{i}.png" for i in range(1, 7)])
        for p in pngs:
            w, h = png_size(p)
            self.assertAlmostEqual(w / h, 16 / 9, places=1)

    def test_manifest_records_provenance_and_checks(self):
        m = json.loads((self.out / "manifest.json").read_text(encoding="utf-8"))
        lock = json.loads((ROOT / "upstream.lock.json").read_text(encoding="utf-8"))
        self.assertEqual(m["renderer"]["commit"], lock["commit"])
        self.assertEqual(m["inputs"]["content"]["sha256"], adapter.content_hash(adapter.load_and_validate(CONTENT, DESIGN)[0]))
        self.assertTrue(any("CJK" in f["name"] and f["embedded"] for f in m["fonts"]["pdf"]))
        c = m["checks"]
        self.assertEqual((c["content_missing_in_pptx"], c["content_missing_in_pdf"], c["font_errors"]), ([], [], []))
        self.assertEqual(c["non_content_text"], {})

    def test_gallery_lists_every_png(self):
        page = (self.out / "index.html").read_text(encoding="utf-8")
        for p in (self.out / "png").glob("*.png"):
            self.assertIn(f'src="png/{p.name}"', page)
        self.assertIn('lang="ja"', page)
        # リンク・画像の参照先がすべて実在する（ファイルを開くだけで閲覧できる静的ページ）
        import re
        for target in re.findall(r'(?:href|src)="([^"]+)"', page):
            self.assertTrue((self.out / target).is_file(), target)


if __name__ == "__main__":
    unittest.main()
