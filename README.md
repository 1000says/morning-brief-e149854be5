# 自動更新ページ（配信基盤）

自動生成される個人向けの日次ページを **GitHub Pages** で配信するためのリポジトリ。
`index.html` は生成側（外部の自動化）が毎朝上書きする対象で、この repo 自体は「置き場所と配信の仕組み」だけを持つ。

## 仕組み

1. 生成側が `index.html` を `main` へ push する。
2. push で GitHub Actions（`.github/workflows/pages.yml`）が起動する。
3. `privacy-guard` ジョブが `index.html` を禁止パターン（郵便番号・電話・メール・追跡番号・座標・地図URL・住所語）で走査する。
   - 検出したら **deploy をブロック**（fail-closed）。Actions が失敗し、GitHub の既定で repo owner に失敗メールが届く。
   - クリーンなら `index.html` のみを `_site/` にステージして GitHub Pages へ deploy する。

## プライバシーの前提（重要・正直な説明）

- このリポジトリは **Public**。GitHub の Public repo は一覧・API・raw・clone・公開イベントで到達可能なため、
  **URL も内容も実質的に公開**であると考えること。「推測されにくい URL」は秘匿ではない。
- したがって **唯一の実効的な防御は「内容に個人を特定できる情報を載せないこと」**（生成側の redaction）。
  `privacy-guard` は push 後に走るため露出そのものは防げない＝**ベストエフォートの衛生と更新停止アラート**に過ぎない。
- より強い秘匿が必要なら GitHub Pro の **Private Pages**（Private repo + Pages 公開・有償）が選択肢。

## 運用メモ

- **禁止パターンの調整/一時無効化:** `.github/workflows/pages.yml` の `privacy-guard` を編集する。
  誤検知で更新が止まる場合は該当パターンを緩めるか、当該ジョブを一時的に無効化する（無効化中は衛生ネットが外れる点に注意）。
- **失敗通知:** guard 失敗＝更新停止に気付けるよう、GitHub の Actions 失敗通知を有効にしておく。
- **識別情報を repo に足さない:** `index.html` 以外（この README・ワークフロー・description）に個人情報を書かない。
- **commit identity:** push は GitHub の noreply identity で行う（個人メールを git 履歴に残さない）。
