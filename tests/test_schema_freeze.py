"""データ契約（content v0.2 / design v0.1）の固定テスト。変更時は docs/schema-versioning.md の手順でバージョンを上げる。"""
from __future__ import annotations

import hashlib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# ハッシュだけを書き換えて通すことは禁止（docs/schema-versioning.md）
FROZEN = {
    # v0.2（#19 ER の互換追加: attributes / edge.id / edge.cardinality / edge.fk）。v0.1 は 8f3f553f…7742
    "schemas/content.schema.json": "77f919fa5ed7d84e9cf26d67e0ae715a78760cc9e935d1dc8dacf66dc9b69131",
    "schemas/design.schema.json": "1fa2fde67d5757708cdf71f110c8dc6383814987f4ff682330520e1e92000dfd",
}


class SchemaFreezeTests(unittest.TestCase):
    def test_v01_schemas_are_frozen(self):
        for rel, expected in FROZEN.items():
            with self.subTest(schema=rel):
                digest = hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()
                self.assertEqual(digest, expected, f"{rel} が変更されています。docs/schema-versioning.md を参照")


if __name__ == "__main__":
    unittest.main()
