#!/usr/bin/env node
/*
 * 上流レンダラ（vendor/presentation-skill）を改変せずに design.yaml のテーマを適用するラッパー。
 *
 * outline.json の psl.theme（design.yaml の theme をそのまま保持）からデザイントークンを作り、
 * 上流が export する PRESETS の基底プリセットへ注入してから、上流の main() を同じ引数で呼ぶ。
 *
 *   node scripts/render.js --outline <outline.json> --output <deck.pptx>
 */
'use strict';

const fs = require('fs');
const path = require('path');

const VENDOR = path.resolve(__dirname, '..', 'vendor', 'presentation-skill');

function parseArgs(argv) {
  const args = {};
  for (let i = 2; i < argv.length; i += 2) {
    if (!['--outline', '--output'].includes(argv[i]) || argv[i + 1] === undefined) {
      throw new Error(`usage: render.js --outline <outline.json> --output <deck.pptx>（不明な引数: ${argv[i]}）`);
    }
    args[argv[i].slice(2)] = argv[i + 1];
  }
  if (!args.outline || !args.output) throw new Error('--outline と --output が必要です');
  return args;
}

// '#1876A3' → '1876A3'（pptxgenjs は # なしの16進を要求する）
function hex(value) {
  return String(value).replace(/^#/, '').toUpperCase();
}

// 相対輝度（WCAG 2.x）。暗い面の判定に使う
function luminance(value) {
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(hex(value).slice(i, i + 2), 16) / 255)
    .map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

// 2色の線形混色（ratio=0 で a、1 で b）。design の色から面・罫線の色を導出する
function mix(a, b, ratio) {
  const pa = [0, 2, 4].map((i) => parseInt(hex(a).slice(i, i + 2), 16));
  const pb = [0, 2, 4].map((i) => parseInt(hex(b).slice(i, i + 2), 16));
  return pa.map((v, i) => Math.round(v + (pb[i] - v) * ratio).toString(16).padStart(2, '0')).join('').toUpperCase();
}

// 暗色テーマの見出し帯: 背景から前景へ寄せる割合（tests/test_render_contract.py でコントラストを検査）
const DARK_BAND_MIX = 0.12;

// design.theme → 上流プリセットのトークン。プリセット固有の色を残さず design の色だけで決める
function themeTokens(theme) {
  const c = theme.colors;
  const muted = c.muted || c.foreground;
  return {
    bg: hex(c.background),
    // カード・表本体の面は背景をわずかに前景へ寄せた色、罫線はさらに寄せた色
    surface: mix(c.background, c.foreground, 0.04),
    line: mix(c.background, c.foreground, 0.18),
    text: hex(c.foreground),
    text_muted: hex(muted),
    // 濃色面（見出し帯・表紙・行見出し）は背景と前景のうち暗い方。明色テーマでは前景。
    // 暗色テーマでは背景そのものだと見出し帯が背景に溶けて見えないため、背景を前景へ 12% 寄せた色にする（#22）
    bg_dark: luminance(c.background) < luminance(c.foreground)
      ? mix(c.background, c.foreground, DARK_BAND_MIX) : hex(c.foreground),
    accent_primary: hex(c.accent),
    // design に第2アクセントはないため、補助色（要点・グラフ第2系列）は muted を使う
    accent_secondary: hex(muted),
    font_heading: theme.fonts.heading,
    font_body: theme.fonts.body,
  };
}

// 上流 v1 のグラフ経路は軸・凡例の文字色を渡さず pptxgenjs 既定の黒（000000）になるため、
// 暗色テーマでも読めるよう軸・凡例の文字色を text_muted に置き換える（値・カテゴリ文字列は変えない）
async function recolorChartText(pptxPath, color) {
  const JSZip = require('jszip');
  const zip = await JSZip.loadAsync(fs.readFileSync(pptxPath));
  const charts = Object.keys(zip.files).filter((n) => /^ppt\/charts\/chart\d+\.xml$/.test(n));
  for (const name of charts) {
    const xml = await zip.file(name).async('string');
    const next = xml.replace(/<c:(catAx|valAx|legend)>[\s\S]*?<\/c:\1>/g,
      (block) => block.replace(/srgbClr val="000000"/g, `srgbClr val="${color}"`));
    zip.file(name, next);
  }
  if (charts.length) {
    fs.writeFileSync(pptxPath, await zip.generateAsync({ type: 'nodebuffer', compression: 'DEFLATE' }));
  }
}

// ノード種別 → pptxgenjs の図形（意味の違いを形でも示す）
const NODE_SHAPES = {
  actor: 'ellipse',
  policy: 'hexagon',
  datastore: 'flowChartMagneticDisk',
  tool: 'roundRect',
};

// psl.diagram_layout（scripts/diagram.py の配置結果）をネイティブ図形・線・ラベルとして描く。
// 名前（objectName）に node:/edge:<辺番号>:/group: を付け、ビルド検査が PPTX 実体から関係（並行辺の本数を含む）を復元できるようにする
function drawDiagram(pptx, pSlide, lay, preset) {
  const font = preset.font_body;
  for (const g of lay.groups || []) {
    pSlide.addShape(pptx.ShapeType.rect, {
      x: g.x, y: g.y, w: g.w, h: g.h, objectName: `group:${g.name}`,
      fill: { color: preset.surface }, line: { color: preset.line, width: 1, dashType: 'dash' },
    });
    // 区画名は配置計算が線と交わらない側（左端／右端）に決めた位置へ置く
    const lb = g.label_box;
    pSlide.addText(g.name, {
      x: lb.x, y: lb.y, w: lb.w, h: lb.h, objectName: `group-label:${g.name}`,
      fontFace: font, fontSize: lay.group_font_pt, bold: true, color: preset.text_muted, valign: 'middle', margin: 0,
    });
  }
  for (const e of lay.edges) {
    const pts = e.points;
    for (let i = 0; i + 1 < pts.length; i += 1) {
      const [x1, y1] = pts[i];
      const [x2, y2] = pts[i + 1];
      // pptxgenjs の線は (x,y)→(x+w,y+h)。逆向きの線分は flip で表し、矢印は最後の線分の終点だけに付ける
      pSlide.addShape(pptx.ShapeType.line, {
        x: Math.min(x1, x2), y: Math.min(y1, y2), w: Math.abs(x2 - x1), h: Math.abs(y2 - y1),
        flipH: x2 < x1, flipV: y2 < y1, objectName: `edge:${e.index}:${e.from}->${e.to}#${i}`,
        line: { color: preset.text_muted, width: 1.25, dashType: e.dash,
          endArrowType: i === pts.length - 2 ? 'triangle' : undefined },
      });
    }
    if (e.label_box) {
      const b = e.label_box;
      // 改行位置は配置計算（diagram.label_lines）が禁則と左右の長さで決めたもの。文字列は変えず a:br で改行する
      const lines = e.label_lines || [e.label];
      pSlide.addText(lines.map((t, k) => ({ text: t, options: { softBreakBefore: k > 0 } })), {
        x: b.x, y: b.y, w: b.w, h: b.h, objectName: `edge-label:${e.index}:${e.from}:${e.to}`,  // addText は名前を二重エスケープするため ">" を使わない
        fontFace: font, fontSize: lay.edge_font_pt, color: preset.text, align: 'center', valign: 'middle',
        fill: { color: preset.bg }, margin: 0,
      });
    }
  }
  for (const n of lay.nodes) {
    const lines = n.lines || [n.label];
    const runs = lines.map((t, k) => ({ text: t, options: { fontSize: n.font_pt || lay.node_font_pt, bold: true,
      color: preset.text, softBreakBefore: k > 0, breakLine: Boolean(n.description) && k === lines.length - 1 } }));
    if (n.description) runs.push({ text: n.description, options: { fontSize: lay.desc_font_pt, color: preset.text_muted } });
    pSlide.addText(runs, {
      shape: pptx.ShapeType[NODE_SHAPES[n.kind] || 'rect'], x: n.x, y: n.y, w: n.w, h: n.h,
      objectName: `node:${n.id}`, fontFace: font, align: 'center', valign: 'middle', margin: 0.04,
      fill: { color: preset.surface }, line: { color: preset.accent_primary, width: 1.25 },
    });
  }
  for (const item of lay.legend || []) {
    const midY = item.y + item.h / 2;
    pSlide.addShape(pptx.ShapeType.line, {
      x: item.x, y: midY, w: 0.35, h: 0, objectName: `legend-line:${item.kind}`,
      line: { color: preset.text_muted, width: 1.25, dashType: item.dash },
    });
    pSlide.addText(item.label, {
      x: item.x + 0.42, y: item.y, w: item.w - 0.42, h: item.h, objectName: `legend:${item.kind}`,
      fontFace: font, fontSize: lay.edge_font_pt, color: preset.text_muted, valign: 'middle', margin: 0,
    });
  }
}

// psl.er_layout（scripts/er.py の配置結果）を ER 図のネイティブ図形として描く（ADR-0002）。
// エンティティは枠・見出し帯・見出し文字・属性行（1行ずつ別の文字図形）に分け、PowerPoint で個別に選択・編集できるようにする。
// 名前: er-frame:/er-head:/er-entity:<ID>、er-attr:<ID>:<行番号>、er-edge:<辺番号>:<from>-><to>#<線分>、er-card:<辺番号>:from|to、er-label:<辺番号>
function drawER(pptx, pSlide, lay, preset) {
  const font = preset.font_body;
  const PAD = 0.08;
  for (const e of lay.edges) {
    const pts = e.points;
    for (let i = 0; i + 1 < pts.length; i += 1) {
      const [x1, y1] = pts[i];
      const [x2, y2] = pts[i + 1];
      // ER の関係は向き（矢印）ではなく両端の多重度で表す
      pSlide.addShape(pptx.ShapeType.line, {
        x: Math.min(x1, x2), y: Math.min(y1, y2), w: Math.abs(x2 - x1), h: Math.abs(y2 - y1),
        flipH: x2 < x1, flipV: y2 < y1, objectName: `er-edge:${e.index}:${e.from}->${e.to}#${i}`,
        line: { color: preset.text_muted, width: 1.25 },
      });
    }
    for (const end of ['from', 'to']) {
      const b = e.card_boxes && e.card_boxes[end];
      if (!b) continue;
      pSlide.addText(b.text, {
        x: b.x, y: b.y, w: b.w, h: b.h, objectName: `er-card:${e.index}:${end}`,
        fontFace: font, fontSize: lay.card_font_pt, bold: true, color: preset.text, align: 'center', valign: 'middle', margin: 0,
      });
    }
    if (e.label_box) {
      const b = e.label_box;
      pSlide.addText(e.label, {
        x: b.x, y: b.y, w: b.w, h: b.h, objectName: `er-label:${e.index}`,
        fontFace: font, fontSize: lay.label_font_pt, color: preset.text_muted, align: 'center', valign: 'middle',
        fill: { color: preset.bg }, margin: 0,
      });
    }
  }
  for (const en of lay.entities) {
    pSlide.addShape(pptx.ShapeType.rect, {
      x: en.x, y: en.y, w: en.w, h: en.h, objectName: `er-frame:${en.id}`,
      fill: { color: preset.surface }, line: { color: preset.accent_primary, width: 1.25 },
    });
    pSlide.addShape(pptx.ShapeType.rect, {
      x: en.x, y: en.y, w: en.w, h: en.header_h, objectName: `er-head:${en.id}`,
      fill: { color: preset.accent_primary }, line: { color: preset.accent_primary, width: 1.25 },
    });
    pSlide.addText(en.label, {
      x: en.x + PAD, y: en.y, w: en.w - 2 * PAD, h: en.header_h, objectName: `er-entity:${en.id}`,
      fontFace: font, fontSize: lay.header_font_pt, bold: true, color: 'FFFFFF', valign: 'middle', margin: 0,
    });
    en.rows.forEach((r, k) => {
      // キー表示（PK / FK / PK/FK）だけアクセント色の太字にし、主キーの行は全体を太字にする
      const marker = r.text.match(/^(PK\/FK|PK|FK) /);
      const runs = marker
        ? [{ text: marker[0], options: { bold: true, color: preset.accent_primary } },
          { text: r.text.slice(marker[0].length), options: { bold: r.pk, color: preset.text } }]
        : [{ text: r.text, options: { color: r.kind === 'desc' ? preset.text_muted : preset.text } }];
      pSlide.addText(runs, {
        x: r.x + PAD, y: r.y, w: r.w - 2 * PAD, h: r.h, objectName: `er-attr:${en.id}:${k}`,
        fontFace: font, fontSize: lay.attr_font_pt, valign: 'middle', margin: 0,
      });
    });
  }
}

// 日本語テーマ規約 J-1: 上流の補助ラベル（表紙キッカー 8.4pt、グラフ注記・軸ラベル 8pt 等）を最小 9pt に引き上げる。
// 文字列は変えず、文字サイズ属性（百分の一 pt）だけを置き換える
const MIN_FONT_CENTIPT = 900;
async function enforceMinFont(pptxPath) {
  const JSZip = require('jszip');
  const zip = await JSZip.loadAsync(fs.readFileSync(pptxPath));
  const parts = Object.keys(zip.files).filter((n) => /^ppt\/(slides\/slide|charts\/chart)\d+\.xml$/.test(n));
  for (const name of parts) {
    const xml = await zip.file(name).async('string');
    zip.file(name, xml.replace(/(<a:(?:rPr|defRPr|endParaRPr)\b[^>]*\ssz=")(\d+)"/g,
      (m, head, size) => (Number(size) < MIN_FONT_CENTIPT ? `${head}${MIN_FONT_CENTIPT}"` : m)));
  }
  fs.writeFileSync(pptxPath, await zip.generateAsync({ type: 'nodebuffer', compression: 'DEFLATE' }));
}

async function main() {
  const args = parseArgs(process.argv);
  const outline = JSON.parse(fs.readFileSync(args.outline, 'utf8'));
  const psl = outline.psl || {};
  if (!psl.theme || !psl.render || !psl.render.style_preset) {
    throw new Error('outline に psl.theme / psl.render.style_preset がありません（scripts/adapter.py の出力を渡してください）');
  }
  const presetName = psl.render.style_preset;
  // 上流の build_deck_pptxgenjs.js も同じモジュールを require するため、ここでの変更が描画に反映される
  const { PRESETS } = require(path.join(VENDOR, 'templates', 'pptxgenjs', 'presets.js'));
  if (!PRESETS[presetName]) throw new Error(`上流に基底プリセット ${presetName} がありません`);
  const tokens = themeTokens(psl.theme);
  Object.assign(PRESETS[presetName], tokens);

  // 図スライド（psl.diagram_layout）は上流の本文描画（見出し・要点・フッタ）に、ネイティブ図を重ねて描く。
  // 上流 builder は slides モジュールのプロパティを呼び出し時に参照するため、ここで差し替えれば反映される
  const slides = require(path.join(VENDOR, 'templates', 'pptxgenjs', 'slides.js'));
  const renderStandard = slides.renderStandard;
  const outlineDir = path.dirname(path.resolve(args.outline));
  slides.renderStandard = (pptx, pSlide, slideData, preset) => {
    renderStandard(pptx, pSlide, slideData, preset);
    const lay = slideData.psl && slideData.psl.diagram_layout;
    if (lay) drawDiagram(pptx, pSlide, lay, preset);
    const er = slideData.psl && slideData.psl.er_layout;
    if (er) drawER(pptx, pSlide, er, preset);
    const erSvg = slideData.psl && slideData.psl.er_svg;
    if (erSvg) {
      // 高密度 ER の例外（ADR-0002）: 構造データから生成した SVG を図全体の画像として置く。内部は個別編集できない
      pSlide.addImage({
        data: `image/svg+xml;base64,${Buffer.from(erSvg.svg, 'utf8').toString('base64')}`,
        x: erSvg.x, y: erSvg.y, w: erSvg.w, h: erSvg.h, objectName: `er-svg:${slideData.psl.slide_id}`,
        altText: `ER 図（SVG。元定義 sha256 ${slideData.psl.fallback.source_sha256.slice(0, 12)}）`,
      });
    }
    const img = slideData.psl && slideData.psl.image;
    if (img) {
      // 画像スライド: adapter が manifest の寸法から計算した位置へ置く（cover は領域を埋めて端を切る）
      // cover: w/h に画像本来の比率の寸法、sizing に枠の寸法を渡すと、pptxgenjs が比率を保って切り抜く（枠は sizing の寸法）
      const cover = img.fit === 'cover';
      pSlide.addImage({
        path: path.resolve(outlineDir, img.path), x: img.x, y: img.y,
        w: cover ? img.src_w : img.w, h: cover ? img.src_h : img.h,
        sizing: cover ? { type: 'cover', w: img.w, h: img.h } : undefined,
        altText: img.alt, objectName: `asset:${img.asset_ref}`,
      });
    }
  };

  const builder = require(path.join(VENDOR, 'scripts', 'build_deck_pptxgenjs.js'));
  process.argv = [process.argv[0], 'build_deck_pptxgenjs.js',
    '--outline', args.outline, '--output', args.output, '--style-preset', presetName];
  await builder.main();
  await recolorChartText(args.output, tokens.text_muted);
  await enforceMinFont(args.output);
}

if (require.main === module) {
  main().catch((err) => {
    console.error(`Error: ${err && err.message ? err.message : err}`);
    process.exit(1);
  });
}

module.exports = { themeTokens, hex, luminance, mix, DARK_BAND_MIX };
