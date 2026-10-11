"""Gate 4 の役割分離（内容担当とデザイン担当）が守られていることを確認する薄いテスト。

描画品質は CI の build / QA ステップで確認する。ここでは「相手の担当ファイルを黙って変えていない」ことだけを見る。
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
G4B = ROOT / "examples/gate4-chatgpt-origin"
# ChatGPT が作成したコミット 1a88c86 / 3d45aa7 時点の content.yaml 原文の SHA-256。
# Claude Code 側の作業でこの値が変わったら、内容を黙って変更したことになる。
G4B_CONTENT_SHA256 = "9bd19d849fa0db9ce9881f15d80948284266d152eee61826b4415ad49f8abcb8"


class Gate4BContractTests(unittest.TestCase):
    def test_chatgpt_content_is_byte_identical(self):
        digest = hashlib.sha256((G4B / "content.yaml").read_bytes()).hexdigest()
        self.assertEqual(digest, G4B_CONTENT_SHA256, "ChatGPT 起点の content.yaml が変更されている")

    def test_design_covers_same_deck_and_slides(self):
        content = yaml.safe_load((G4B / "content.yaml").read_text(encoding="utf-8"))
        design = yaml.safe_load((G4B / "design.yaml").read_text(encoding="utf-8"))
        self.assertEqual(design["deck_id"], content["deck_id"])
        slide_ids = {s["id"] for s in content["slides"]}
        # デザイン側が存在しない Slide ID を参照すると、内容との対応が崩れる
        self.assertLessEqual(set(design["overrides"]), slide_ids)

    def test_validate_passes(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts/validate.py"),
             "--content", str(G4B / "content.yaml"), "--design", str(G4B / "design.yaml"),
             "--public-repo-check"],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
