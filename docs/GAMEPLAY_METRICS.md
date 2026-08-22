# ゲームプレイ指標

ゲームループの率はschema version 2の`diagnosis_summary`だけから計算します。細かな操作イベントはデバッグ用に残しますが、異なる診断の開始と完了をイベント件数だけで結合しません。

## 匿名summary契約

診断開始時にFlask session内へ一時的な集計状態を作り、完了、離脱、再開始、破棄のいずれかでsummaryを1件だけ保存して状態を消します。永続的なuser/session/run ID、IP、User-Agent、自由記述、回答値は保存しません。ページ離脱時は`sendBeacon`を使い、届かなかった場合も同じsessionで次に開始した時に直前summaryを確定します。

全イベントに次を付けます。

- `schema_version: 2`
- `release`: `RENDER_GIT_COMMIT`、次に`RELEASE_VERSION`、ローカルは`dev`
- UTCの`timestamp`

summaryは`summary_status`、`retry_kind`、`answered_count`、`result_reached`、`result_id`、`continued`、`feedback_outcome`、`correction_count`、`work_impressions`、`work_clicks`、`question_repeats`に加え、戻る・回答再照会・UIエラーの回数、共有の試行/完了、結果到達時間とsummary確定時間を持ちます。値はallowlist、真偽値、または上限付き整数です。開始時刻など集計途中の内部値はFlask session内だけに置き、永続eventやCSVには出しません。

## 指標と分母

- 結果到達率: `result_reached=true / summary_total`
- 通常再挑戦率・除外再挑戦率: 各`retry_kind / summary_total`
- 追加質問率: `continued=true / result_reached=true`
- feedback完了率: `feedback_outcomeあり / result_reached=true`
- おすすめ作品CTR: summary内`work_clicks / work_impressions`
- 質問重複率: summary内`question_repeats / answered_count`
- 戻る利用率: `back_count > 0 / summary_total`
- 回答再照会率: `answer_retries / answered_count`
- UIエラー影響率: `ui_errors > 0 / summary_total`
- 100回答あたりUIエラー: `ui_errors / answered_count * 100`
- 共有試行率: `share_attempted=true / result_reached=true`
- 共有完了率: `share_completed=true / share_attempted=true`
- 平均結果到達時間: `time_to_result_seconds`の平均。結果表示後の閲覧・共有時間を含めない
- 平均summary時間: `duration_seconds`の平均。開始から完了・離脱・再開始等で確定するまで

`work_impression`はカードの50%以上がviewportへ入った時だけclientが送り、同じ結果描画内では安定した`work_id`/`edition_id`で重複排除します。`work_click`も同じゲームプレイ仕様へ送り、従来のshare analyticsとは用途を分けます。

## 管理APIと不変条件

- `GET /api/admin/gameplay_events?limit=5000`: version 2集計、release別集計、legacy、直近イベント
- `GET /api/admin/gameplay_events/summaries.csv`: summaryだけのCSV export
- `/api/admin/operations_snapshot`: `gameplay_events_summary`に同じレポート

`feedback_without_result`（feedback summary数が結果到達数を超える）、`work_clicks_exceed_impressions`、feedbackなしの訂正、結果なしの続行・作品表示・結果到達時間、試行なしの共有完了を不変条件違反として返します。全体だけでなくrelease別にも判定するため、あるreleaseの異常が別releaseの結果数で相殺されません。`schema_version`のない既存履歴は`legacy.metrics_trusted=false`へ分離し、新指標へ混ぜません。release識別子はcommit SHAに加え、`2026.08.09`のような`.`区切りversionも保持します。

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

UI変更の効果はrelease別に比較します。少数サンプルでは結論を出さず、結果到達率だけでなく、平均結果到達時間、戻る利用率、回答再照会率、UIエラー影響率、共有試行/完了率を同時に確認します。実利用baselineが十分に溜まるまでは、質問数や終了条件をこの指標の推測だけで変更しません。

## Web Vitals

ブラウザが対応する場合、ページ離脱時に`web_vitals`を1件だけ送ります。LCP、INPはミリ秒、CLSは小数値を1000倍した整数として上限を付けます。URL、画面名、端末情報、session IDは送りません。管理レポートは全体とrelease別のp75、各指標の実サンプル数を返します。未対応browserの欠損値を0として扱わず、実値がある指標だけでp75を計算します。Core Web Vitalsの判定は十分な実利用サンプルを得てから行い、少数の開発・botアクセスだけで合否を決めません。

旧イベントのbackfillは行いません。診断境界を復元できないため、推測でsummaryへ変換すると誤った率を作るためです。
