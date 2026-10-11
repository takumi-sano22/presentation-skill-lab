"""契約検証の最小限の回帰テスト。レンダリング品質の保証ではない。"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONTENT = ROOT / "examples/technical-architecture/content.yaml"
DESIGN = ROOT / "examples/technical-architecture/design.yaml"


class ValidatorTests(unittest.TestCase):
    def _run(self, mutate=None, *, public=True):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            c = yaml.safe_load(CONTENT.read_text(encoding="utf-8"))
            design = yaml.safe_load(DESIGN.read_text(encoding="utf-8"))
            if mutate:
                mutate(c, design)
            cpath, dpath = root / "content.yaml", root / "design.yaml"
            cpath.write_text(yaml.safe_dump(c, allow_unicode=True), encoding="utf-8")
            dpath.write_text(yaml.safe_dump(design, allow_unicode=True), encoding="utf-8")
            command = [sys.executable, str(ROOT / "scripts/validate.py"), "--content", str(cpath), "--design", str(dpath)]
            if public:
                command.append("--public-repo-check")
            return subprocess.run(command, capture_output=True, text=True, check=False)

    def test_valid_sample(self):
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("6 スライド", result.stdout)

    def test_unknown_edge_fails(self):
        def mutate(c, _):
            c["slides"][2]["diagram"]["edges"][0]["to"] = "missing_node"
        result = self._run(mutate)
        self.assertEqual(result.returncode, 1)
        self.assertIn("接続先がありません", result.stdout)

    def test_unknown_design_id_fails(self):
        def mutate(_, d):
            d["overrides"]["s999"] = {"layout": "claim"}
        result = self._run(mutate)
        self.assertEqual(result.returncode, 1)
        self.assertIn("s999", result.stdout)

    def test_sensitive_example_fails_public_guard(self):
        def mutate(c, _):
            c["metadata"]["classification"] = "confidential"
            c["metadata"]["synthetic"] = False
        result = self._run(mutate)
        self.assertEqual(result.returncode, 1)
        self.assertIn("公開用サンプル", result.stdout)


if __name__ == "__main__":
    unittest.main()
