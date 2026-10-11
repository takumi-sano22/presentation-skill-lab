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
    // 濃色面（見出し帯・表紙・行見出し）は背景と前景のうち暗い方。明色テーマでは前景、暗色テーマでは背景
    bg_dark: hex(luminance(c.background) < luminance(c.foreground) ? c.background : c.foreground),
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
// 名前（objectName）に node:/edge:/group: を付け、ビルド検査が PPTX 実体から関係を復元できるようにする
function drawDiagram(pptx, pSlide, lay, preset) {
  const font = preset.font_body;
  for (const g of lay.groups || []) {
    pSlide.addShape(pptx.ShapeType.rect, {
      x: g.x, y: g.y, w: g.w, h: g.h, objectName: `group:${g.name}`,
      fill: { color: preset.surface }, line: { color: preset.line, width: 1, dashType: 'dash' },
    });
    pSlide.addText(g.name, {
      x: g.x + 0.08, y: g.y + 0.02, w: g.w - 0.16, h: 0.22, objectName: `group-label:${g.name}`,
      fontFace: font, fontSize: 9, bold: true, color: preset.text_muted, valign: 'middle', margin: 0,
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
        flipH: x2 < x1, flipV: y2 < y1, objectName: `edge:${e.from}->${e.to}#${i}`,
        line: { color: preset.text_muted, width: 1.25, dashType: e.dash,
          endArrowType: i === pts.length - 2 ? 'triangle' : undefined },
      });
    }
    if (e.label_box) {
      const b = e.label_box;
      pSlide.addText(e.label, {
        x: b.x, y: b.y, w: b.w, h: b.h, objectName: `edge-label:${e.from}->${e.to}`,
        fontFace: font, fontSize: lay.edge_font_pt, color: preset.text, align: 'center', valign: 'middle',
        fill: { color: preset.bg }, margin: 0,
      });
    }
  }
  for (const n of lay.nodes) {
    const runs = [{ text: n.label, options: { fontSize: lay.node_font_pt, bold: true, color: preset.text,
      breakLine: Boolean(n.description) } }];
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
  slides.renderStandard = (pptx, pSlide, slideData, preset) => {
    renderStandard(pptx, pSlide, slideData, preset);
    const lay = slideData.psl && slideData.psl.diagram_layout;
    if (lay) drawDiagram(pptx, pSlide, lay, preset);
  };

  const builder = require(path.join(VENDOR, 'scripts', 'build_deck_pptxgenjs.js'));
  process.argv = [process.argv[0], 'build_deck_pptxgenjs.js',
    '--outline', args.outline, '--output', args.output, '--style-preset', presetName];
  await builder.main();
  await recolorChartText(args.output, tokens.text_muted);
}

if (require.main === module) {
  main().catch((err) => {
    console.error(`Error: ${err && err.message ? err.message : err}`);
    process.exit(1);
  });
}

module.exports = { themeTokens, hex, luminance, mix };
