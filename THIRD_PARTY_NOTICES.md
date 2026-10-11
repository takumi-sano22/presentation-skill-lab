# サードパーティとライセンス管理

以下は調査済みの候補であり、**この初期雛形には外部コードをコピーしていない**。今後、コピー・改変・配布をする場合は、そのコミット時点のライセンス、著作権表示、同梱アセットの個別条件を確認してこの表を更新する。

| 名称 | URL | 確認したライセンス | 扱い |
|---|---|---|---|
| presentation-skill | https://github.com/siril9/presentation-skill | MIT | Phase 1 で git submodule もしくは pinned checkout 参照予定。正本は upstream |
| jinba-consulting-pptx-skill | https://github.com/carnot-tech/jinba-consulting-pptx-skill | MIT | 規約・パーツを選択的参照。直接移植時には元著作権・LICENSE を付記 |
| minorun-marp-skill | https://github.com/minorun365/minorun-marp-skill | Apache-2.0 | 考え方を参考。初期はコードのコピーなし。画像素材は別権利の可能性あり |
| basicslide | https://github.com/khaym/basicslide | MIT | 将来の独創的デザイン評価を参考。コード移植は未定 |
| Dagre | https://github.com/dagrejs/dagre | MIT | 将来のノード配置用の依存候補 |

**注意:** このリポジトリの `LICENSE` は本プロジェクトが作成したコードに適用。外部依存・フォント・画像など個別権利を再許諾するものではない。特に他社ブランド資産・第三者イラスト・有償フォントは自動的に MIT にならない。
