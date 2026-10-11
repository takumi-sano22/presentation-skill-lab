#!/usr/bin/env python3
"""Gate 4（#10）の Windows 版 PowerPoint 実機検証キットを作る。

Docker イメージ内で実行する（scripts/dev.sh run python3 scripts/gate4_kit.py）。
検証対象のデッキをすべて同じコマンドでビルドし、次を build/gate4-kit/ にまとめる:
  - <デッキ名>/deck.pptx・deck.pdf・png/・manifest.json（PowerPoint で開く最終 PPTX と比較用の PDF/PNG）
  - objects.md: スライドごとの「編集を試す対象」（PowerPoint の選択ウィンドウに出る図形名）と種別
  - CHECKLIST.md / RECORD_TEMPLATE.md: 手順と記録用テンプレート（docs/gate4-windows-checklist.md から生成）
  - SHA256SUMS・kit.json: 対象コミット・入力ハッシュ・成果物ハッシュ（記録とキットの対応づけ用）
実機での操作結果はここでは作らない（人が #10 に記録する）。
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import build  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "build" / "gate4-kit"
# (キット内の名前, content, design, 実機で見る観点)
DECKS = [
    ("01-claude-content-light", "technical-architecture/content.yaml", "technical-architecture/design.yaml",
     "基本: 表・棒グラフ・ネイティブ構成図・長い日本語見出し"),
    ("02-claude-content-dark", "technical-architecture/content.yaml", "technical-architecture/design-dark.yaml",
     "暗色テーマ（見出し帯・表・図の配色）"),
    ("03-gate4a-chatgpt-design", "technical-architecture/content.yaml", "technical-architecture/design-chatgpt.yaml",
     "Gate 4-A: ChatGPT が design だけ変更"),
    ("04-gate4b-chatgpt-content", "gate4-chatgpt-origin/content.yaml", "gate4-chatgpt-origin/design.yaml",
     "Gate 4-B: ChatGPT 作成の content に Claude Code が design"),
    ("05-er-native-and-svg", "bench-er/content.yaml", "bench-er/design.yaml",
     "ER: e402 ネイティブ（個別編集可）、e403 SVG 例外（図全体の画像・内部は編集不可）"),
    ("06-dense-tech", "bench-dense-tech/content.yaml", "bench-dense-tech/design.yaml",
     "表紙の改行、SQL の等幅列、v0.1 の ER（ネイティブ）"),
    ("07-table-chart", "bench-table-chart/content.yaml", "bench-table-chart/design.yaml",
     "比較表・1系列棒グラフ（単色）・折れ線グラフ"),
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "不明"


def objects(pptx: Path, content: dict) -> list[str]:
    """スライドごとの編集対象（名前は PowerPoint の［ホーム］→［選択］→［オブジェクトの選択と表示］に出る）。"""
    lines = []
    with zipfile.ZipFile(pptx) as z:
        for slide, part in zip(content["slides"], build.slide_part_names(z)):
            xml = z.read(part).decode("utf-8")
            names = [html.unescape(n) for n in re.findall(r'<p:cNvPr id="\d+" name="([^"]*)"', xml)]
            kinds = []
            if "<a:tbl>" in xml:
                kinds.append("表（ネイティブ）")
            if "drawingml/2006/chart" in xml:
                kinds.append("グラフ（ネイティブ）")
            node = [n for n in names if n.startswith("node:")]
            edge = sorted({n.split("#")[0] for n in names if n.startswith("edge:")})
            if node:
                kinds.append(f"構成図 ノード {len(node)}・辺 {len(edge)}（例: {node[0]}、{edge[0] if edge else ''}）")
            ent = [n for n in names if n.startswith("er-entity:")]
            if ent:
                attrs = [n for n in names if n.startswith("er-attr:")]
                cards = [n for n in names if n.startswith("er-card:")]
                kinds.append(f"ER ネイティブ エンティティ {len(ent)}・属性行 {len(attrs)}・多重度 {len(cards)}（例: {ent[0]}、{attrs[0]}）")
            svg = [n for n in names if n.startswith("er-svg:")]
            if svg:
                kinds.append(f"ER の SVG 例外 {svg[0]}（図全体の画像。内部は個別編集不可が正しい挙動）")
            pics = xml.count("<p:pic>") - len(svg)
            if pics:
                kinds.append(f"画像 {pics}")
            lines.append(f"| {slide['id']} | {slide['type']} | {slide['title']} | {'、'.join(kinds) or '文字のみ'} |")
    return lines


def main() -> int:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    commit = git("rev-parse", "HEAD")
    kit = {"commit": commit, "decks": []}
    inventory = ["# 編集を試す対象（スライド別）", "",
                 "図形名は PowerPoint の［ホーム］→［配置］→［オブジェクトの選択と表示］（選択ウィンドウ）に表示される名前。", ""]
    for name, content_rel, design_rel, focus in DECKS:
        out = OUT / name
        manifest = build.build(ROOT / "examples" / content_rel, ROOT / "examples" / design_rel, out)
        content = build.adapter.validate.load_yaml(ROOT / "examples" / content_rel)
        kit["decks"].append({"name": name, "focus": focus, "content": content_rel, "design": design_rel,
                             "content_sha256": manifest["inputs"]["content"]["sha256"],
                             "design_sha256": manifest["inputs"]["design"]["sha256"],
                             "pptx_sha256": sha256(out / "deck.pptx"), "slides": manifest["slides"],
                             "fallbacks": manifest["fallbacks"], "fonts": manifest["fonts"]["theme"]})
        inventory += [f"## {name}", "", f"観点: {focus}", "", "| Slide ID | 種別 | タイトル | 編集を試す対象 |", "|---|---|---|---|"]
        inventory += objects(out / "deck.pptx", content) + [""]
    (OUT / "objects.md").write_text("\n".join(inventory) + "\n", encoding="utf-8")
    doc = (ROOT / "docs" / "gate4-windows-checklist.md").read_text(encoding="utf-8")
    checklist, _, template = doc.partition("<!-- RECORD_TEMPLATE -->")
    (OUT / "CHECKLIST.md").write_text(checklist.replace("{{COMMIT}}", commit), encoding="utf-8")
    (OUT / "RECORD_TEMPLATE.md").write_text(template.strip().replace("{{COMMIT}}", commit) + "\n", encoding="utf-8")
    (OUT / "kit.json").write_text(json.dumps(kit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    sums = [f"{sha256(p)}  {p.relative_to(OUT).as_posix()}" for p in sorted(OUT.rglob("*"))
            if p.is_file() and p.suffix in (".pptx", ".pdf")]
    (OUT / "SHA256SUMS").write_text("\n".join(sums) + "\n", encoding="utf-8")
    print(f"PASS: Gate 4 実機検証キット → {OUT}（{len(DECKS)} デッキ、commit {commit[:12]}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
