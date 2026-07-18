# Share Improvement Notes

目的は、結果別シェアランキング上位の結果に対して「OGP文言改善メモ」を残し、次の文言改善や称号調整に使えるようにすることです。

## 方針

- DB schema は変更しない。
- 個人情報、IP、User-Agent、ユーザーIDは保存しない。
- 保存対象は管理者が入力した運用メモのみ。
- 診断結果、推論、質問選択、学習には影響させない。
- `data/share_improvement_notes.json` の小さなJSONへ保存する。

## 保存形式

```json
{
  "NTR": {
    "note": "OGPタイトルをもう少し煽る。SSR称号との相性を見る。",
    "updated_at": "2026-05-24T00:00:00+00:00"
  }
}
```

## API

- `GET /api/admin/share_notes`
  - 全メモを取得。
- `POST /api/admin/share_notes`
  - `result_name`, `note` を保存。
  - 管理者認証と既存CSRF/adminFetchを使う。
  - `result_name` は80文字、`note` は500文字へ正規化し、超過分は切り捨てる。

## 管理画面

- 結果別ランキング表の各行に textarea と保存ボタンを表示する。
- 既存ランキングの DOM 構造を大きく変えず、横スクロール内に収める。
- 保存後はランキング表示を更新せず、軽い保存完了表示だけ出す。
- メモがある行には「改善メモあり」を表示する。

## 注意点

- メモ本文はHTML escapeして表示する。
- メモには個人情報を書かない注意書きを表示する。
- JSONファイルはログ同様にgit管理対象外にする。
- 監査が必要なら既存 `write_audit` に `share_note_update` を記録する。

## 実装状況

実装済みです。`services/share_notes.py` が JSON 保存と入力長制限を担当し、`/api/admin/share_notes` が管理者用の取得/保存 API を提供します。POST は既存の `require_admin` と admin CSRF に乗せています。

保存時は `share_note_update` を監査ログに残します。本文は保存時にHTMLを削除せず、表示時のJinja自動escapeでXSSを防ぎます。これにより「OGP案に記号を書いた」程度の管理メモを失わず、画面へのHTML注入は避けます。
