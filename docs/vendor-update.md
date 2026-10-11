# 上流（vendor）更新ルール

対象: `vendor/presentation-skill`（git submodule、`upstream.lock.json` で固定）。

## 原則

- 上流はタグ付きリリースのコミット SHA（40桁）で固定する。ブランチ追従・自動更新はしない。
- 更新は **専用 PR**（`chore/vendor-presentation-skill-vX.Y.Z`）で行い、機能変更と混ぜない。
- 第三者コード（npm 依存・上流スクリプト）はホストで直接実行せず、`scripts/dev.sh run` の Docker コンテナ内で実行する。

## 手順

1. 対象タグの確認: `gh release view vX.Y.Z -R siril9/presentation-skill`
2. submodule を対象コミットへ移動し、`upstream.lock.json` の `tag` / `commit` を更新する。
3. **差分確認**（PR 本文に要約を貼る）:
   - `git diff <旧SHA>..<新SHA> --stat`（submodule 内で実行）
   - `scripts/build_deck_pptxgenjs.js`・`templates/pptxgenjs/` の差分（outline.json の互換性・描画 API の変更）
   - `package.json` / `package-lock.json` の依存追加・版変更とそのライセンス
4. **ライセンス確認**: `LICENSE` が変わった場合は内容を読み、MIT 互換であることを確認してから `license_sha256` を更新する。非互換・疑義があれば更新を止めて Issue に記録する（`docs/autonomy.md` の停止条件）。
5. `upstream.lock.json` の `node_dependencies` を新しい lock の版に合わせる。
6. `scripts/dev.sh build` → `scripts/dev.sh run python3 scripts/doctor.py` が全項目 PASS。
7. サンプル回帰（#4 以降）: 既存サンプルの PPTX/PDF/PNG を再生成し、変更ページを目視比較する。
8. `THIRD_PARTY_NOTICES.md` のコミット・範囲を更新する。

## doctor が検査する固定条件

- superproject に記録された gitlink == `upstream.lock.json.commit`
- 実際のチェックアウト == `upstream.lock.json.commit`
- 上流 `LICENSE` の sha256 == `upstream.lock.json.license_sha256`
- Node 依存（pptxgenjs / jszip）の版 == `upstream.lock.json.node_dependencies`
