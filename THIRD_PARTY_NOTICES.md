# サードパーティとライセンス管理

外部コードはリポジトリへコピーせず、git submodule で参照する（下記「取り込み済み」）。今後、コピー・改変・配布をする場合は、そのコミット時点のライセンス、著作権表示、同梱アセットの個別条件を確認してこの表を更新する。

| 名称 | URL | 確認したライセンス | 扱い |
|---|---|---|---|
| presentation-skill | https://github.com/siril9/presentation-skill | MIT | **取り込み済み**（下記）。正本は upstream |
| jinba-consulting-pptx-skill | https://github.com/carnot-tech/jinba-consulting-pptx-skill | MIT | 規約・パーツを選択的参照。直接移植時には元著作権・LICENSE を付記 |
| minorun-marp-skill | https://github.com/minorun365/minorun-marp-skill | Apache-2.0 | 考え方を参考。初期はコードのコピーなし。画像素材は別権利の可能性あり |
| basicslide | https://github.com/khaym/basicslide | MIT | 将来の独創的デザイン評価を参考。コード移植は未定 |
| Dagre | https://github.com/dagrejs/dagre | MIT | 将来のノード配置用の依存候補 |

**注意:** このリポジトリの `LICENSE` は本プロジェクトが作成したコードに適用。外部依存・フォント・画像など個別権利を再許諾するものではない。特に他社ブランド資産・第三者イラスト・有償フォントは自動的に MIT にならない。

## 取り込み済み

### presentation-skill（git submodule）

- パス: `vendor/presentation-skill`
- タグ / コミット: `v0.14.0` / `efd899c5ddf866af2ce0001c4c9340af775d4d55`（`upstream.lock.json` で固定）
- ライセンス: MIT（Copyright (c) 2026 Siril Sengolraj）。原文は submodule 内 `LICENSE` をそのまま保持し、sha256 を doctor で検査する。
- コピー範囲: **なし**。本リポジトリのファイルへ上流コードを複製・改変していない。ビルド時に submodule のスクリプト（`scripts/build_deck_pptxgenjs.js`、`templates/pptxgenjs/`）を実行する。
- 更新手順: [`docs/vendor-update.md`](docs/vendor-update.md)

### 上流の Node 依存（Docker イメージ内で `npm ci`、リポジトリには含めない）

上流 `package-lock.json` 記載の版。本リポジトリは再配布しない。

| パッケージ | 版 | ライセンス |
|---|---|---|
| pptxgenjs | 4.0.1 | MIT |
| jszip | 3.10.1 | MIT OR GPL-3.0-or-later（MIT を選択） |
| react / react-dom | 19.2.5 | MIT |
| react-icons | 5.6.0 | MIT（同梱アイコンセットは個別ライセンス。使用時に確認） |
| sharp | 0.35.3 | Apache-2.0（同梱 libvips バイナリは LGPL-3.0。再配布しない） |

### 描画環境（Docker イメージ内、再配布しない）

- LibreOffice（MPL-2.0）、poppler-utils（GPL-2.0）、Noto Sans CJK JP（`fonts-noto-cjk`, SIL OFL 1.1）。いずれも Debian パッケージをイメージ構築時に取得し、本リポジトリには含めない。
