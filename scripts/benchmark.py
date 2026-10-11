#!/usr/bin/env python3
"""技術資料ベンチマーク: 3デッキ × 3条件（初期・テーマ変更・文言増加）をビルドし、比較ギャラリーと指標を出す。

Docker イメージ内で実行する（scripts/dev.sh run python3 scripts/benchmark.py）。
    出力: build/benchmark/index.html（条件ごとの PNG を並べた before/after）、build/benchmark/metrics.json
意味保持（自動の検査結果）と装飾品質（docs/benchmarks.md の目視評価）は別の指標として扱う。
"""
from __future__ import annotations

import argparse
import copy
import html
import json
import shutil
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

import build  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DECKS = ["bench-architecture", "bench-table-chart", "bench-dense-tech"]
CONDITIONS = {"initial": "初期", "theme": "テーマ変更（technical-dark）", "text_plus": "文言増加"}
DARK_THEME = {
    "name": "technical-dark",
    "fonts": {"heading": "Noto Sans JP", "body": "Noto Sans JP"},
    "colors": {"background": "#0F172A", "foreground": "#E2E8F0", "accent": "#0284C7", "muted": "#94A3B8"},
}
# 文言増加: 要点・本文・注記に補足を足して文字量を増やす（数値・表セル・図ラベルは変えない）
# QA 重大 0 まで必須の条件。文言増加は意味保持だけ必須で、幾何の崩れは想定崩れとして記録する
REQUIRED_CLEAN = ("initial", "theme")
TAKEAWAY_SUFFIX = "（前提と適用範囲は付録を参照）"
BODY_SUFFIX = "。判断の根拠と例外条件も併記する"
NOTES_SUFFIX = "。数値はすべて検証用の仮の値である"


def variant(content: dict, design: dict, condition: str) -> tuple[dict, dict]:
    content, design = copy.deepcopy(content), copy.deepcopy(design)
    if condition == "theme":
        design["theme"] = copy.deepcopy(DARK_THEME)
    elif condition == "text_plus":
        for s in content["slides"]:
            if s.get("takeaway"):
                s["takeaway"] += TAKEAWAY_SUFFIX
            if s.get("body"):
                s["body"] = [b + BODY_SUFFIX for b in s["body"]]
            if s.get("notes"):
                s["notes"] += NOTES_SUFFIX
    return content, design


def metrics(manifest: dict | None, error: str = "") -> dict:
    """意味保持（自動）の指標。ビルドが止まった場合は止まった理由を残す。"""
    if manifest is None:
        return {"built": False, "error": error}
    c = manifest["checks"]
    return {
        "built": True,
        "content_missing": len(c["content_missing_in_pptx"]) + len(c["content_missing_in_pdf"]),
        "qa_errors": len(c["qa"]["errors"]),
        "qa_warnings": len(c["qa"]["warnings"]),
        "diagram_errors": len(c["diagram_errors"]),
        "media_errors": len(c["media_errors"]),
        "font_errors": len(c["font_errors"]),
        "japanese_errors": len(c["japanese_errors"]),
        "diagram_crossings": sum(c["diagram_crossings"].values()),
        "japanese_warnings": c["japanese_warnings"],
        "non_content_text": c["non_content_text"],
        "fallbacks": manifest["fallbacks"],
    }


def run_condition(deck: str, condition: str, out_root: Path) -> dict:
    src = ROOT / "examples" / deck
    content = yaml.safe_load((src / "content.yaml").read_text(encoding="utf-8"))
    design = yaml.safe_load((src / "design.yaml").read_text(encoding="utf-8"))
    content, design = variant(content, design, condition)
    work = out_root / deck / condition
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    # アセット参照を保つため、元の assets/ があれば複製してから条件別の入力を置く
    if (src / "assets").is_dir():
        shutil.copytree(src / "assets", work / "assets")
    (work / "content.yaml").write_text(yaml.safe_dump(content, allow_unicode=True, sort_keys=False), encoding="utf-8")
    (work / "design.yaml").write_text(yaml.safe_dump(design, allow_unicode=True, sort_keys=False), encoding="utf-8")
    try:
        manifest = build.build(work / "content.yaml", work / "design.yaml", work / "out")
        return {"deck": deck, "condition": condition, **metrics(manifest)}
    except (build.BuildError, ValueError) as exc:
        # 検査で止まった場合も、どこまで描画できたかを比較できるよう結果として残す
        partial = work / "out" / "manifest.json"
        m = json.loads(partial.read_text(encoding="utf-8")) if partial.is_file() else None
        return {"deck": deck, "condition": condition, **metrics(m), "built": False, "error": str(exc)}


def gate_failures(results: list[dict], out_root: Path) -> tuple[list[str], list[dict]]:
    """Gate の判定。戻り値は（FAIL 理由の一覧, 想定内の崩れ＝ストレス所見の一覧）。

    - 全 9 条件: ビルド結果（manifest）が得られ、内容欠落・図の接続・画像・フォント・和文の重大エラーが 0。
      意味（文言・数値・表セル・図の関係）の欠落は文言増加でも許さない。
    - 初期・テーマ変更: さらに QA 重大 0 かつビルド成功（Gate 3）。
    - 文言増加: 文字量を意図的に増やす負荷試験なので、QA の幾何の崩れ（あふれ・重なり等）は
      「想定崩れ」として記録し FAIL にしない。再現コマンドを残す。
    """
    failures, stress = [], []
    for r in results:
        name = f"{r['deck']}/{r['condition']}"
        if "content_missing" not in r:
            failures.append(f"{name}: ビルド結果（manifest）が得られません: {r.get('error', '')[:200]}")
            continue
        meaning = {k: r[k] for k in ("content_missing", "diagram_errors", "media_errors", "font_errors", "japanese_errors")
                   if r.get(k)}
        if meaning:
            failures.append(f"{name}: 意味保持・重大検査の FAIL {meaning}")
        if r["condition"] in REQUIRED_CLEAN:
            if not r["built"] or r["qa_errors"]:
                failures.append(f"{name}: QA 重大 {r['qa_errors']}（初期・テーマ変更は 0 が必須）")
        elif r["qa_errors"] and not meaning:
            work = out_root / r["deck"] / r["condition"]
            stress.append({"case": name, "qa_errors": r["qa_errors"],
                           "repro": f"scripts/build --content {work / 'content.yaml'} --design {work / 'design.yaml'}"
                                    f" --out {work / 'out'}"})
    return failures, stress


def gallery(results: list[dict], out_root: Path) -> Path:
    """デッキごとに、スライド（行）× 条件（列）で PNG を並べた before/after 比較ページ。"""
    sections = []
    for deck in DECKS:
        rows = {r["condition"]: r for r in results if r["deck"] == deck}
        pngs = {c: sorted((out_root / deck / c / "out" / "png").glob("*.png")) for c in CONDITIONS}
        count = max((len(v) for v in pngs.values()), default=0)
        head = "".join(f"<th>{html.escape(label)}<br><small>{status(rows.get(c))}</small></th>"
                       for c, label in CONDITIONS.items())
        body = ""
        for i in range(count):
            cells = ""
            for c in CONDITIONS:
                p = pngs[c][i] if i < len(pngs[c]) else None
                rel = p.relative_to(out_root).as_posix() if p else ""
                cells += f'<td><a href="{rel}"><img src="{rel}" loading="lazy" alt="{html.escape(rel)}"></a></td>' if p else "<td>—</td>"
            body += f"<tr><th>{i + 1:02d}</th>{cells}</tr>"
        sections.append(f"<section><h2>{html.escape(deck)}</h2><table><tr><th></th>{head}</tr>{body}</table></section>")
    page = f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>技術資料ベンチマーク</title>
<style>
body{{margin:0;padding:16px;font-family:"Noto Sans CJK JP","Noto Sans JP",sans-serif;background:#f4f5f7;color:#1f2937}}
h1{{font-size:20px}} h2{{font-size:16px;margin:24px 0 8px}} table{{border-collapse:collapse;width:100%}}
th,td{{border:1px solid #d1d5db;padding:4px;vertical-align:top;background:#fff;font-size:12px}}
img{{display:block;width:100%;height:auto}} small{{font-weight:normal;color:#4b5563}}
</style></head><body>
<h1>技術資料ベンチマーク（初期 / テーマ変更 / 文言増加）</h1>
<p>意味保持は自動検査（metrics.json）、装飾品質は docs/benchmarks.md の目視評価で別に扱う。</p>
{''.join(sections)}
</body></html>
"""
    path = out_root / "index.html"
    path.write_text(page, encoding="utf-8")
    return path


def status(r: dict | None) -> str:
    if not r:
        return "未実行"
    if not r["built"]:
        return "検査で停止: " + html.escape(r.get("error", "").splitlines()[0][:80])
    return f"内容欠落 {r['content_missing']} / QA 重大 {r['qa_errors']} / 警告 {r['qa_warnings'] + len(r['japanese_warnings'])}"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path, default=ROOT / "build" / "benchmark")
    a = p.parse_args()
    results = [run_condition(d, c, a.out) for d in DECKS for c in CONDITIONS]
    failures, stress = gate_failures(results, a.out)
    (a.out / "metrics.json").write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (a.out / "gate.json").write_text(json.dumps({"passed": not failures, "failures": failures, "expected_stress": stress},
                                                ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    gallery(results, a.out)
    for r in results:
        print(f"{r['deck']:22s} {r['condition']:10s} {status(r)}")
    for s in stress:
        print(f"想定崩れ（文言増加の負荷試験）: {s['case']} QA 重大 {s['qa_errors']} 再現: {s['repro']}")
    for f in failures:
        print(f"FAIL: {f}")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
