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
