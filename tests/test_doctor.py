"""doctor の上流固定・ライセンス検査の回帰テスト。描画ツールの有無には依存しない。"""
from __future__ import annotations

import configparser
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import doctor  # noqa: E402


class DoctorLockTests(unittest.TestCase):
    def setUp(self):
        self.lock = doctor.load_lock()

    def test_lock_pins_full_sha_and_tag(self):
        self.assertTrue(doctor.check_lock_format(self.lock).ok)
        self.assertRegex(self.lock["tag"], r"^v\d+\.\d+\.\d+$")

    def test_short_sha_is_rejected(self):
        bad = dict(self.lock, commit=self.lock["commit"][:7])
        self.assertFalse(doctor.check_lock_format(bad).ok)

    def test_lock_path_matches_gitmodules(self):
        # lock と .gitmodules の path/url がずれると固定対象が曖昧になる
        cfg = configparser.ConfigParser()
        cfg.read(ROOT / ".gitmodules", encoding="utf-8")
        section = f'submodule "{self.lock["path"]}"'
        self.assertEqual(cfg[section]["path"], self.lock["path"])
        self.assertEqual(cfg[section]["url"].removesuffix(".git"), self.lock["url"])

    def test_gitlink_matches_lock(self):
        # 実チェックアウトの有無に関わらず、記録された gitlink は lock と一致しなければならない
        gitlink = doctor.check_submodule(self.lock)[0]
        self.assertTrue(gitlink.ok, gitlink.detail)

    def test_license_hash_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "LICENSE").write_text("not MIT", encoding="utf-8")
            lock = dict(self.lock, path=".", license_file="LICENSE")
            original = doctor.ROOT
            try:
                doctor.ROOT = root
                self.assertFalse(doctor.check_license(lock).ok)
                lock["license_sha256"] = hashlib.sha256(b"not MIT").hexdigest()
                self.assertTrue(doctor.check_license(lock).ok)
            finally:
                doctor.ROOT = original


if __name__ == "__main__":
    unittest.main()
