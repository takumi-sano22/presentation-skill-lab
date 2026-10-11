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

    def test_inline_yaml_comment_in_text_is_warned(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "content.yaml"
            path.write_text("notes: 詳細は Issue #19 で検討\nquoted: '詳細は Issue #19'\nlayout: cover  # 設定の説明\n# 行コメント\n",
                            encoding="utf-8")
            sys.path.insert(0, str(ROOT / "scripts"))
            import validate
            warnings = validate.yaml_comment_warnings(path)
            self.assertEqual(len([w for w in warnings if ":1:" in w]), 1)
            self.assertFalse(any(":2:" in w or ":4:" in w for w in warnings))

    def test_inline_hash_in_text_fails_public_check_only(self):
        # #24: 引用符なしの「Issue #19」は公開リポジトリ検査で FAIL、通常は警告
        def mutate(c, _):
            c["slides"][1]["takeaway"] = "PLACEHOLDER"
        for public, code in ((True, 1), (False, 0)):
            with self.subTest(public=public), tempfile.TemporaryDirectory() as d:
                root = Path(d)
                c = yaml.safe_load(CONTENT.read_text(encoding="utf-8"))
                design = yaml.safe_load(DESIGN.read_text(encoding="utf-8"))
                mutate(c, design)
                text = yaml.safe_dump(c, allow_unicode=True).replace("PLACEHOLDER", "詳細は Issue #19 で検討")
                (root / "content.yaml").write_text(text, encoding="utf-8")
                (root / "design.yaml").write_text(yaml.safe_dump(design, allow_unicode=True), encoding="utf-8")
                command = [sys.executable, str(ROOT / "scripts/validate.py"), "--content", str(root / "content.yaml"),
                           "--design", str(root / "design.yaml")] + (["--public-repo-check"] if public else [])
                r = subprocess.run(command, capture_output=True, text=True, check=False)
                self.assertEqual(r.returncode, code, r.stdout + r.stderr)
                self.assertIn("Issue #19", r.stdout)

    def test_intentional_comment_after_text_is_only_warned(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        import validate
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "content.yaml"
            path.write_text("notes: 詳細は Issue #19 で検討\ntitle: 本文の文言  # 作成者メモ\nquoted: '詳細は Issue #19'\n"
                            "layout: cover  # 設定の説明\ntakeaway: Issue #19\n", encoding="utf-8")
            strict, loose = validate.yaml_comment_issues(path)
            # 一語の値（takeaway: Issue #19）も「#」直後が空白でなければ strict（Codex 指摘）
            self.assertEqual([w.split(":")[1] for w in strict], ["1", "5"])
            self.assertEqual([":2:" in w for w in loose], [True])

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
