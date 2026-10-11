"""画像アセット manifest 検査と、画像スライド・差し替えのテスト。"""
from __future__ import annotations

import copy
import hashlib
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import adapter  # noqa: E402
import assets  # noqa: E402

DECK = ROOT / "examples/asset-illustration"


def make_png(width: int, height: int, color_type: int = 2) -> bytes:
    """最小の PNG（単色）。color_type 2=RGB、6=RGBA。"""
    channels = {2: 3, 6: 4}[color_type]
    raw = b"".join(b"\x00" + b"\x80" * (width * channels) for _ in range(height))
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def make_jpeg_header(width: int, height: int, components: int) -> bytes:
    """寸法・成分数だけを持つ JPEG 風バイト列（SOF0 まで）。"""
    sof = struct.pack(">BHHB", 8, height, width, components) + b"\x01\x11\x00" * components
    return b"\xff\xd8" + b"\xff\xc0" + struct.pack(">H", len(sof) + 2) + sof + b"\xff\xd9"


class AssetCheckTests(unittest.TestCase):
    def setUp(self):
        # サブテストごとに setUp を呼び直すため、前の一時ディレクトリを片付ける
        if getattr(self, "tmp", None):
            self.tmp.cleanup()
        self.tmp = tempfile.TemporaryDirectory()
        self.deck = Path(self.tmp.name) / "deck"
        shutil.copytree(DECK, self.deck)
        self.manifest = yaml.safe_load((self.deck / assets.MANIFEST).read_text(encoding="utf-8"))

    def tearDown(self):
        self.tmp.cleanup()

    def save(self):
        (self.deck / assets.MANIFEST).write_text(yaml.safe_dump(self.manifest, allow_unicode=True), encoding="utf-8")

    def add(self, name: str, data: bytes, **fields) -> dict:
        path = self.deck / "assets" / name
        path.write_bytes(data)
        entry = {"path": f"assets/{name}", "sha256": hashlib.sha256(data).hexdigest(), "transparent": False,
                 "alt": "テスト画像", "contains_text": False, "license": "MIT", "updated": "2026-10-11",
                 "origin": {"type": "authored", "author": "テスト"}, **fields}
        self.manifest["assets"].append(entry)
        self.save()
        return entry

    def errors(self) -> list[str]:
        return assets.check_deck(self.deck)

    def assertError(self, fragment: str):
        errors = self.errors()
        self.assertTrue(any(fragment in e for e in errors), errors)

    def test_sample_passes(self):
        self.assertEqual(self.errors(), [])

    def test_unregistered_file_is_unknown_rights(self):
        (self.deck / "assets" / "found.png").write_bytes(make_png(1600, 900))
        self.assertError("manifest に登録されていないファイル")

    def test_swapped_image_without_manifest_update(self):
        (self.deck / "assets/boundary-illustration.svg").write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900"><rect width="10" height="10"/></svg>',
            encoding="utf-8")
        self.assertError("sha256 が manifest と一致しません")

    def test_license_and_provenance_rules(self):
        cases = [
            ({"license": "unknown"}, "自動許可の対象外"),
            ({"license": "CC-BY-4.0"}, "attribution"),
            ({"origin": {"type": "third_party"}, "attribution": "A"}, "source_url"),
            ({"origin": {"type": "generated", "tool": "ChatGPT 画像生成"}}, "prompt_file"),
            ({"origin": {"type": "authored", "author": "x", "source_file": "assets/src.html"}}, "origin.source_file"),
        ]
        for i, (fields, fragment) in enumerate(cases):
            with self.subTest(fragment):
                self.setUp()
                self.add(f"x{i}.png", make_png(1600, 900), media_type="image/png", width=1600, height=900, **fields)
                self.assertError(fragment)

    def test_generated_image_with_prompt_passes(self):
        (self.deck / "assets/prompts").mkdir()
        (self.deck / "assets/prompts/hero.md").write_text("生成指示（人がチャットで明示的に依頼）", encoding="utf-8")
        self.add("hero.png", make_png(1600, 900), media_type="image/png", width=1600, height=900,
                 origin={"type": "generated", "tool": "ChatGPT 画像生成", "prompt_file": "assets/prompts/hero.md",
                         "asset_id": "file-xyz"})
        self.assertEqual(self.errors(), [])

    def test_raster_quality_rules(self):
        cases = [
            ("small.png", make_png(800, 450), {"width": 800, "height": 450}, "解像度不足"),
            ("alpha.png", make_png(1600, 900, 6), {"width": 1600, "height": 900}, "透過"),
            ("size.png", make_png(1600, 900), {"width": 1600, "height": 1000}, "寸法"),
        ]
        for name, data, dims, fragment in cases:
            with self.subTest(fragment):
                self.setUp()
                self.add(name, data, media_type="image/png", **dims)
                self.assertError(fragment)

    def test_extension_must_match_media_type(self):
        self.add("wrong.svg", make_png(1600, 900), media_type="image/png", width=1600, height=900)
        self.assertError("拡張子")

    def test_broken_png_is_rejected(self):
        good = make_png(1600, 900)
        cases = {"切断（IHDR まで）": good[:33], "CRC 破損": good[:29] + bytes([good[29] ^ 0xFF]) + good[30:],
                 "IEND なし": good[:-12]}
        for i, (name, data) in enumerate(cases.items()):
            with self.subTest(name):
                self.setUp()
                self.add(f"b{i}.png", data, media_type="image/png", width=1600, height=900)
                self.assertError("解析できません")

    def test_svg_size_prefers_width_height_over_viewbox(self):
        svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900" viewBox="0 0 100 100"><rect width="100" height="100" fill="#fff"/></svg>'
        self.assertEqual(assets.svg_info(svg)[:2], (1600, 900))
        self.assertEqual(assets.svg_info(b'<svg xmlns="http://www.w3.org/2000/svg" width="100%" viewBox="0 0 400 300"/>')[:2], (400, 300))
        self.assertEqual(assets.svg_info(b'<svg xmlns="http://www.w3.org/2000/svg" width="4in" height="2.25in"/>')[:2], (384, 216))

    def test_cmyk_jpeg_is_rejected(self):
        self.add("p.jpg", make_jpeg_header(1600, 900, 4), media_type="image/jpeg", width=1600, height=900)
        self.assertError("CMYK")

    def test_svg_rules(self):
        cases = [
            ('<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900"><text>売上 120</text></svg>', "文字"),
            ('<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="1600" height="900">'
             '<image xlink:href="https://example.com/a.png" width="10" height="10"/></svg>', "外部参照"),
            ('<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900"><script>x</script></svg>', "<script>"),
        ]
        for i, (svg, fragment) in enumerate(cases):
            with self.subTest(fragment):
                self.setUp()
                self.add(f"s{i}.svg", svg.encode(), media_type="image/svg+xml", width=1600, height=900)
                self.assertError(fragment)

    def test_svg_internal_references_are_allowed(self):
        svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900"><defs><linearGradient id="g"/>'
               '<clipPath id="c"><rect width="9" height="9"/></clipPath></defs>'
               '<rect style="fill: url(\'#g\')" clip-path="url(&quot;#c&quot;)" width="10" height="10"/>'
               '<rect style="fill:url(#g)" width="5" height="5"/></svg>')
        self.add("ok.svg", svg.encode(), media_type="image/svg+xml", width=1600, height=900, transparent=True)
        self.assertEqual(self.errors(), [])
        self.setUp()
        bad = '<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900"><rect style="fill:url(\'https://x/a.svg#g\')"/></svg>'
        self.add("bad.svg", bad.encode(), media_type="image/svg+xml", width=1600, height=900)
        self.assertError("外部参照")

    def test_svg_presentation_attribute_urls_are_checked(self):
        for i, attr in enumerate(('fill="url(https://example.com/a.svg#g)"', 'filter="url(\'http://x/f.svg#f\')"')):
            with self.subTest(attr):
                self.setUp()
                svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900"><rect {attr} width="9" height="9"/></svg>'
                self.add(f"p{i}.svg", svg.encode(), media_type="image/svg+xml", width=1600, height=900)
                self.assertError("外部参照")

    def test_svg_transparency_is_judged_from_content(self):
        no_bg = b'<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900"><circle cx="5" cy="5" r="4"/></svg>'
        self.add("nobg.svg", no_bg, media_type="image/svg+xml", width=1600, height=900, transparent=False)
        self.assertError("透過")
        self.setUp()
        self.add("nobg2.svg", no_bg, media_type="image/svg+xml", width=1600, height=900, transparent=True)
        self.assertEqual(self.errors(), [])
        self.setUp()
        half = (b'<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900">'
                b'<rect width="100%" height="100%" fill="#fff" fill-opacity="0.5"/></svg>')
        self.add("half.svg", half, media_type="image/svg+xml", width=1600, height=900, transparent=False)
        self.assertError("透過")

    def test_paths_outside_assets_are_rejected(self):
        (self.deck / "outside.png").write_bytes(make_png(1600, 900))
        self.manifest["assets"].append({"path": "assets/../outside.png", "sha256": "0" * 64, "media_type": "image/png",
                                        "width": 1600, "height": 900, "transparent": False, "alt": "x",
                                        "contains_text": False, "license": "MIT", "updated": "2026-10-11",
                                        "origin": {"type": "authored", "author": "x"}})
        self.save()
        self.assertTrue(any("manifest.yaml" in e for e in self.errors()))

    def test_truncated_jpeg_is_reported_not_crashed(self):
        self.add("cut.jpg", make_jpeg_header(1600, 900, 3)[:9], media_type="image/jpeg", width=1600, height=900)
        self.assertError("解析できません")

    def test_text_in_image_requires_reason(self):
        self.add("t.svg", b'<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900"><text>A</text></svg>',
                 media_type="image/svg+xml", width=1600, height=900, contains_text=True)
        self.assertError("text_reason")


class IllustrationAdapterTests(unittest.TestCase):
    def setUp(self):
        self.content, self.design = adapter.load_and_validate(DECK / "content.yaml", DECK / "design.yaml")
        self.out = ROOT / "build" / "test-outline"

    def convert(self, content=None, design=None, base=DECK):
        return adapter.convert(content or self.content, design or self.design, base, self.out)

    def test_contain_keeps_aspect_ratio_inside_area(self):
        img = self.convert()["slides"][1]["psl"]["image"]
        self.assertAlmostEqual(img["w"] / img["h"], 1600 / 900, places=3)
        ax, ay, aw, ah = adapter.IMAGE_AREA
        self.assertTrue(ax <= img["x"] and img["x"] + img["w"] <= ax + aw + 1e-6 and img["h"] <= ah + 1e-6)
        self.assertEqual((self.out / img["path"]).resolve(), (DECK / "assets/boundary-illustration.svg").resolve())

    def test_cover_fills_area(self):
        design = copy.deepcopy(self.design)
        design["overrides"]["a002"]["asset_fit"] = "cover"
        img = self.convert(design=design)["slides"][1]["psl"]["image"]
        self.assertEqual((img["x"], img["y"], img["w"], img["h"]), adapter.IMAGE_AREA)
        # 切り抜きの基準寸法は画像本来の比率で、領域を覆う
        self.assertAlmostEqual(img["src_w"] / img["src_h"], 1600 / 900, places=3)
        self.assertTrue(img["src_w"] >= img["w"] - 1e-6 and img["src_h"] >= img["h"] - 1e-6)

    def test_unsupported_image_cases(self):
        no_body = copy.deepcopy(self.content)
        no_body["slides"][1]["body"] = ["本文"]
        fit_elsewhere = copy.deepcopy(self.design)
        fit_elsewhere["overrides"]["a003"] = {"layout": "claim", "asset_fit": "cover"}
        for name, content, design in (("本文つき画像", no_body, None), ("画像以外に asset_fit", None, fit_elsewhere)):
            with self.subTest(name), self.assertRaises(adapter.UnsupportedContent):
                self.convert(content, design)

    def test_unregistered_asset_fails(self):
        with tempfile.TemporaryDirectory() as d:
            deck = Path(d) / "deck"
            shutil.copytree(DECK, deck)
            (deck / assets.MANIFEST).write_text("schema_version: '0.1'\nassets: []\n", encoding="utf-8")
            with self.assertRaises(adapter.UnsupportedContent):
                self.convert(base=deck)

    def test_image_swap_does_not_change_content(self):
        # 画像を差し替えて manifest を更新しても、content の hash・意味項目は変わらない（#7 DoD）
        with tempfile.TemporaryDirectory() as d:
            deck = Path(d) / "deck"
            shutil.copytree(DECK, deck)
            new_svg = (b'<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900">'
                       b'<rect width="1600" height="900" fill="#ffffff"/><circle cx="800" cy="450" r="300"/></svg>')
            (deck / "assets/boundary-illustration.svg").write_bytes(new_svg)
            manifest = yaml.safe_load((deck / assets.MANIFEST).read_text(encoding="utf-8"))
            manifest["assets"][0]["sha256"] = hashlib.sha256(new_svg).hexdigest()
            (deck / assets.MANIFEST).write_text(yaml.safe_dump(manifest, allow_unicode=True), encoding="utf-8")
            self.assertEqual(assets.check_deck(deck), [])
            before, after = self.convert(), self.convert(base=deck)
            self.assertEqual(before["psl"]["content_sha256"], after["psl"]["content_sha256"])
            self.assertEqual(adapter.outline_semantic_items(before), adapter.outline_semantic_items(after))
            self.assertNotEqual(before["slides"][1]["psl"]["image"]["sha256"], after["slides"][1]["psl"]["image"]["sha256"])


@unittest.skipUnless(os.environ.get("PPTX_NODE_MODULES"), "Docker イメージ内でのみ実行")
class AssetBuildTests(unittest.TestCase):
    def build(self, deck: Path, out: Path) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(ROOT / "scripts/build.py"), "--content", str(deck / "content.yaml"),
                               "--design", str(deck / "design.yaml"), "--out", str(out)], capture_output=True, text=True)

    def test_build_places_image_with_valid_png_fallback(self):
        with tempfile.TemporaryDirectory() as d:
            r = self.build(DECK, Path(d) / "out")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            m = yaml.safe_load((Path(d) / "out/manifest.json").read_text(encoding="utf-8"))
            self.assertEqual([a["path"] for a in m["assets"]], ["assets/boundary-illustration.svg"])
            self.assertEqual(len(m["svg_png_fallbacks_fixed"]), 1)
            self.assertEqual(m["checks"]["media_errors"], [])

    def test_cover_crops_instead_of_stretching(self):
        import re
        import zipfile
        with tempfile.TemporaryDirectory() as d:
            deck = Path(d) / "deck"
            shutil.copytree(DECK, deck)
            design = yaml.safe_load((deck / "design.yaml").read_text(encoding="utf-8"))
            design["overrides"]["a002"]["asset_fit"] = "cover"
            (deck / "design.yaml").write_text(yaml.safe_dump(design, allow_unicode=True), encoding="utf-8")
            r = self.build(deck, Path(d) / "out")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            xml = zipfile.ZipFile(Path(d) / "out/deck.pptx").read("ppt/slides/slide2.xml").decode("utf-8")
            pic = re.search(r"<p:pic>.*?</p:pic>", xml, re.S).group(0)
            # 16:9 の画像を 9.0x3.6 の枠へ cover → 上下を切り抜く（t/b > 0）。枠は領域いっぱい
            crop = dict(re.findall(r'(\w)="(\d+)"', re.search(r"<a:srcRect[^>]*>", pic).group(0)))
            self.assertGreater(int(crop["t"]), 0)
            self.assertEqual(int(crop["t"]), int(crop["b"]))
            ext = re.search(r'<a:ext cx="(\d+)" cy="(\d+)"/>', pic).groups()
            self.assertEqual(tuple(round(int(v) / 914400, 2) for v in ext), (9.0, 3.6))

    def test_build_stops_on_unknown_rights(self):
        with tempfile.TemporaryDirectory() as d:
            deck = Path(d) / "deck"
            shutil.copytree(DECK, deck)
            (deck / "assets/stray.png").write_bytes(make_png(1600, 900))
            r = self.build(deck, Path(d) / "out")
            self.assertEqual(r.returncode, 1)
            self.assertIn("出自・権利が不明", r.stderr)


if __name__ == "__main__":
    unittest.main()
