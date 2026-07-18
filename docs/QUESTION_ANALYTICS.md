# 質問分析ダッシュボード

管理画面の「質問分析ダッシュボード」は、質問ごとの回答傾向・離脱・結果寄与に加え、未学習質問がfeedbackによって育っているかを確認する読み取り専用の運用ビューです。

## 記録するイベント

- `question_shown`: 質問が表示された
- `question_answered`: YES / NO / 不明などの回答が送られた
- `question_dropoff`: 診断途中で離脱が記録された
- `question_result_contribution`: 結果表示時に理由として採用された
- `question_feedback_learned`: 正解・不正解・惜しい等のfeedbackを受け、回答済み質問が学習処理に使われた

`question_feedback_learned` は、回答値が0（不明）の質問とテストプレイを除外します。`feedback_kind` と学習対象結果数 `target_count` は記録しますが、IP、User-Agent、ユーザーID、session IDは保存しません。

本番で `DATABASE_URL` が有効な場合は `analytics_events` テーブルへ保存します。`QUESTION_EVENT_LOG_PATH` が指定された場合、またはDB未使用のローカル環境ではJSONLへ保存します。

## 管理画面で見えるもの

- 質問表示回数
- YES率 / NO率 / 未回答率
- 離脱率
- 結果寄与ランキング
- カテゴリ別出現率、YES率、離脱率
- `relation` / `attachment` 偏重警告
- feedback learning回数、positive feedback回数、学習対象結果数
- discrimination（識別力）、feedback観測期間中の識別力差分、未学習質問の成熟度

## 未学習質問の扱い

初期の識別力が中立な質問は、同じ結果しか出ない状態を避けるための探索対象です。質問を無効化せず、実際の回答と結果feedbackを蓄積してmatrixを学習させます。`learning_scale_neutral: true` の質問（現在はQ143〜Q152）に加え、discriminationが `0.02` 以下の質問をcold-start監視対象として表示します。

成熟度は次のルールです。

- `collecting`: feedback learningが20回未満。警告せず、データ収集中として扱う。
- `learning`: feedback learningが20回以上で、discriminationが `0.02` 以上 `0.05` 未満。
- `mature`: discriminationが `0.05` 以上。
- `needs_review`: feedback learningが20回以上あるのに、discriminationが `0.02` 未満。

`needs_review` だけを警告対象にします。表示回数だけが多い質問やfeedbackがまだ少ない質問は異常扱いしません。しきい値は診断用であり、自動的に質問を停止したりmatrixを変更したりはしません。

このfeedback eventは導入後から蓄積します。過去に行われた学習回数は復元しないため、導入直後の `collecting` は既存質問の品質が低いという意味ではありません。

## 読み取りAPIとCSV

- `/api/admin/question_events`: 集約、警告、`cold_start_summary`、`cold_start_questions`
- `/api/admin/operations_snapshot`: 運用snapshot内の同じcold-start集約
- `/api/admin/question_events/questions.csv`: 質問別CSV
- `/api/admin/question_events/category.csv`: カテゴリ別CSV

質問別CSVには `feedback`、`positive_feedback`、`feedback_targets`、`feedback_discrimination_first`、`feedback_discrimination_latest`、`feedback_discrimination_delta`、`discrimination`、`learning_scale_neutral`、`cold_start`、`maturity` を含みます。すべて管理者認証必須です。

## 本番分析に必要な確認手順

1. `/api/admin/preflight` で `analysis_question_events_rows` を確認します。
2. `/api/admin/question_events` の `quality` を確認し、不審な同一秒burstが除外されていないか確認します。
3. `cold_start_summary` で `collecting` / `learning` / `mature` / `needs_review` の推移を確認します。
4. `needs_review` が出た場合だけ、質問文、回答分布、対象結果、matrixの学習方向を個別にレビューします。
5. 長期的な外部レビューには `ADMIN_READ_TOKEN` を使い、読み取り専用APIだけを参照します。詳細は `docs/ADMIN_READ_ACCESS.md` を参照してください。

この分析は観測専用です。自動で推論アルゴリズム、matrix、prior、DB schemaを変更しません。
