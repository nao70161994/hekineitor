# Share Improvement Notes Plan

目的は、結果別シェアランキング上位の結果に対して「OGP文言改善メモ」を残し、次の文言改善や称号調整に使えるようにすることです。

## 方針

- DB schema は変更しない。
- 個人情報、IP、User-Agent、ユーザーIDは保存しない。
- 保存対象は管理者が入力した運用メモのみ。
- 診断結果、推論、質問選択、学習には影響させない。
- 最初は `data/share_improvement_notes.json` の小さなJSONで十分。

## 保存案

```json
{
  "NTR": {
    "note": "OGPタイトルをもう少し煽る。SSR称号との相性を見る。",
    "updated_at": "2026-05-24T00:00:00+00:00"
  }
}
```

## API案

- `GET /api/admin/share_notes`
  - 全メモを取得。
- `POST /api/admin/share_notes`
  - `result_name`, `note` を保存。
  - 管理者認証と既存CSRF/adminFetchを使う。
  - `result_name` は最大80文字、`note` は最大500文字。

## 管理画面案

- 結果別ランキング表の各行に「メモ」ボタンを置く。
- 折りたたみ行で textarea を表示。
- 保存後はランキング表示を更新せず、軽い保存完了表示だけ出す。

## 注意点

- メモ本文はHTML escapeして表示する。
- メモには個人情報を書かない注意書きを表示する。
- JSONファイルはログ同様にgit管理対象外にする。
- 監査が必要なら既存 `write_audit` に `share_note_update` を記録する。

## 実装を見送った理由

現時点ではランキング・比較・CSVの分析導線を優先したため、編集UIを急いで入れない。メモ機能は管理者入力を保存するため、CSRF、escape、監査ログ、gitignoreを揃えた小PRとして実装する方が安全。
