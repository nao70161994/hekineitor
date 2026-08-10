# 質問分析ダッシュボード

管理画面の「質問分析ダッシュボード」は、質問ごとの回答傾向・離脱・結果寄与に加え、未学習質問がfeedbackによって育っているかを確認する読み取り専用の運用ビューです。

質問文の設計方針は `docs/QUESTION_DESIGN.md` を参照してください。質問は結果を直接確認するものではなく、複数候補を横断する間接的・抽象的な潜在軸として設計します。

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
- posterior discrimination、初期疑似観測を除いたlearned discrimination、未学習質問の成熟度

## 無信号質問とcold-startの扱い

全候補で厳密に `P(YES)=0.5` かつ `learning_scale_neutral` の印がない既存質問は、学習予定の質問ではなく `legacy_no_signal` として扱います。通常選択、後半の候補識別、低露出軸、除外再挑戦、追加質問、IDK回復のすべてから安全に除外します。質問文から妥当な広範囲の初期シグナルをレビューできた場合だけmatrixへ付与し、単一結果へ直結するseedは作りません。

`learning_scale_neutral: true` の質問（現在はQ143〜Q152）だけが意図的なcold-startです。未成熟な間も1診断につき最大1問だけ探索でき、回答と結果feedbackによるmatrix学習を受けます。上限は全質問選択経路で共通です。

成熟度は次のルールです。

- `collecting`: matrixの初期重みを超えたfeedback相当量が20未満。
- `learning`: feedback相当量が20以上で、learned discriminationが `0.015` 以上 `0.04` 未満。探索枠に残る。
- `mature`: feedback相当量が20以上かつlearned discriminationが `0.04` 以上。cold-start枠を卒業して通常選択へ自動移行する。
- `needs_review`: feedback相当量が20以上あるのに、learned discriminationが `0.015` 未満。通常・探索の双方から除外する。

`matrix_feedback_equivalent` は各候補セルの `total - 4` の合計で、イベントログの件数とは別物です。learned discriminationは各候補の初期疑似観測（total 4 / yes 2）を差し引き、実際に学習されたYES率の候補間weighted mean absolute deviationを測ります。posterior discriminationは現時点の推論列の分離度を診断用に残しますが、cold-start成熟度には使いません。選択可否と管理レポートは同じmatrix根拠を使います。

このfeedback eventは導入後から蓄積します。過去に行われた学習回数は復元しないため、導入直後の `collecting` は既存質問の品質が低いという意味ではありません。

## 読み取りAPIとCSV

- `/api/admin/question_events`: 集約、警告、`cold_start_summary`、`cold_start_questions`、`no_signal_summary`、`no_signal_questions`
- `/api/admin/operations_snapshot`: 運用snapshot内の同じcold-start集約
- `/api/admin/question_events/questions.csv`: 質問別CSV
- `/api/admin/question_events/category.csv`: カテゴリ別CSV

質問別CSVにはイベント由来のfeedback列に加え、`matrix_feedback_equivalent`、`discrimination`、`posterior_discrimination`、`learned_discrimination`、`learning_scale_neutral`、`cold_start`、`maturity`、`legacy_no_signal`、`selection_status` を含みます。すべて管理者認証必須です。

## 本番分析に必要な確認手順

1. `/api/admin/preflight` で `analysis_question_events_rows` を確認します。
2. `/api/admin/question_events` の `quality` を確認し、不審な同一秒burstが除外されていないか確認します。
3. `no_signal_summary.total` が意図せず増えていないことと、`cold_start_summary` の `collecting` / `learning` / `mature` / `needs_review` の推移を確認します。
4. `needs_review` が出た場合だけ、質問文、回答分布、対象結果、matrixの学習方向を個別にレビューします。
5. 長期的な外部レビューには `ADMIN_READ_TOKEN` を使い、読み取り専用APIだけを参照します。詳細は `docs/ADMIN_READ_ACCESS.md` を参照してください。

この分析は観測専用です。自動で推論アルゴリズム、matrix、prior、DB schemaを変更しません。
