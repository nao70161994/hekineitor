# へきネイター

性癖を当てるAkinator風Webアプリ。質問に答えると最も確率の高い性癖を診断する。

## アーキテクチャ

- `app.py` — Flask APIサーバー。サーバーサイドセッションで回答履歴を管理
- `engine.py` — ベイズ推論エンジン。情報利得で次の質問を選択
- `templates/index.html` — シングルページUI（PWA対応）
- `templates/admin.html` — 管理画面（学習データ量・質問無効化・診断ログ・相関分析・ヒートマップ・統合）
- `data/` — questions.json（93問）/ fetishes.json（99件）/ matrix.json・learned_priors.json（ローカル用・gitignore済み）

## データ永続化

- `DATABASE_URL` 環境変数があればPostgreSQL（Render）を使用
- なければ `data/` 以下にローカル保存（matrix.json / fetish_log.json / question_flags.json / config.json）
- DBテーブル: `fetishes`, `matrix`, `stats`, `fetish_log`, `sessions`, `config`, `stats_history`
- 起動時に fetishes.json・questions.json との差分を自動マイグレーション（新規追加のみ）

## 推論ロジック（engine.py）

- ナイーブベイズで事後確率を計算。`FETISH_PRIOR_WEIGHTS` をベースに診断ログから動的更新（60s TTL）
- 情報利得（エントロピー削減量）が最大の質問を次に選択
- 相関ペナルティ：中心化ベクトル（P−0.5）のコサイン類似度で既出質問との重複を最大40%割り引く
- `AXIS_INDIRECT_BONUS`：抽象軸・パーソナリティ軸に微小ボーナス（同スコアなら間接質問を優先）
- **終盤モード**（`FOCUS_THRESHOLD=0.40`）：1位確率が40%超で上位`FOCUS_TOP_N=6`件に絞った情報利得を計算
- **序盤ランダム化**（`EARLY_RANDOM_DEPTH=3`）：最初の3問は上位`EARLY_RANDOM_TOP_K=5`件からランダムに選択
- **UCB探索ボーナス**（`UCB_EXPLORE_C=0.05`）：使用回数が少ない質問にボーナス。`ask_count / n_fetishes` 正規化で性癖追加時に自動復活
- 確率が `GUESS_THRESHOLD=0.75` 超 or 質問数が `MAX_QUESTIONS=20` で診断確定
- **早期打ち切り**：`gap_ratio`（1位/2位の確率比）が高い場合に早期終了（4問以上で3倍差 or 8問以上で2.5倍差）
- **接戦抑制**：`gap_ratio < 1.8` かつ `count < 10` の場合は `effective_thr = min(guess_thr + 0.10, 0.90)` に引き上げ
- **わからない弱推論**：`ans == 0` を完全スキップせず `−0.05 × |P(yes)−0.5|` の微弱な否定的証拠として posteriors に加算
- わからない4連続で診断確定
- **複数worker対応**：DB使用時に `posteriors()` が5秒TTLでmatrixをリロード（`_MATRIX_RELOAD_INTERVAL`）
- **質問の無効化**：`disabled_questions` セットに含まれる質問は `best_question()` でスキップ。DB/JSONに永続化
- `learn(strength_factor)` で正解フィードバックをmatrixに反映（正解性癖を強化・他を弱化）
- `learn_negative()` で不正解フィードバック（対象性癖のみ弱く負学習、0.2×強度）
- `learn_cooccurrence(idx_a, idx_b, factor)` で共起した2性癖を相互強化（複合正解時に呼ぶ）
- `_learn_silent()` はlearn_countをカウントしない内部用（初期ブースト専用）
- 0.5/-0.5（どちらかといえば）の回答も強さに比例して学習
- `add_fetish()` で新しい性癖を追加。現在の回答から事後確率が最も高い既存性癖を自動でテンプレートに使用
- `boost_learn_new()` で新規追加性癖の初期ブースト（`_learn_silent` × 3 + `learn` × 1）
- `promote_fetish(old_id)` でプレイヤー追加性癖（ID≥10000）をシード性癖に格上げ（次の空きIDに変更）
- `capture_learned_priors()` で現在の P(yes) を `data/learned_priors.json` に保存。`_init_matrix_file` がこれを使ってDOMAIN_PRIORSより優先的に初期化
- `index_of(db_id)` でDB idから配列インデックスを取得
- `get_question_stats()` で質問ごとの識別力（disc）+ 無効化フラグ一覧を返す
- `get_fetish_log()` / `log_guessed/correct/wrong()` で診断ログを管理
- `get_correlation_stats()` で質問ペアのコサイン類似度上位30件を返す（管理画面用）
- `get_top_questions_per_fetish()` で各性癖のP(yes)が高い/低い質問TOP5を返す（DOMAIN_PRIORS整備用）
- `get_matrix_heatmap(n_fetishes, n_questions)` で上位N性癖×N質問の P(yes) グリッドを返す（管理画面ヒートマップ用）
- `merge_fetishes(id_keep, id_remove)` で2性癖のmatrixを加算して統合（DB/JSON両対応）
- `edit_fetish(fetish_id, name, desc)` で性癖の名前・説明を更新
- `get_stats_history(days)` で日別プレイ・学習回数を返す（stats_historyテーブル/JSON）
- `idk_streak` 連続時の軸切替：直近idkが同一軸に集中していればその軸を除外、複数軸混在ならabstract/personalityへ

## 質問の設計方針

93問を3層構造で設計：

1. **コンテンツ軸（0〜54）** — 力関係・禁断・年齢差・異種族など、作品・関係の特徴を直接聞く（55問）
2. **抽象軸（55〜62, 87〜92）** — 感情の方向性・激しさ・堕落・共依存・禁断感・守護・孤独・運命など、全性癖にまたがる汎用軸（14問）
3. **パーソナリティ軸（63〜86）** — 性癖から離れた間接的な質問（服装・嗜好・性格など）で性癖を間接推定（24問）

パーソナリティ軸の狙い：プレイヤー自身の属性や行動傾向から性癖を推定。「スカートよりズボンが好き？」「嫉妬しやすい？」など、性癖を直接聞かずに絞り込む。

## 診断結果の複合判定（app.py）

- `COMPOUND_RATIO=0.55`：2位が1位の55%以上なら複合（例：「SM × ヤンデレ」）
- `TRIPLE_RATIO=0.45`：3位が1位の45%以上なら三重複合
- `PROFILE_MIN_RATIO=0.25` / `PROFILE_MIN_PROB=0.08`：それ以下は「他に該当しそうなジャンル」に表示
- 診断結果に上位5件の確率バーグラフ（`top_chart`）を返す
- シェア文は常にヘキネイターが提示した性癖を使用

## 正誤フィードバックのフロー

- `_learn_factor(answers, total_n)` ヘルパー（app.py）：確信度（0.75/top_p）× 1/√n のスケーリング係数を返す

診断結果画面で主診断・複合それぞれに **○/△/×** の3択をつける：

| 選択 | 意味 | 学習 |
|---|---|---|
| ○ | 正解 | 即正学習。その後「追加したい性癖があれば選べます（任意）」画面を表示 |
| △ | 外れだが正解不明 | 負学習のみ。「正解があれば選べます（任意）」画面を表示 |
| × | 外れ・正解を選びたい | 負学習＋「正解の性癖を選んでください」画面を表示 |

- 複合正解（複数のIDが○）時は `learn_cooccurrence()` で共起パターンを強化
- `/api/confirm` の `add_only: true` フラグ：正解追加目的のリスト取得（wrong_db_ids を設定しない）
- 正解候補リストは事後確率上位**20件**・診断済み性癖を除外

## セッション管理

- サーバーサイドセッション（`_ServerSessionInterface`）を使用。クッキーにはUUIDのみ保存
- DB使用時：`sessions` テーブルに JSON として保存（TTL 24時間）
- ローカル時：`_LOCAL_SESSIONS` インメモリdict（最大2000件、古いものは自動削除）
- セッション切れ（サーバー再起動後等）は HTTP 440 を返し、フロントが自動リスタートを促す

## 「別の性癖を探す」モード

- 結果画面・完了画面の「別の性癖を探す →」ボタンで診断済み性癖を除外してリスタート
- `/api/start` に `exclude_ids` 配列を渡すとセッションに保存
- `_compute_guess()` で excluded fetishes を末尾に退けて診断

## APIエンドポイント

| メソッド | パス | 説明 |
|---|---|---|
| POST | /api/start | セッション開始。`exclude_ids` 配列で除外性癖を指定可 |
| POST | /api/answer | 回答を受け取り次の質問 or 診断結果を返す |
| POST | /api/back | 直前の回答を取り消して前の質問に戻る |
| POST | /api/confirm | 診断結果の正誤をフィードバック（correct=false時に外れリスト上位20件を返す。add_only=trueで負学習なし） |
| POST | /api/teach | 正解の性癖を教える（学習） |
| POST | /api/add_fetish | 新しい性癖を追加（作成のみで学習はしない）。`confirmed=true` で確定 |
| POST | /api/finalize_added | 追加済み項目をまとめて学習（完了ボタン押下時）。複合正解は共起強化も実施 |
| DELETE | /api/fetish/&lt;id&gt; | プレイヤー追加性癖を削除（ID ≥ 10000 のみ可） |
| GET  | /admin | 管理画面（Basic認証必須） |
| POST | /api/admin/toggle_question/&lt;id&gt; | 質問の有効/無効を切り替え（Basic認証必須） |
| POST | /api/admin/params | 推論パラメータを更新（Basic認証必須） |
| POST | /api/admin/cleanup_sessions | 期限切れセッションを手動削除（Basic認証必須） |
| POST | /api/admin/add_fetish | 管理者が性癖を手動追加（Basic認証必須） |
| POST | /api/admin/capture_priors | 現在の P(yes) を learned_priors.json に保存（Basic認証必須） |
| POST | /api/admin/promote_fetish/&lt;id&gt; | プレイヤー追加性癖をシード性癖に格上げ（Basic認証必須） |
| POST | /api/admin/edit_fetish/&lt;id&gt; | 性癖の名前・説明を編集（Basic認証必須） |
| POST | /api/admin/merge_fetishes | 2性癖のmatrixを統合（`id_keep`, `id_remove`）（Basic認証必須） |
| GET  | /api/admin/export_matrix | matrix全体をJSON形式でダウンロード（Basic認証必須） |
| GET  | /api/admin/export_log | 診断ログをCSV形式でダウンロード（Basic認証必須） |
| POST | /api/resume | localStorageに保存した回答ペアからセッションを復元 |
| POST | /api/continue | 診断確定後に追加質問を継続（閾値+0.20で続行） |
| GET  | /health | DB接続・性癖数・質問数を返す（Render監視用） |

回答値: `1`=はい / `0.5`=どちらかといえばはい / `0`=わからない / `-0.5`=どちらかといえばいいえ / `-1`=いいえ

## 管理画面（/admin）

- 学習データ量一覧（性癖別）+ 過去30日の時系列グラフ（7日/30日切替）
- プレイヤー追加性癖一覧 + インライン編集・格上げ・削除ボタン
- シード性癖編集フォーム（IDで指定して名前・説明変更）
- 質問の識別力一覧 + **有効/無効トグル** + disc値でソート可
- **診断ログ**：性癖別の診断回数・正解数・外れ数・正解率。wrong率60%超でハイライト。CSVエクスポートあり
- **DOMAIN_PRIORSサジェスト**：各性癖のP(yes)が高い/低い質問TOP5（学習済みmatrixから自動生成）
- 質問間の相関分析（コサイン類似度上位30ペア）
- **Matrix ヒートマップ**：上位20性癖×20質問のP(yes)を色可視化
- **性癖統合フォーム**：2性癖のmatrixを加算して1つにマージ
- 推論パラメータ更新 / セッションクリーンアップ / 手動性癖追加 / learned_priorsキャプチャ
- matrix JSONエクスポート

## 環境変数

| 変数名 | 説明 | デフォルト |
|---|---|---|
| `SECRET_KEY` | Flaskセッション署名キー | ハードコード値（本番では必須） |
| `DATABASE_URL` | PostgreSQL接続URL | なし（ローカルJSON使用） |
| `ADMIN_USER` | /admin のBasic認証ユーザー名 | `admin` |
| `ADMIN_PASS` | /admin のBasic認証パスワード | なし（未設定時503） |

## 実行

```bash
# ローカル
python app.py

# 本番（Render）。複数workerも可（DBの5秒TTLリロードで整合性を確保）
gunicorn app:app --workers 2 --threads 4
```

## プレイヤー追加性癖

- `PLAYER_FETISH_BASE_ID = 10000`（engine.pyで定義）以上のIDがプレイヤー追加性癖
- シードとIDが競合しない設計
- DBの `fetishes` テーブルに永続化
- 管理画面でプレイヤー追加分を一覧表示・削除・シード格上げ可能

## バージョン管理

- `app.py` の `DISPLAY_VERSION` でタイトルに表示するバージョン番号を管理（現在 `v1.2.0`）
- ブラウザタブに「へきネイター v1.2.0」と表示される

## 注意

- `data/matrix.json`・`data/learned_priors.json` は `.gitignore` 済み（学習データをgitに含めない）
- Termux環境では長いコマンドはスクリプトファイルに書いて実行する
- シードの性癖をDBに登録せずJSONで管理しているのは、JSONが「正解」でありDB側はfetish_idを参照するだけのため（シード増減もマイグレーションで自動追従）
- テストは `python tests/test_app.py` で実行（現在46テスト）
- `data/stats_history.json` は `.gitignore` 済み
- `DISPLAY_VERSION` は現在 `v1.2.1`
- index.html: キーボードショートカット（1〜5で回答、Backspaceで戻る）
- index.html: localStorage に `heki_draft` として回答を自動保存。セッション切れ後も「途中から再開」可能
- index.html: 結果画面の「もう少し続ける」ボタンで診断確定後も追加質問できる
