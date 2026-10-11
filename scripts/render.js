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

// design.theme → 上流プリセットのトークン。プリセット固有の色を残さず design の色だけで決める
function themeTokens(theme) {
  const c = theme.colors;
  const muted = c.muted || c.foreground;
  return {
    bg: hex(c.background),
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

module.exports = { themeTokens, hex, luminance };
