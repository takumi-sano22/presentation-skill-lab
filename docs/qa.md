# 自動 QA（内容保持・幾何・編集性）

`scripts/build` が描画後に全検査を実行し、重大な違反があれば終了コード 1 で止まる。結果は `build/<deck>/manifest.json` の `checks` と、レビュー用の `build/<deck>/qa/report.json` に出力され、CI では artifact として保存される。

## 検査一覧

| 区分 | 検査 | 実装 | 重大度 |
|---|---|---|---|
| 内容保持 | 文言・表セル・数値・単位・図ラベル・出典・注記が PPTX（段落・表セル・グラフ値）に出現回数込みで存在。数値は完全一致（丸めも欠落扱い） | `build.check_content_in_pptx` | FAIL |
| 内容保持 | PDF の抽出テキストに同上（グラフ以外） | `build.check_content_in_pdf` | FAIL |
| 内容保持 | adapter の往復検査（content ⇔ outline の意味項目） | `adapter.verify_roundtrip` | FAIL |
| 幾何 | `out-of-bounds`: 図形のスライド外はみ出し（文字・表・グラフ・画像は FAIL、文字のない装飾は警告） | `qa` | FAIL / 警告 |
| 幾何 | `text-overlap`: 文字を持つ図形どうしの重なり（小さい方の面積の 10% 超） | `qa` | FAIL |
| 幾何 | `text-overflow`: 文字量から推定した必要高さが枠を超える（内側余白は bodyPr、`normAutofit`・`spAutoFit` の枠は対象外） | `qa` | FAIL |
| 幾何 | `autofit-expansion`: `spAutoFit`（図形を文字に合わせて伸ばす）の枠が、縦位置（anchor）に応じて上下へ、折り返さない枠（`wrap="none"`）は段落の水平位置に応じて左右へ伸びた部分で他の文字・表・グラフ・画像と重なる、またはスライド外に出る。`normAutofit`（文字を縮小）とは区別し、こちらは縮小後の実効サイズを `min-font` で検査 | `qa` | FAIL |
| 文字 | `min-font`: 9pt 未満の文字（J-1。上流の補助ラベルは描画時に 9pt へ引き上げる） | `qa` / `render.js` | FAIL |
| 文字 | タイトル長（全角換算 40 字超は警告、80 字超は FAIL）・泣き別れ（警告） | `build.check_japanese` | FAIL / 警告 |
| 図 | `connector-crossing`: 図の線が端点以外のノード・ラベル・区画名・凡例を貫通。ER の関係線が端点以外のエンティティ見出し・属性行・多重度・関係名を貫通 | `qa` | FAIL |
| 図 | ノード図形の存在・重なり 0、辺の始終点が正しいノード境界、終点の矢印、content に無いノード・辺が無い | `build.check_diagram_in_pptx` | FAIL |
| ER | ネイティブ: 見出し・属性行の文字と所属（枠内）、枠の重なり 0、関係線の連続・始点＝外部キー側の境界かつ FK 行の高さ・終点＝参照先の境界（反転・接続先誤りの検出）、多重度・関係名の文字と位置、定義に無い er-* 図形なし。SVG 例外: 画像の配置、埋め込み SVG のハッシュが manifest と一致し全文字列・関係を含む | `build.check_er_in_pptx` | FAIL |
| ER | SVG 例外の一覧と、縮小後の実効文字サイズが 9pt 未満のときの分割提案 | `build.er_fallback_warnings` | 警告 |
| 編集性 | `rasterized-table` / `rasterized-chart` / `rasterized-diagram`: manifest に登録のない画像（表・グラフ・図・本文の画像化の疑い）。ER の SVG 例外（`er-svg:<Slide ID>`、adapter が理由とハッシュを記録したもの）だけは許可 | `qa` | FAIL |
| 編集性 | `missing-native-table` / `missing-native-chart`: 表・グラフがネイティブオブジェクトでない | `qa` | FAIL |
| 編集性 | 埋め込み PNG の構造・画像スライドの配置 | `build.check_media` | FAIL |
| 描画環境 | PDF のフォント埋め込み・日本語フォント・Type 3 なし、テーマ書体の解決 | `build` | FAIL |
| 権利 | 画像アセットの出自・ライセンス・ハッシュ・寸法など | `assets` | FAIL |
| 入力 | 引用符なしの文言（plain scalar）の直後の「 #」（直後が空白でない。`Issue #19` など）は YAML コメントとして以降が捨てられる。YAML のスキャナで判定し、引用符付き・ブロックスカラー（`|` / `>`）は対象外。`--public-repo-check` で FAIL、それ以外は警告。「 # 」（# の後に空白）は意図したコメントとして警告のみ | `validate.yaml_comment_issues` | FAIL / 警告 |
| 参考 | 図の辺の交差数、content 由来でない文言 | `build` | 記録・警告 |

## 描画後の仕上げ（`scripts/polish.py`、#22）

上流レンダラの出力を、内容（文字列・数値・表セル）を変えずに見せ方だけ調整する: 1系列棒グラフの単色化、表の列幅配分・行の高さ（J-9）・等幅列（J-10）、タイトルの泣き別れ解消（J-3）。適用した調整は manifest の `polish` に残り、上表の検査はすべて仕上げ後の PPTX に対して行う（仕上げで内容が崩れれば FAIL）。

## 誤検知の除外（`<deck>/qa-exceptions.yaml`）

除外は **Slide ID・検査 ID・対象・理由がすべて必須**。欠けていればビルドは FAIL する。使われなくなった除外は `stale_exceptions` として報告される（放置すると本物の不具合を隠すため削除する）。

```yaml
exceptions:
  - slide_id: s004
    check: text-overflow        # 上表の検査 ID
    target: Text 7              # 図形名（PowerPoint の選択ウィンドウの名前）の一部
    reason: 法定の注記文を省略できないため。PDF で目視確認済み（2026-10-11）
```

除外できるのは `qa` の検査（幾何・文字・図の線・画像化）だけ。内容保持・図の関係・権利の検査は除外できない。

## 意図的に壊したサンプル

`tests/test_qa.py` の `BrokenSampleTests`（Docker 内）は、正常にビルドした PPTX の XML を書き換えて、表の画像化・表セル欠落・数値変更／丸め・スライド外はみ出し・文字の縮小・文字図形の重なり・図の線とラベルの交差・`spAutoFit` の伸長衝突で各検査が FAIL することを確かめる。

## 限界

- 文字あふれは文字幅の推定（和文 1em、欧文 0.55em）による。最終判断は PNG の目視。
- PNG/JPEG の画像内の文字・中心データの焼き込みは自動検出しない（アセット運用と PR レビュー）。
