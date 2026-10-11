#!/usr/bin/env python3
"""共通ビルド CLI: content.yaml / design.yaml → outline.json → PPTX → PDF → PNG → manifest / gallery。

上流レンダラ・LibreOffice・poppler を実行するため、Docker イメージ内で動かす前提:
    scripts/build --content <content.yaml> --design <design.yaml> [--out build/<deck_id>]
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import subprocess
import sys
import tempfile
import unicodedata
import zipfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import adapter  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LOCK = json.loads((ROOT / "upstream.lock.json").read_text(encoding="utf-8"))
RENDERER = ROOT / LOCK["path"] / "scripts" / "build_deck_pptxgenjs.js"
PNG_DPI = 110


class BuildError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(cmd: list[str], **kw) -> str:
    """外部コマンドを実行し、失敗時は出力を添えて BuildError にする。"""
    p = subprocess.run(cmd, capture_output=True, text=True, check=False, **kw)
    if p.returncode != 0:
        raise BuildError(f"{cmd[0]} が失敗しました (exit {p.returncode}):\n{p.stdout}\n{p.stderr}")
    return p.stdout + p.stderr


def tool_version(cmd: list[str]) -> str:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except OSError:
        return "未検出"
    out = (p.stdout + p.stderr).strip()
    return out.splitlines()[0] if out else "未検出"


# ---------------------------------------------------------------------------
# 各段
# ---------------------------------------------------------------------------

def render_pptx(outline_path: Path, pptx_path: Path, preset: str) -> None:
    run(["node", str(RENDERER), "--outline", str(outline_path), "--output", str(pptx_path), "--style-preset", preset])


def convert_pdf(pptx_path: Path, out_dir: Path) -> Path:
    # LibreOffice はユーザープロファイルが書けないと黙って失敗するため、使い捨てプロファイルを指定する
    with tempfile.TemporaryDirectory(prefix="psl-lo-") as profile:
        run(["soffice", f"-env:UserInstallation=file://{profile}", "--headless",
             "--convert-to", "pdf", "--outdir", str(out_dir), str(pptx_path)])
    pdf = out_dir / (pptx_path.stem + ".pdf")
    if not pdf.is_file():
        raise BuildError("PDF が生成されませんでした")
    return pdf


def pdf_pages(pdf: Path) -> int:
    m = re.search(r"^Pages:\s+(\d+)", run(["pdfinfo", str(pdf)]), re.M)
    if not m:
        raise BuildError("pdfinfo からページ数を取得できません")
    return int(m.group(1))


def pdf_fonts(pdf: Path) -> list[dict]:
    """pdffonts の表をパースする（埋め込み有無・種別で豆腐化リスクを判定する）。"""
    lines = run(["pdffonts", str(pdf)]).splitlines()[2:]
    fonts = []
    for line in lines:
        parts = line.split()
        if len(parts) < 7:
            continue
        # 列: name type(複数語) encoding emb sub uni object ID
        fonts.append({"name": parts[0], "type": " ".join(parts[1:-6]), "embedded": parts[-5] == "yes",
                      "unicode": parts[-3] == "yes"})
    return fonts


def render_png(pdf: Path, out_dir: Path, slide_ids: list[str]) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.png"):
        old.unlink()
    run(["pdftoppm", "-r", str(PNG_DPI), "-png", str(pdf), str(out_dir / "page")])
    pages = sorted(out_dir.glob("page-*.png"))
    if len(pages) != len(slide_ids):
        raise BuildError(f"PNG 枚数 {len(pages)} とスライド数 {len(slide_ids)} が一致しません")
    named = []
    for i, (page, sid) in enumerate(zip(pages, slide_ids), start=1):
        target = out_dir / f"{i:02d}-{sid}.png"
        page.rename(target)
        named.append(target)
    return named


# ---------------------------------------------------------------------------
# 検査
# ---------------------------------------------------------------------------

def normalize(text: str) -> str:
    # 折返し・空白の差は無視し、NFKC で全角/半角の揺れを吸収して比較する
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))


def pptx_slide_texts(pptx: Path) -> list[str]:
    with zipfile.ZipFile(pptx) as z:
        names = sorted((n for n in z.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
                       key=lambda n: int(re.findall(r"\d+", n)[0]))
        texts = []
        for n in names:
            xml = z.read(n).decode("utf-8")
            # グラフは別パーツ（chartN.xml）なので、スライドが参照するグラフのテキストも含める
            rels = z.read(n.replace("slides/", "slides/_rels/") + ".rels").decode("utf-8") if \
                n.replace("slides/", "slides/_rels/") + ".rels" in z.namelist() else ""
            # 上流は絶対パス（/ppt/charts/）で参照するため、相対・絶対の両方を受ける
            for target in re.findall(r'Target="(?:\.\./|/ppt/)charts/(chart\d+\.xml)"', rels):
                xml += z.read(f"ppt/charts/{target}").decode("utf-8")
            texts.append(html.unescape("".join(re.findall(r"<(?:a:t|c:v)>([^<]*)</(?:a:t|c:v)>", xml))))
    return texts


def expected_texts(slide: dict) -> list[str]:
    """スライド上に現れるべき内容文字列（adapter の意味項目のうち可視のもの）。"""
    items = [slide["title"], slide.get("takeaway", ""), *slide.get("body", []), *slide.get("source_refs", [])]
    if slide.get("notes"):
        items.append(slide["notes"])
    if t := slide.get("table"):
        items += t["headers"] + [c for row in t["rows"] for c in row]
        # 単位・期間は部分一致で誤検出しないよう、表示文字列（caption）で照合する
        if t.get("unit") or t.get("period"):
            items.append(adapter.table_caption(t.get("unit"), t.get("period")))
    if ch := slide.get("chart"):
        items += ch["categories"] + [se["name"] for se in ch["series"]] + [adapter.chart_unit_title(ch["unit"])]
        items += [adapter.format_number(v) for se in ch["series"] for v in se["values"]]
    if d := slide.get("diagram"):
        items += [n["label"] for n in d["nodes"]] + [e["label"] for e in d.get("edges", []) if e.get("label")]
    return [i for i in items if i]


def check_content_in_pptx(content: dict, pptx: Path) -> list[str]:
    """PPTX の各スライドに内容文字列が欠落なく現れるかを検査する（上流の切り詰め・欠落の検出）。"""
    texts = pptx_slide_texts(pptx)
    if len(texts) != len(content["slides"]):
        return [f"PPTX のスライド数 {len(texts)} が content の {len(content['slides'])} と一致しません"]
    missing = []
    for slide, text in zip(content["slides"], texts):
        norm = normalize(text)
        missing += [f"{slide['id']}: 「{item}」" for item in expected_texts(slide) if normalize(item) not in norm]
    return missing


def pptx_text_runs(pptx: Path) -> list[list[str]]:
    """スライドごとのテキストランの一覧（グラフ部品は除く）。"""
    with zipfile.ZipFile(pptx) as z:
        names = sorted((n for n in z.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
                       key=lambda n: int(re.findall(r"\d+", n)[0]))
        return [[html.unescape(t) for t in re.findall(r"<a:t>([^<]*)</a:t>", z.read(n).decode("utf-8"))] for n in names]


def find_non_content_text(content: dict, outline: dict, pptx: Path) -> dict[str, list[str]]:
    """content に由来しないテキスト（レンダラの装飾ラベル・プレースホルダ等）をスライド別に列挙する。

    内容の改変ではないが、未承認の文言追加として可視化する（除去は日本語テーマ #5 で扱う）。
    """
    found: dict[str, list[str]] = {}
    for slide, o_slide, runs in zip(content["slides"], outline["slides"], pptx_text_runs(pptx)):
        allowed = normalize("".join(expected_texts(slide) + o_slide.get("bullets", []) + [o_slide.get("footer", "")]))
        # 出典ラベル（adapter が deck_style.footer_source_label で指定）は装飾ではなく既知の表示枠
        label = normalize(outline["deck_style"].get("footer_source_label", "") + ":")
        extra = [r for r in runs if (n := normalize(r).removeprefix(label)) and n not in allowed]
        # 出典ラベル等の短い定型も含めてそのまま記録する
        if extra:
            found[slide["id"]] = sorted(set(extra))
    return found


def pdf_page_texts(pdf: Path, pages: int) -> list[str]:
    return [run(["pdftotext", "-f", str(i), "-l", str(i), "-layout", str(pdf), "-"]) for i in range(1, pages + 1)]


def check_content_in_pdf(content: dict, pdf: Path, pages: int) -> list[str]:
    """PDF の各ページから抽出したテキストに内容文字列が現れるか（LibreOffice 変換での欠落・文字化けの検出）。

    グラフの軸ラベル・数値は描画方式によって抽出順が崩れるため、ここではグラフ以外の文字列を対象にする。
    """
    missing = []
    for slide, text in zip(content["slides"], pdf_page_texts(pdf, pages)):
        norm = normalize(text)
        chart_items = set()
        if ch := slide.get("chart"):
            chart_items = set(ch["categories"]) | {se["name"] for se in ch["series"]}
            chart_items |= {adapter.format_number(v) for se in ch["series"] for v in se["values"]}
        missing += [f"{slide['id']}: 「{item}」" for item in expected_texts(slide)
                    if item not in chart_items and normalize(item) not in norm]
    return missing


def check_fonts(fonts: list[dict]) -> list[str]:
    errors = [f"埋め込まれていないフォント: {f['name']}" for f in fonts if not f["embedded"]]
    if not any("CJK" in f["name"] or "JP" in f["name"] for f in fonts):
        errors.append("日本語フォント（Noto Sans CJK JP 等）が PDF に埋め込まれていません（豆腐化の疑い）")
    if any(f["type"].startswith("Type 3") for f in fonts):
        errors.append("Type 3 フォントが含まれます（ラスタ化・代替描画の疑い）")
    return errors


# ---------------------------------------------------------------------------
# 出力
# ---------------------------------------------------------------------------

def write_gallery(out: Path, deck_title: str, pngs: list[Path], slide_ids: list[str], manifest_rel: str) -> Path:
    cards = "\n".join(
        f'<figure><a href="png/{p.name}"><img src="png/{p.name}" alt="{html.escape(sid)}" loading="lazy"></a>'
        f"<figcaption>{i:02d} · {html.escape(sid)}</figcaption></figure>"
        for i, (p, sid) in enumerate(zip(pngs, slide_ids), start=1)
    )
    page = f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(deck_title)} プレビュー</title>
<style>
body{{margin:0;padding:16px;font-family:"Noto Sans CJK JP","Noto Sans JP",sans-serif;background:#f4f5f7;color:#1f2937}}
h1{{font-size:20px;margin:0 0 4px}} p{{margin:0 0 16px;font-size:13px;color:#4b5563}}
main{{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:16px}}
figure{{margin:0;background:#fff;border:1px solid #d1d5db;border-radius:6px;overflow:hidden}}
img{{display:block;width:100%;height:auto}} figcaption{{padding:6px 10px;font-size:12px}}
</style></head><body>
<h1>{html.escape(deck_title)}</h1>
<p>静的プレビュー（PNG）。正本は content.yaml / design.yaml。<a href="deck.pdf">PDF</a> · <a href="deck.pptx">PPTX</a> · <a href="{manifest_rel}">manifest</a></p>
<main>
{cards}
</main></body></html>
"""
    path = out / "index.html"
    path.write_text(page, encoding="utf-8")
    return path


def build(content_path: Path, design_path: Path, out: Path) -> dict:
    content, design = adapter.load_and_validate(content_path, design_path)
    out.mkdir(parents=True, exist_ok=True)
    slide_ids = [s["id"] for s in content["slides"]]

    # 1. adapter（意味項目の往復検査込み）
    outline = adapter.convert(content, design)
    outline_text = adapter.canonical_json(outline)
    outline_path = out / "outline.json"
    outline_path.write_text(outline_text, encoding="utf-8")

    # 2. PPTX（固定コミットの上流レンダラ）
    pptx = out / "deck.pptx"
    render_pptx(outline_path, pptx, outline["psl"]["render"]["style_preset"])

    # 3. PDF / 4. PNG
    pdf = convert_pdf(pptx, out)
    if pdf.name != "deck.pdf":
        pdf = pdf.rename(out / "deck.pdf")
    pages = pdf_pages(pdf)
    if pages != len(slide_ids):
        raise BuildError(f"PDF ページ数 {pages} とスライド数 {len(slide_ids)} が一致しません")
    pngs = render_png(pdf, out / "png", slide_ids)

    # 5. 検査（内容欠落・フォント埋め込み）
    fonts = pdf_fonts(pdf)
    missing = check_content_in_pptx(content, pptx)
    missing_pdf = check_content_in_pdf(content, pdf, pages)
    font_errors = check_fonts(fonts)
    non_content = find_non_content_text(content, outline, pptx)

    manifest = {
        "deck_id": content["deck_id"],
        "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "inputs": {
            "content": {"path": str(content_path), "sha256": adapter.content_hash(content)},
            "design": {"path": str(design_path), "sha256": sha256_file(design_path)},
        },
        "adapter_version": adapter.ADAPTER_VERSION,
        "renderer": {"name": LOCK["name"], "tag": LOCK["tag"], "commit": LOCK["commit"],
                     "style_preset": outline["psl"]["render"]["style_preset"]},
        "tools": {
            "node": tool_version(["node", "--version"]),
            "libreoffice": tool_version(["soffice", "--headless", "--version"]),
            "poppler": tool_version(["pdftoppm", "-v"]),
        },
        "fonts": {"pdf": fonts, "ja_fallback": tool_version(["fc-match", "sans-serif:lang=ja"])},
        "slides": len(slide_ids),
        "pdf_pages": pages,
        "artifacts": {
            "outline.json": adapter.sha256_text(outline_text),
            "deck.pptx": sha256_file(pptx),
            "deck.pdf": sha256_file(pdf),
            **{f"png/{p.name}": sha256_file(p) for p in pngs},
        },
        "fallbacks": {s["psl"]["slide_id"]: s["psl"]["fallback"] for s in outline["slides"] if s["psl"].get("fallback")},
        "checks": {
            "pdf_pages_match": pages == len(slide_ids),
            "content_missing_in_pptx": missing,
            "content_missing_in_pdf": missing_pdf,
            "font_errors": font_errors,
            # 警告（FAIL にしない）: content 由来でない文言。日本語テーマ（#5）で解消する
            "non_content_text": non_content,
        },
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_gallery(out, content["metadata"]["title"], pngs, slide_ids, "manifest.json")
    errors = [f"PPTX {e}" for e in missing] + [f"PDF {e}" for e in missing_pdf] + font_errors
    if errors:
        raise BuildError("検査 FAIL:\n" + "\n".join(f" - {e}" for e in errors))
    return manifest


def main() -> int:
    p = argparse.ArgumentParser(description="content/design から PPTX・PDF・PNG・静的プレビューを生成")
    p.add_argument("--content", required=True, type=Path)
    p.add_argument("--design", required=True, type=Path)
    p.add_argument("--out", type=Path, help="出力先（既定: build/<deck_id>）")
    a = p.parse_args()
    try:
        deck_id = adapter.validate.load_yaml(a.content).get("deck_id", "deck")
        out = a.out or ROOT / "build" / deck_id
        m = build(a.content, a.design, out)
    except (BuildError, ValueError, OSError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    if m["checks"]["non_content_text"]:
        print("WARN: content 由来でない文言（レンダラ装飾）: " + json.dumps(m["checks"]["non_content_text"], ensure_ascii=False))
    print(f"PASS: {m['slides']} スライド → {out}/deck.pptx, deck.pdf ({m['pdf_pages']} ページ), png/, index.html")
    print(f"renderer: {m['renderer']['tag']} {m['renderer']['commit'][:12]} / content_sha256: {m['inputs']['content']['sha256'][:12]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
