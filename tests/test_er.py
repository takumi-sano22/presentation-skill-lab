"""ER 図（ADR-0002 / #19）: v0.2 データ契約、ネイティブ配置、SVG 例外、PPTX 上の関係検査のテスト。"""
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

import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import adapter  # noqa: E402
import build  # noqa: E402
import er  # noqa: E402
import qa  # noqa: E402
import validate  # noqa: E402

DECK = ROOT / "examples/bench-er"
OUTLINE_SCHEMA = json.loads((ROOT / "schemas/outline-adapter.schema.json").read_text(encoding="utf-8"))
V01_DECKS = ["technical-architecture", "bench-architecture", "bench-table-chart", "bench-dense-tech",
             "asset-illustration", "gate4-chatgpt-origin"]


def load(deck: Path = DECK) -> tuple[dict, dict]:
    return (yaml.safe_load((deck / "content.yaml").read_text(encoding="utf-8")),
            yaml.safe_load((deck / "design.yaml").read_text(encoding="utf-8")))


def slide(content: dict, sid: str) -> dict:
    return next(s for s in content["slides"] if s["id"] == sid)


def contract_errors(content: dict, design: dict, deck: Path = DECK) -> list[str]:
    return (validate.schema_errors(content, Path("content")) + validate.schema_errors(design, Path("design"))
            + validate.cross_validate(content, design, deck))


class ContractTests(unittest.TestCase):
    """schema v0.2 は v0.1 の互換追加。0.1 の入力は従来どおり受理し、0.2 の項目の整合性を相互検証する。"""

    def test_v01_inputs_remain_valid(self):
        for deck in V01_DECKS:
            with self.subTest(deck):
                c, d = load(ROOT / "examples" / deck)
                self.assertEqual(c["schema_version"], "0.1")
                self.assertEqual(contract_errors(c, d, ROOT / "examples" / deck), [])

    def test_v02_er_sample_is_valid(self):
        c, d = load()
        self.assertEqual(contract_errors(c, d), [])

    def test_v02_fields_require_v02(self):
        c, d = load()
        c["schema_version"] = "0.1"
        self.assertTrue(any("schema_version: '0.2'" in e for e in contract_errors(c, d)))

    def test_attributes_only_on_er_slides(self):
        c, d = load()
        slide(c, "e402")["type"] = "architecture"
        d["overrides"]["e402"] = {"layout": "architecture"}
        self.assertTrue(any("type: er" in e for e in contract_errors(c, d)))

    def test_fk_target_must_exist(self):
        c, d = load()
        slide(c, "e402")["diagram"]["nodes"][0]["attributes"][2]["fk"] = "product.存在しない列"
        self.assertTrue(any("参照先がありません" in e for e in contract_errors(c, d)))

    def test_reversed_relationship_is_rejected(self):
        # FK を持つ側（item）から参照先（product）への関係が無く、逆向きだけがある
        c, d = load()
        edge = slide(c, "e402")["diagram"]["edges"][1]
        edge["from"], edge["to"] = edge["to"], edge["from"]
        self.assertTrue(any("from が外部キーを持つ側" in e for e in contract_errors(c, d)))

    def test_bad_cardinality_and_duplicate_ids(self):
        c, d = load()
        edges = slide(c, "e402")["diagram"]["edges"]
        edges[0]["cardinality"]["from"] = "many"
        edges[1]["id"] = edges[0]["id"]
        errors = contract_errors(c, d)
        self.assertTrue(any("cardinality" in e for e in errors))
        self.assertTrue(any("関係 ID が重複" in e for e in errors))

    def test_duplicate_attribute_names(self):
        c, d = load()
        attrs = slide(c, "e402")["diagram"]["nodes"][1]["attributes"]
        attrs.append(copy.deepcopy(attrs[0]))
        self.assertTrue(any("属性名が重複" in e for e in contract_errors(c, d)))


class LayoutTests(unittest.TestCase):
    def setUp(self):
        self.content, self.design = load()
        self.small = slide(self.content, "e402")["diagram"]
        self.dense = slide(self.content, "e403")["diagram"]

    def test_attribute_text(self):
        self.assertEqual(er.attribute_text({"name": "受注ID", "type": "INT", "pk": True, "fk": "orders.受注ID"}),
                         "PK/FK 受注ID : INT")
        self.assertEqual(er.attribute_text({"name": "地域", "type": "VARCHAR(20)", "nullable": True}), "地域 : VARCHAR(20) NULL可")
        self.assertEqual(er.attribute_text({"name": "氏名", "nullable": False}), "氏名 NOT NULL")
        self.assertEqual(er.attribute_text({"name": "ID", "pk": True, "nullable": False}), "PK ID")

    def test_small_er_is_native_readable_and_deterministic(self):
        lay = er.layout(self.small)
        self.assertEqual(lay, er.layout(copy.deepcopy(self.small)))
        self.assertGreaterEqual(lay["attr_font_pt"], 9.0)
        self.assertEqual(lay["metrics"]["crossings"], 0)
        boxes = er.entity_boxes(lay)
        ids = list(boxes)
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                self.assertFalse(boxes[a].intersects(boxes[b]), (a, b))
        # 複合主キー: 受注明細の2行が PK
        item = next(en for en in lay["entities"] if en["id"] == "item")
        self.assertEqual([r["pk"] for r in item["rows"]], [True, True, False, False])
        # 関係線の始点は FK 行の高さ（item.商品ID → product）
        edge = next(e for e in lay["edges"] if e["to"] == "product")
        row = item["rows"][2]
        self.assertTrue(row["y"] <= edge["points"][0][1] <= row["y"] + row["h"])
        self.assertEqual(edge["cardinality"], {"from": "0..N", "to": "1"})

    def test_dense_er_fails_native_with_reproducible_reason(self):
        with self.assertRaises(er.ERLayoutError) as ctx:
            er.layout(self.dense)
        self.assertIn("9pt", ctx.exception.reason)
        self.assertEqual(ctx.exception.metrics["entities"], 12)

    def test_svg_contains_all_texts_and_relationships(self):
        svg, natural = er.to_svg(self.dense, self.design["theme"]["colors"])
        self.assertEqual(svg, er.to_svg(copy.deepcopy(self.dense), self.design["theme"]["colors"])[0])
        self.assertEqual(sorted(er.svg_texts(svg)), sorted(er.expected_texts(self.dense)))
        self.assertEqual(er.svg_edges(svg), [(e["from"], e["to"]) for e in self.dense["edges"]])
        self.assertNotIn("http", svg.replace("http://www.w3.org/2000/svg", ""))  # 外部参照なし

    def test_v01_er_without_attributes_is_native(self):
        c, _ = load(ROOT / "examples/bench-dense-tech")
        lay = er.layout(c["slides"][1]["diagram"])
        # 属性の無い v0.1 の ER は説明（description）を1行で表示する
        self.assertEqual([r["text"] for en in lay["entities"] for r in en["rows"]][0], "顧客ID・氏名・地域")


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.content, self.design = load()

    def convert(self, mutate=None):
        c, d = copy.deepcopy(self.content), copy.deepcopy(self.design)
        if mutate:
            mutate(c, d)
        return adapter.convert(c, d)

    def test_policies(self):
        outline = self.convert()
        Draft202012Validator(OUTLINE_SCHEMA).validate(outline)
        e402, e403 = outline["slides"][1]["psl"], outline["slides"][2]["psl"]
        self.assertEqual((e402["er_policy"], "er_layout" in e402, "fallback" in e402), ("native_only", True, False))
        self.assertEqual((e403["er_policy"], "er_svg" in e403), ("auto", True))
        fb = e403["fallback"]
        self.assertEqual(fb["mode"], "svg")
        self.assertIn("横幅が不足", fb["reason"])
        self.assertEqual(fb["source_sha256"], adapter.er_source_hash(slide(self.content, "e403")["diagram"]))
        self.assertEqual(fb["svg_sha256"], adapter.sha256_text(e403["er_svg"]["svg"]))
        self.assertIn("個別に編集できない", fb["editable"])
        self.assertLess(fb["effective_attr_font_pt"], 9)

    def test_native_only_fails_instead_of_silent_svg(self):
        def force(_, d):
            d["overrides"]["e403"]["diagram_mode"] = "native"
        with self.assertRaisesRegex(adapter.UnsupportedContent, "native_only"):
            self.convert(force)

    def test_svg_policy_is_explicit(self):
        def force(_, d):
            d["overrides"]["e402"]["diagram_mode"] = "svg"
        fb = self.convert(force)["slides"][1]["psl"]["fallback"]
        self.assertIn("diagram_mode: svg", fb["reason"])

    def test_image_mode_is_unsupported(self):
        def force(_, d):
            d["overrides"]["e402"]["diagram_mode"] = "image"
        with self.assertRaises(adapter.UnsupportedContent):
            self.convert(force)

    def test_semantic_items_cover_attributes_and_cardinality(self):
        items = adapter.semantic_items(self.content)
        self.assertIn(("e402", "diagram.edge", "item->orders:明細:relationship:id=r-item-orders:card=1..N/1"), items)
        attrs = [v for sid, k, v in items if sid == "e402" and k == "diagram.node.attribute"]
        self.assertEqual(len(attrs), 16)
        self.assertIn('"fk": "orders.受注ID"', attrs[0])

    def test_tampered_layout_or_svg_is_detected(self):
        outline = self.convert()
        outline["slides"][1]["psl"]["er_layout"]["entities"][0]["rows"][0]["text"] = "PK 改変"
        with self.assertRaises(adapter.ContentMismatch):
            adapter.verify_roundtrip(self.content, outline)
        outline = self.convert()
        outline["slides"][2]["psl"]["er_svg"]["svg"] = outline["slides"][2]["psl"]["er_svg"]["svg"].replace("請求額", "金額")
        with self.assertRaises(adapter.ContentMismatch):
            adapter.verify_roundtrip(self.content, outline)

    def test_v01_semantic_items_have_no_v02_kinds(self):
        # 0.1 の入力の意味項目は v0.2 対応後も同じ形（edge の値に id/card を付けない）
        c, _ = load(ROOT / "examples/technical-architecture")
        items = adapter.semantic_items(c)
        self.assertFalse(any(k == "diagram.node.attribute" for _, k, _ in items))
        self.assertIn(("s003", "diagram.edge", "user->agent:質問:data"), items)


def mutate(src: Path, dst: Path, part: str, func) -> Path:
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename == part:
                data = func(data.decode("utf-8")).encode("utf-8")
            zout.writestr(info, data)
    return dst


@unittest.skipUnless(os.environ.get("PPTX_NODE_MODULES"), "Docker イメージ内でのみ実行")
class BuiltDeckTests(unittest.TestCase):
    """実際にビルドした PPTX で、ネイティブ ER の編集可能性と、壊した場合の検出を確かめる。"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name) / "deck"
        r = subprocess.run([sys.executable, str(ROOT / "scripts/build.py"), "--content", str(DECK / "content.yaml"),
                            "--design", str(DECK / "design.yaml"), "--out", str(cls.out)], capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr
        cls.content, _ = adapter.load_and_validate(DECK / "content.yaml", DECK / "design.yaml")
        cls.outline = json.loads((cls.out / "outline.json").read_text(encoding="utf-8"))
        cls.pptx = cls.out / "deck.pptx"
        cls.manifest = json.loads((cls.out / "manifest.json").read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def broken(self, name, part, func):
        return mutate(self.pptx, Path(self.tmp.name) / f"{name}.pptx", part, func)

    def test_manifest_records_native_and_svg_exception(self):
        checks = self.manifest["checks"]
        self.assertEqual((checks["content_missing_in_pptx"], checks["content_missing_in_pdf"], checks["diagram_errors"],
                          checks["qa"]["errors"]), ([], [], [], []))
        self.assertEqual(self.manifest["fallbacks"]["e403"]["mode"], "svg")
        self.assertNotIn("e402", self.manifest["fallbacks"])
        self.assertTrue(any(w.startswith("e403:") for w in checks["er_fallback_warnings"]))

    def test_native_er_objects_are_editable_shapes(self):
        with zipfile.ZipFile(self.pptx) as z:
            xml = z.read("ppt/slides/slide2.xml").decode("utf-8")
        self.assertEqual(xml.count("<p:pic>"), 0)  # 画像化していない
        for name in ("er-entity:item", "er-attr:item:0", "er-attr:item:1", "er-card:0:from", "er-label:0"):
            block = re.search(rf'<p:sp>(?:(?!</p:sp>).)*?name="{re.escape(name)}".*?</p:sp>', xml, re.S)
            self.assertIsNotNone(block, name)
            self.assertIn("<a:t>", block.group(0))  # 文字はテキストとして編集できる
        self.assertEqual(len(re.findall(r'name="er-edge:', xml)), sum(len(e["points"]) - 1
                         for e in self.outline["slides"][1]["psl"]["er_layout"]["edges"]))

    def test_svg_exception_is_a_single_image_with_matching_source(self):
        with zipfile.ZipFile(self.pptx) as z:
            xml = z.read("ppt/slides/slide3.xml").decode("utf-8")
        self.assertEqual(xml.count("<p:pic>"), 1)
        self.assertIn('name="er-svg:e403"', xml)
        self.assertIn(self.manifest["fallbacks"]["e403"]["svg_sha256"], build.svg_media(self.pptx))

    def test_reversed_relationship_is_detected(self):
        # 関係線の名前の from/to を入れ替える（線の向き＝どちらが外部キーを持つかが反転）
        pptx = self.broken("rev", "ppt/slides/slide2.xml",
                           lambda x: x.replace("er-edge:1:item-&gt;product", "er-edge:1:product-&gt;item"))
        errors = build.check_er_in_pptx(self.content, self.outline, pptx)
        self.assertTrue(any("関係 er-edge:1:item->product の線がありません" in e for e in errors), errors)
        self.assertTrue(any("ER 定義に無い図形" in e for e in errors), errors)

    def test_wrong_endpoint_is_detected(self):
        # 関係 item->product の最後の線分を、別のエンティティ（顧客）の方へずらす
        lay = self.outline["slides"][1]["psl"]["er_layout"]
        edge = lay["edges"][1]
        last = len(edge["points"]) - 2

        def move(xml):
            return re.sub(rf'(name="er-edge:1:item-&gt;product#{last}".*?<a:off x=")(\d+)(" y=")(\d+)',
                          lambda m: m.group(1) + m.group(2) + m.group(3) + str(int(m.group(4)) - 600000), xml, count=1, flags=re.S)
        errors = build.check_er_in_pptx(self.content, self.outline, self.broken("end", "ppt/slides/slide2.xml", move))
        self.assertTrue(any("item->product" in e and ("終点" in e or "途切れ" in e) for e in errors), errors)

    def test_attribute_text_change_or_move_is_detected(self):
        # 属性行（er-attr:item:1「PK 明細番号 : INT」）の文字だけを書き換える（要点の同じ語は変えない）
        pptx = self.broken("attr", "ppt/slides/slide2.xml", lambda x: re.sub(
            r'(name="er-attr:item:1"(?:(?!</p:sp>).)*?)明細番号', r"\g<1>行番号", x, count=1, flags=re.S))
        self.assertTrue(any("属性行" in e for e in build.check_er_in_pptx(self.content, self.outline, pptx)))
        self.assertTrue(build.check_content_in_pptx(self.content, pptx, self.outline))

        def move_row(xml):
            return re.sub(r'(name="er-attr:item:3".*?<a:off x=")(\d+)', lambda m: m.group(1) + str(int(9.0 * 914400)),
                          xml, count=1, flags=re.S)
        errors = build.check_er_in_pptx(self.content, self.outline, self.broken("row", "ppt/slides/slide2.xml", move_row))
        self.assertTrue(any("枠の外" in e for e in errors), errors)

    def test_missing_cardinality_is_detected(self):
        pptx = self.broken("card", "ppt/slides/slide2.xml",
                           lambda x: re.sub(r'(name="er-card:3:to".*?<a:t>)0\.\.1(</a:t>)', r"\g<1>1\g<2>", x, count=1, flags=re.S))
        errors = build.check_er_in_pptx(self.content, self.outline, pptx)
        self.assertTrue(any("多重度「0..1」" in e for e in errors), errors)

    def test_tampered_svg_is_detected(self):
        with zipfile.ZipFile(self.pptx) as z:
            svg_name = next(n for n in z.namelist() if n.endswith(".svg"))
        pptx = self.broken("svg", svg_name, lambda x: x.replace("請求額", "金額"))
        errors = build.check_er_in_pptx(self.content, self.outline, pptx)
        self.assertTrue(any("SVG" in e for e in errors), errors)

    def test_er_line_through_label_is_qa_error(self):
        # 関係名の枠を、別の関係の線分の上へ動かす
        lay = self.outline["slides"][1]["psl"]["er_layout"]
        (x1, y1), (x2, y2) = lay["edges"][0]["points"][:2]
        box = lay["edges"][2]["label_box"]
        x, y = (x1 + x2) / 2 - box["w"] / 2, y1 - box["h"] / 2

        def move(xml):
            return re.sub(r'(name="er-label:2".*?<a:off x=")\d+(" y=")\d+',
                          lambda m: m.group(1) + str(int(x * 914400)) + m.group(2) + str(int(y * 914400)), xml, count=1, flags=re.S)
        pptx = self.broken("cross", "ppt/slides/slide2.xml", move)
        result = qa.run_qa(self.content, self.outline, pptx, DECK)
        self.assertIn("connector-crossing", {e["check"] for e in result["errors"]})

    def test_unregistered_picture_on_er_slide_is_flagged(self):
        # SVG 例外の名前でない画像は、ER スライドでも画像化として FAIL
        pptx = self.broken("pic", "ppt/slides/slide3.xml", lambda x: x.replace('name="er-svg:e403"', 'name="Picture 9"'))
        result = qa.run_qa(self.content, self.outline, pptx, DECK)
        self.assertIn("rasterized-diagram", {e["check"] for e in result["errors"]})


if __name__ == "__main__":
    unittest.main()
