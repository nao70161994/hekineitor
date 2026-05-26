# 質問分析ダッシュボード

管理画面の「質問分析ダッシュボード」は、質問ごとの刺さり方と離脱を軽量イベントで確認するための運用ビューです。

## 記録するイベント

- `question_shown`: 質問が表示された
- `question_answered`: YES/NO/不明などの回答が送られた
- `question_dropoff`: 診断途中で離脱が記録された
- `question_result_contribution`: 結果表示時に理由として採用された質問

保存先は `QUESTION_EVENT_LOG_PATH` があればそのパス、未指定なら `data/question_events.jsonl` です。保存するのは質問ID、質問文、カテゴリ、回答値、結果名、timestamp 程度に限定し、IP、User-Agent、ユーザーID、session ID は保存しません。

## 管理画面で見えるもの

- 質問表示回数
- YES率 / NO率 / 未回答率
- 離脱率
- 結果寄与ランキング
- カテゴリ別出現率
- カテゴリ別YES率 / 離脱率
- `relation` / `attachment` 偏重警告

## CSV

- `/api/admin/question_events/questions.csv`
- `/api/admin/question_events/category.csv`

どちらも管理者認証必須です。

## 注意

この分析は観測専用です。推論アルゴリズム、matrix、prior、DB schema は変更しません。結果の偏りを見つけた場合は、まず質問カテゴリ・序盤質問・質問文の追加や整理で改善してください。

## 本番分析に必要な確認手順

本番データを分析するときは、ローカルJSONではなく本番の管理画面または管理APIを確認します。

1. `/api/admin/preflight` を開き、次の行数を確認します。
   - `analysis_stats_history_rows`: 結果分布・フィードバック分析に使う履歴日数
   - `analysis_share_events_rows`: 結果ページ表示、OGP表示、Xクリック、コピー、Web Share分析に使うJSONL行数
   - `analysis_question_events_rows`: 質問表示、回答、離脱、結果寄与分析に使うJSONL行数
2. 管理画面の「分析ログ蓄積状況」を確認します。
   - `question_events` が50行未満なら質問別離脱率・YES/NO偏り・結果寄与は参考にしない
   - `share_events` が20行未満なら結果別シェア率・チャネル別評価は参考にしない
3. 取得元を確認します。
   - result distribution: Engine `stats_history` / `fetish_log`
   - feedback / confirm / wrong: Engine `fetish_log` / `stats_history`
   - share analytics: JSONL `share_events`
   - question analytics: JSONL `question_events`
4. 本番分析で使うAPI。
   - `/api/admin/share_events`
   - `/api/admin/question_events`
   - `/api/admin/fetish_log_rows`
   - `/api/admin/export_stats_history`

`share_events` と `question_events` はDB schemaを増やさず軽量JSONLで保存します。Renderの永続ディスク設定やログパス環境変数を変更する場合は、preflightの行数が継続して増えることを確認してください。
