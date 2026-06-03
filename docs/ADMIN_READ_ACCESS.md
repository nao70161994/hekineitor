# Admin Read Access

`ADMIN_READ_TOKEN` は、Codex など外部レビュー担当が本番分析だけを実行するための読み取り専用トークンです。既存の `ADMIN_PASS` は管理画面の編集・削除・学習操作にも使えるため、長期運用で共有しないでください。

## 設定

Render の Web Service 環境変数に追加します。

```text
ADMIN_READ_TOKEN=<十分長いランダム文字列>
```

変更後に再デプロイまたは再起動します。

## 使えるAPI

Bearer token で以下の読み取りAPIだけを呼び出せます。

```sh
curl -H "Authorization: Bearer $ADMIN_READ_TOKEN" https://hekineitor.onrender.com/api/admin/read_overview
curl -H "Authorization: Bearer $ADMIN_READ_TOKEN" https://hekineitor.onrender.com/api/admin/preflight
curl -H "Authorization: Bearer $ADMIN_READ_TOKEN" https://hekineitor.onrender.com/api/admin/fetishes_snapshot
curl -H "Authorization: Bearer $ADMIN_READ_TOKEN" https://hekineitor.onrender.com/api/admin/learning_stats
curl -H "Authorization: Bearer $ADMIN_READ_TOKEN" https://hekineitor.onrender.com/api/admin/question_stats
curl -H "Authorization: Bearer $ADMIN_READ_TOKEN" https://hekineitor.onrender.com/api/admin/quality_report
curl -H "Authorization: Bearer $ADMIN_READ_TOKEN" https://hekineitor.onrender.com/api/admin/works_health
curl -H "Authorization: Bearer $ADMIN_READ_TOKEN" https://hekineitor.onrender.com/api/admin/audit_log
curl -H "Authorization: Bearer $ADMIN_READ_TOKEN" https://hekineitor.onrender.com/api/admin/maintenance_checklist
curl -H "Authorization: Bearer $ADMIN_READ_TOKEN" https://hekineitor.onrender.com/api/admin/matrix_health
curl -H "Authorization: Bearer $ADMIN_READ_TOKEN" https://hekineitor.onrender.com/api/admin/funnel_metrics
curl -H "Authorization: Bearer $ADMIN_READ_TOKEN" https://hekineitor.onrender.com/api/admin/player_fetishes
curl -H "Authorization: Bearer $ADMIN_READ_TOKEN" https://hekineitor.onrender.com/api/admin/promoted_fetish_history
curl -H "Authorization: Bearer $ADMIN_READ_TOKEN" https://hekineitor.onrender.com/api/admin/question_events
curl -H "Authorization: Bearer $ADMIN_READ_TOKEN" https://hekineitor.onrender.com/api/admin/share_events
curl -H "Authorization: Bearer $ADMIN_READ_TOKEN" https://hekineitor.onrender.com/api/admin/share_notes
curl -H "Authorization: Bearer $ADMIN_READ_TOKEN" https://hekineitor.onrender.com/api/admin/fetish_log_rows
curl -H "Authorization: Bearer $ADMIN_READ_TOKEN" https://hekineitor.onrender.com/api/admin/recent_fetish_ranking
curl -H "Authorization: Bearer $ADMIN_READ_TOKEN" https://hekineitor.onrender.com/api/admin/export_stats_history
curl -H "Authorization: Bearer $ADMIN_READ_TOKEN" https://hekineitor.onrender.com/api/admin/matrix_backups
curl -H "Authorization: Bearer $ADMIN_READ_TOKEN" https://hekineitor.onrender.com/api/admin/works_link_queue
```

CSV系の読み取りも同じトークンで取得できます。

## できないこと

以下は引き続き `ADMIN_PASS` のBasic認証が必要です。

- パラメータ変更
- matrix import / restore
- 性癖追加・編集・削除・統合
- 学習OFFテストプレイ開始/終了
- share note更新
- その他POST/PUT/PATCH/DELETE系の管理操作

## ローテーション

トークンを渡した相手の作業が終わったら、Renderで `ADMIN_READ_TOKEN` を更新して再起動してください。漏洩時も同じ手順で無効化できます。

## Displayed result exposure ranking

Use this endpoint when checking what users actually saw as their final result:

```sh
curl -H "Authorization: Bearer $ADMIN_READ_TOKEN" \
  "https://hekineitor.onrender.com/api/admin/result_exposures?days=7&top_n=20"
```

It returns aggregate counts only. It does not include IP address, User-Agent, session id, tokens, or raw URLs.

For deploy cutover checks, use the recent safe event endpoint. It returns only timestamp, result id/name, rank, probability, and source:

```sh
curl -H "Authorization: Bearer $ADMIN_READ_TOKEN" \
  "https://hekineitor.onrender.com/api/admin/result_exposures/recent?limit=20"
```

Backfill preview is read-only and available through the same token:

```sh
curl -H "Authorization: Bearer $ADMIN_READ_TOKEN" \
  "https://hekineitor.onrender.com/api/admin/result_exposures/backfill?max_events=1000"
```

Applying the backfill is a POST management action and still requires Basic admin authentication plus CSRF; the read token cannot apply it.
