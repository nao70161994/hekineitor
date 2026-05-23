# Share Event Tracking

ヘキネイターの拡散導線を改善するための軽量イベントログです。診断、共有、OGP 表示の流れだけを集計し、個人識別は行いません。

## 記録するフィールド

- `timestamp`: UTC ISO 秒精度
- `event_name`: 許可されたイベント名のみ
- `result_name`: 診断結果名。最大 80 文字
- `channel`: `button`, `web_share`, `clipboard`, `x`, `result_page`, `ogp`
- `success`: `true`, `false`, `null`

## 記録しないもの

- IP アドレス
- User-Agent
- Cookie / session ID
- localStorage ID
- ユーザー識別子
- 回答内容

## イベント

- `share_button_click`: 結果画面の共有ボタン押下
- `web_share_success`: Web Share API 成功
- `web_share_failure`: Web Share API 失敗/キャンセル
- `copy_success`: クリップボードコピー成功
- `copy_failure`: クリップボードコピー失敗
- `x_share_click`: X 共有 intent 起動
- `result_page_view`: `/r` 結果共有ページ表示
- `ogp_png_view`: `/ogp.png` 表示
- `ogp_svg_view`: 既存 `/ogp` SVG 表示

## 保存先

既存の local/testing/production のログ分離に合わせ、`SHARE_EVENT_LOG_PATH` があればその JSONL に保存します。未指定時は `data/share_events.jsonl` です。

## API

- `POST /api/share_event`: クライアントからの fire-and-forget 記録用。失敗しても共有 UX は止めません。
- `GET /api/admin/share_events?limit=500`: 管理者向けの簡易集計。イベント別、チャネル別、成功/失敗数、直近 20 件を返します。

## 運用メモ

`/api/share_event` は未知のイベントや保存失敗を `recorded: false` として扱います。クライアントはレスポンスに依存しないため、ログ保存障害が診断や共有を止めることはありません。

## 管理画面表示

`/admin` の「拡散イベント」カードでは、最新 `1000` 件を対象に以下を確認できます。

- 共有ボタン押下
- Web Share 成功
- コピー成功
- X 共有クリック
- OGP 表示数
- 結果ページ表示数
- 成功/失敗/不明の件数
- 直近の日次イベント数
- チャネル別イベント数
- 結果別シェアランキング
- 結果別 OGP / 結果ページ / X / Web Share / コピー数
- 結果別の結果ページ→共有ボタン率 / 共有成功率

API の `GET /api/admin/share_events?limit=500` は既存の `total`, `by_event`, `by_channel`, `success`, `recent` を維持しつつ、`metrics`, `daily`, `ranking` を追加で返します。


## 期間フィルタとCSV

`GET /api/admin/share_events` は任意で `days`, `since`, `until`, `limit` を受け取ります。未指定時は従来通り最新ログを集計します。

- `days`: 読み込んだログ内の直近日数
- `since`: `YYYY-MM-DD` 以降
- `until`: `YYYY-MM-DD` 以前
- `limit`: 読み込み件数上限

CSV は以下で取得できます。

- `/api/admin/share_events/ranking.csv`
- `/api/admin/share_events/daily.csv`

どちらも同じ期間フィルタ query を受け取ります。
