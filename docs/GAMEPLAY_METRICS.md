# ゲームプレイ指標

ゲームループの率はschema version 2の`diagnosis_summary`だけから計算します。細かな操作イベントはデバッグ用に残しますが、異なる診断の開始と完了をイベント件数だけで結合しません。

## 匿名summary契約

診断開始時にFlask session内へ一時的な集計状態を作り、完了、離脱、再開始、破棄のいずれかでsummaryを1件だけ保存して状態を消します。永続的なuser/session/run ID、IP、User-Agent、自由記述、回答値は保存しません。ページ離脱時は`sendBeacon`を使い、届かなかった場合も同じsessionで次に開始した時に直前summaryを確定します。

全イベントに次を付けます。

- `schema_version: 2`
- `release`: `RENDER_GIT_COMMIT`、次に`RELEASE_VERSION`、ローカルは`dev`
- UTCの`timestamp`

summaryは`summary_status`、`retry_kind`、`answered_count`、`result_reached`、`result_id`、`continued`、`feedback_outcome`、`correction_count`、`work_impressions`、`work_clicks`、`question_repeats`を持ちます。値はallowlistまたは上限付き整数です。

## 指標と分母

- 結果到達率: `result_reached=true / summary_total`
- 通常再挑戦率・除外再挑戦率: 各`retry_kind / summary_total`
- 追加質問率: `continued=true / result_reached=true`
- feedback完了率: `feedback_outcomeあり / result_reached=true`
- おすすめ作品CTR: summary内`work_clicks / work_impressions`
- 質問重複率: summary内`question_repeats / answered_count`

`work_impression`はカードの50%以上がviewportへ入った時だけclientが送り、同じ結果描画内では安定した`work_id`/`edition_id`で重複排除します。`work_click`も同じゲームプレイ仕様へ送り、従来のshare analyticsとは用途を分けます。

## 管理APIと不変条件

- `GET /api/admin/gameplay_events?limit=5000`: version 2集計、release別集計、legacy、直近イベント
- `GET /api/admin/gameplay_events/summaries.csv`: summaryだけのCSV export
- `/api/admin/operations_snapshot`: `gameplay_events_summary`に同じレポート

`feedback_without_result`（feedback summary数が結果到達数を超える）、`work_clicks_exceed_impressions`、feedbackなしの訂正、結果なしの続行・作品表示を不変条件違反として返します。全体だけでなくrelease別にも判定するため、あるreleaseの異常が別releaseの結果数で相殺されません。`schema_version`のない既存履歴は`legacy.metrics_trusted=false`へ分離し、新指標へ混ぜません。release識別子はcommit SHAに加え、`2026.08.09`のような`.`区切りversionも保持します。

## 保存先・保持・プライバシー

- PostgreSQL: 汎用`analytics_events`に同じJSON payloadを保存する。`(event_type, timestamp)` indexを作り、gameplay書き込み時に1プロセス1日1回、90日より古いgameplay行を削除する。
- ローカル/DB障害fallback: `data/gameplay_events.jsonl`。5 MiBを超えると`.1`へローテーションし、最大2世代（約10 MiB）に制限する。
- test-playでは記録しない。計測失敗はゲーム進行を止めない。
- CSVを外部共有する場合も、必要期間のsummaryだけを扱い、自由記述や他ログと個人単位で結合しない。

`GET /api/admin/gameplay_events`のstorage statusに実際の保持方式を返します。PostgreSQLとJSONLはpayload契約が同一で、保存先を切り替えてもschema versionとreleaseの意味は変わりません。

## 移行・rollback・運用

1. デプロイ後、version 2 summaryが増え、`legacy.total`は増えないことを確認する。
2. `invariants.valid=true`、release別`summary_total`、結果到達率、feedback完了率を確認する。
3. CSVを取得し、1行が1診断終了で、永続識別子がないことをspot checkする。
4. PostgreSQLではstorage statusが`retention.mode=age`, `days=90`であることを確認する。
5. 異常時は旧releaseへrollbackできる。旧releaseが出すversionなしイベントはlegacyへ隔離されるため、version 2の分母を破壊しない。履歴を書き換えるmigrationは行わず、修正releaseをforward deployする。

旧イベントのbackfillは行いません。診断境界を復元できないため、推測でsummaryへ変換すると誤った率を作るためです。
