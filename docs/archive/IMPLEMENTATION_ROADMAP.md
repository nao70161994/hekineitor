# ヘキネイター 神ゲー化 実装ロードマップ

このロードマップは、監査結果を安全なPR単位へ分割した実装計画です。

方針:

- まず壊れにくく、効果が大きい変更から入れる。
- `app.py` / `engine.py` / `static/app.js` の巨大分割は、テストを増やしてから段階的に進める。
- SNS共有、スマホ完走率、収益導線、再訪理由を優先する。
- `data/fetish_log.json` のような運用データを誤って混ぜない。

現状確認:

- `app.py`: 2327行。ルート、SEO、管理、推論補助、バックアップ処理が集中。
- `engine.py`: 2286行。事前確率、推論、学習、DB、分析が集中。
- `static/app.js`: 1057行。状態管理、API、描画、共有、PWA処理が集中。
- `templates/`: トップ、結果共有、性癖詳細、性癖一覧、統計、管理が存在。
- `tests/`: API/engine/script/smoke/e2e系のテストあり。
- 未コミットで出やすい既知差分: `data/fetish_log.json`。

## PR候補一覧

### PR-01

- 優先度: S
- 対象ファイル: `.gitignore`, `tests/test_script_safety.py`, `README.md`
- 修正内容: `data/fetish_log.json` を誤コミット対象から外す運用ルールを明文化し、必要ならローカル実行時は `data/fetish_log.local.json` を使う設計方針を追加する。まずは誤コミット防止のテストを追加する。
- 期待効果: 利用統計の誤コミットや本番データ混入を防ぐ。
- リスク: 既存の本番ログをGit管理している前提がある場合、運用変更が必要。
- テスト方法: `python3 -m unittest tests.test_script_safety`, `git status --short` でログ差分が混ざらないことを確認。
- 推奨コミットメッセージ: `Prevent accidental fetish log commits`

### PR-02

- 優先度: S
- 対象ファイル: `storage.py`, `engine.py`, `app.py`, `tests/test_app.py`
- 修正内容: `FETISH_LOG_PATH` または `APP_DATA_DIR` を導入し、テスト/ローカル/本番でログ保存先を分離できるようにする。
- 期待効果: テスト実行やローカル確認で実データJSONが汚れにくくなる。
- リスク: 保存先変更により既存ログが読めなくなる可能性。
- テスト方法: 一時ディレクトリを指定してプレイログがそちらへ保存されることを確認。
- 推奨コミットメッセージ: `Add configurable fetish log storage`

### PR-03

- 優先度: S
- 対象ファイル: `requirements.txt`, `app.py`, `templates/result_share.html`, `templates/fetish.html`, `tests/test_app.py`
- 修正内容: Pillowを追加し、`/ogp.png` で1200x630 PNGを生成する。`og:image` をSVGの `/ogp` から `/ogp.png` に切り替える。既存 `/ogp` は互換用に残す。
- 期待効果: X/LINE/Discordなどで画像プレビューが安定し、シェア率が上がる。
- リスク: 日本語フォントが環境にないと文字化けする可能性。
- テスト方法: `/ogp.png?f=NTR&p=82` が `image/png`、1200x630、200を返すことをテスト。
- 推奨コミットメッセージ: `Generate raster OGP preview images`

### PR-04

- 優先度: S
- 対象ファイル: `app.py`, `tests/test_app.py`, `README.md`
- 修正内容: PNG OGP用フォント検出を実装する。`Noto Sans CJK`, `DejaVuSans`, fallback の順で選択し、環境変数 `OGP_FONT_PATH` を許可する。
- 期待効果: 本番環境での日本語OGP崩れを防ぐ。
- リスク: Render等の環境でフォントが存在しない場合は代替表示になる。
- テスト方法: フォント未指定でも `/ogp.png` が生成されること、`OGP_FONT_PATH` 指定時に読み込むこと。
- 推奨コミットメッセージ: `Add robust OGP font selection`

### PR-05

- 優先度: A
- 対象ファイル: `static/app.js`, `templates/index.html`, `static/app.css`, `tests/test_e2e_smoke.py`
- 修正内容: 結果直後に「Xで見せる」「友達にも診断させる」を上部固定または結果名直下へ移動する。
- 期待効果: 結果を見た直後の共有率が上がる。
- リスク: 結果画面の情報量が増えすぎる可能性。
- テスト方法: 結果画面に共有CTAが表示されることをE2E/DOMテストで確認。
- 推奨コミットメッセージ: `Prioritize result sharing CTA`

### PR-06

- 優先度: A
- 対象ファイル: `static/app.js`, `static/app.css`, `templates/index.html`
- 修正内容: 結果フィードバックを簡略化する。最初は「当たってる」「惜しい」「違う」の3ボタンを出し、詳細の○△×は任意展開にする。
- 期待効果: 結果後離脱を減らし、学習フィードバック数を増やす。
- リスク: 詳細な学習データの粒度が下がる。
- テスト方法: 3ボタンから既存 `/api/confirm` / `/api/teach` に正しく流れること。
- 推奨コミットメッセージ: `Simplify result feedback flow`

### PR-07

- 優先度: A
- 対象ファイル: `app.py`, `engine.py`, `static/app.js`, `static/app.css`, `tests/test_app.py`
- 修正内容: 途中演出用の `progress_message` をAPIレスポンスに追加し、5問目/10問目/接戦時/高確信時に表示する。
- 期待効果: 質問ループの単調さが減り、ゲームとしてのテンポが良くなる。
- リスク: メッセージが多すぎると邪魔になる。
- テスト方法: 回答回数に応じて `progress_message` が返るケースをテスト。
- 推奨コミットメッセージ: `Add mid-game progress moments`

### PR-08

- 優先度: A
- 対象ファイル: `engine.py`, `app.py`, `static/app.js`, `tests/test_engine.py`, `tests/test_app.py`
- 修正内容: 質問理由を返す `question_reason` を追加する。例: 「候補が接戦なのでここで見分けます」。
- 期待効果: AIが考えている感が出て、納得感が増す。
- リスク: 理由文が的外れだと逆に不自然。
- テスト方法: 接戦時に理由が返ること、通常時は空でも壊れないこと。
- 推奨コミットメッセージ: `Explain why questions are asked`

### PR-09

- 優先度: B
- 対象ファイル: `templates/index.html`, `static/app.css`, `static/app.js`
- 修正内容: スマホ結果画面を再構成する。ファーストビューは結果名、一致度、共有、フィードバックだけにし、詳細/関連/作品は折りたたむ。
- 期待効果: スクロール疲れが減り、結果後アクション率が上がる。
- リスク: 既存ユーザーが詳細情報を見つけにくくなる。
- テスト方法: モバイル幅で主要CTAが画面内に収まることをスクリーンショット確認。
- 推奨コミットメッセージ: `Optimize result screen for mobile`

### PR-10

- 優先度: B
- 対象ファイル: `static/app.js`, `static/app.css`
- 修正内容: 回答ボタンをスマホ下部に近づけ、親指操作しやすい間隔と高さに調整する。
- 期待効果: 長い診断でも操作疲れが減る。
- リスク: 小さい画面で質問文とのバランスが崩れる可能性。
- テスト方法: 360px幅/390px幅/430px幅で表示確認。
- 推奨コミットメッセージ: `Improve mobile answer ergonomics`

### PR-11

- 優先度: A
- 対象ファイル: `analytics.py`, `app.py`, `templates/admin.html`, `static/admin.js`, `tests/test_app.py`
- 修正内容: 誤診ペア分析を管理画面に追加する。例: 「NTRとヤンデレの誤診が多い」。
- 期待効果: 精度改善すべき箇所が見える。
- リスク: ログが少ない間はノイズが多い。
- テスト方法: サンプルログから誤診ペア集計が返ること。
- 推奨コミットメッセージ: `Add misdiagnosis pair analytics`

### PR-12

- 優先度: A
- 対象ファイル: `engine.py`, `analytics.py`, `app.py`, `templates/admin.html`, `tests/test_engine.py`
- 修正内容: 誤診ペアごとに、識別力の高い既存質問と不足している質問軸を提案する。
- 期待効果: 管理者が追加/修正すべき質問を判断しやすい。
- リスク: 自動提案を過信すると質問品質が落ちる。
- テスト方法: 近いベクトルの性癖ペアに対して候補質問が返ること。
- 推奨コミットメッセージ: `Suggest questions for confusing fetish pairs`

### PR-13

- 優先度: B
- 対象ファイル: `app.py`, `templates/admin.html`, `static/admin.js`, `check_works_links.py`, `tests/test_app.py`
- 修正内容: 作品URL修正キューを管理画面に追加する。URLなし、検索URL、ASIN不明を一覧化する。
- 期待効果: Amazonアソシエイト導線の品質が上がる。
- リスク: 管理画面の情報量が増える。
- テスト方法: URLなし/検索URLの件数とサンプルがAPIで返ること。
- 推奨コミットメッセージ: `Add works link maintenance queue`

### PR-14

- 優先度: B
- 対象ファイル: `fetch_kindle_asins.py`, `work_utils.py`, `tests/test_script_safety.py`
- 修正内容: ASIN反映スクリプトのdry-runレポートを強化し、検索URLから直リンク化できる候補を一覧出力する。
- 期待効果: 収益導線改善作業が安全に進む。
- リスク: Amazon検索依存で結果が不安定。
- テスト方法: ローカルprogressを使ったdry-runで候補が出ること。
- 推奨コミットメッセージ: `Improve ASIN backfill reporting`

### PR-15

- 優先度: A
- 対象ファイル: `app.py`, `routes/seo.py`, `tests/test_app.py`
- 修正内容: `app.py` からSEO/静的公開ルートを `routes/seo.py` に分離する。対象は `/robots.txt`, `/sitemap.xml`, `/fetishes`, `/stats`, `/r`, `/ogp`。
- 期待効果: `app.py` 分割の第一歩になり、SEO変更の巻き込みが減る。
- リスク: Flask app/engine参照の渡し方を誤るとルートが壊れる。
- テスト方法: 既存SEO/共有系テストが全て通ること。
- 推奨コミットメッセージ: `Extract SEO and sharing routes`

### PR-16

- 優先度: A
- 対象ファイル: `app.py`, `routes/game.py`, `tests/test_app.py`
- 修正内容: ゲームAPI `/api/start`, `/api/answer`, `/api/back`, `/api/continue`, `/api/confirm`, `/api/teach` を `routes/game.py` に分離する。
- 期待効果: ゲーム本体と管理/SEOの責務が分かれる。
- リスク: セッション、rate limit、engine参照の移動で回帰しやすい。
- テスト方法: APIフロー、back、confirm、continueの既存テストを全実行。
- 推奨コミットメッセージ: `Extract game API routes`

### PR-17

- 優先度: A
- 対象ファイル: `app.py`, `routes/admin.py`, `static/admin.js`, `static/admin_ops.js`, `tests/test_app.py`
- 修正内容: 管理画面と管理APIを `routes/admin.py` に分離する。
- 期待効果: 本番ユーザー向け処理と管理処理が明確に分かれる。
- リスク: 認証デコレータや監査ログの移動でバグが出やすい。
- テスト方法: 管理APIテスト、admin画面表示、監査ログ書き込みテスト。
- 推奨コミットメッセージ: `Extract admin routes`

### PR-18

- 優先度: A
- 対象ファイル: `engine.py`, `engine/inference.py`, `tests/test_engine.py`
- 修正内容: `posteriors`, `top_guess`, `get_answer_contributions` など純粋推論処理を分離する。
- 期待効果: 推論品質改善を安全に進めやすくなる。
- リスク: 既存Engine API互換を崩すと広範囲に影響。
- テスト方法: 既存 `tests/test_engine.py` が全て通ること。代表入力で結果一致を確認。
- 推奨コミットメッセージ: `Extract inference helpers from engine`

### PR-19

- 優先度: A
- 対象ファイル: `engine.py`, `engine/question_selection.py`, `tests/test_engine.py`
- 修正内容: `best_question`, `best_disambiguating_question`, 軸選択を分離する。
- 期待効果: 質問最適化の改善速度が上がる。
- リスク: 質問順が変わり、体験やテストが揺れる。
- テスト方法: 質問重複なし、候補接戦時の識別質問選択、idk連続時の挙動を確認。
- 推奨コミットメッセージ: `Extract question selection logic`

### PR-20

- 優先度: A
- 対象ファイル: `engine.py`, `engine/learning.py`, `tests/test_engine.py`, `tests/test_app.py`
- 修正内容: 正学習、弱学習、負学習、near miss学習を分離する。
- 期待効果: 学習ロジックのバグを局所化できる。
- リスク: 学習強度が変わると診断精度に影響。
- テスト方法: yes/total更新量、maybe、wrong、compoundの既存テストを確認。
- 推奨コミットメッセージ: `Extract learning update logic`

### PR-21

- 優先度: B
- 対象ファイル: `static/app.js`, `static/game_state.js`, `tests/test_e2e_smoke.py`
- 修正内容: グローバル変数 `_guessData`, `_excludedIds`, `_fetching` などを `gameState` に集約する。
- 期待効果: フロント状態破綻を減らす。
- リスク: イベント処理の参照漏れ。
- テスト方法: start, answer, back, result, retryのスモーク確認。
- 推奨コミットメッセージ: `Centralize client game state`

### PR-22

- 優先度: B
- 対象ファイル: `static/app.js`, `static/renderers.js`, `templates/index.html`
- 修正内容: 結果描画、質問描画、作品描画を関数/モジュールへ分離する。
- 期待効果: UI改善を安全に進めやすくなる。
- リスク: script読み込み順の問題。
- テスト方法: `node --check`, E2Eスモーク、結果表示のDOM確認。
- 推奨コミットメッセージ: `Extract client render helpers`

### PR-23

- 優先度: B
- 対象ファイル: `static/app.js`, `static/api_client.js`
- 修正内容: `apiFetch` と通信エラー処理を分離する。再試行やタイムアウト設定を一箇所に集める。
- 期待効果: 通信不整合やエラー表示の改善が容易になる。
- リスク: 既存呼び出しのbody/timeout指定漏れ。
- テスト方法: network error mock、440、500、timeoutの挙動確認。
- 推奨コミットメッセージ: `Extract client API helper`

### PR-24

- 優先度: B
- 対象ファイル: `app.py`, `data/stats_history.json`, `templates/stats.html`, `tests/test_app.py`
- 修正内容: デイリー診断の下地として「今日の人気性癖」「今日の診断数」を統計ページに追加する。
- 期待効果: 再訪理由とSNS投稿ネタが増える。
- リスク: 統計データが少ない日は表示が薄い。
- テスト方法: stats_historyあり/なしの両方で表示確認。
- 推奨コミットメッセージ: `Add daily stats highlights`

### PR-25

- 優先度: B
- 対象ファイル: `static/app.js`, `templates/index.html`, `static/app.css`
- 修正内容: 診断履歴を「性癖コレクション」風に表示し、過去結果から詳細ページへ飛べるようにする。
- 期待効果: リプレイ性と自己分析感が上がる。
- リスク: ローカルストレージ肥大化。
- テスト方法: 履歴保存、表示、削除、詳細リンクを確認。
- 推奨コミットメッセージ: `Turn history into result collection`

### PR-26

- 優先度: B
- 対象ファイル: `static/app.js`, `static/app.css`
- 修正内容: 結果に称号を追加する。例: 高一致度なら「完全看破」、複合なら「混沌型」。
- 期待効果: スクショ/シェアしたくなる要素が増える。
- リスク: 文言が寒いと逆効果。
- テスト方法: 確率/複合/低確信度ごとに称号が出ること。
- 推奨コミットメッセージ: `Add shareable result titles`

### PR-27

- 優先度: B
- 対象ファイル: `app.py`, `templates/result_share.html`, `static/app.js`, `tests/test_app.py`
- 修正内容: `/r` の結果URLを `fid` ベースに寄せ、名前/説明はサーバー側で引く。自由入力クエリは後方互換にする。
- 期待効果: 共有URLの改ざんや低品質ページ生成を減らせる。
- リスク: 複合結果の表現がやや複雑。
- テスト方法: `fid=0`, 旧 `f=NTR`, 不正fidの3ケース。
- 推奨コミットメッセージ: `Use stable IDs for result share pages`

### PR-28

- 優先度: C
- 対象ファイル: `app.py`, `templates/compatibility.html`, `static/app.js`, `tests/test_app.py`
- 修正内容: 2人の診断結果を入力して相性診断するページを追加する。
- 期待効果: 友達に送る理由が増え、拡散しやすくなる。
- リスク: 相性ロジックが浅いと一発ネタで終わる。
- テスト方法: 2つのfetish_idから相性スコアと説明が返ること。
- 推奨コミットメッセージ: `Add compatibility diagnosis page`

### PR-29

- 優先度: C
- 対象ファイル: `app.py`, `templates/bingo.html`, `static/app.js`, `static/app.css`
- 修正内容: 性癖ビンゴを追加する。結果や一覧からビンゴカードを生成できるようにする。
- 期待効果: SNSバズ用コンテンツになる。
- リスク: 本体診断から離れすぎる可能性。
- テスト方法: ビンゴページ表示、カード生成、シェアリンク確認。
- 推奨コミットメッセージ: `Add fetish bingo experience`

### PR-30

- 優先度: C
- 対象ファイル: `app.py`, `templates/rankings.html`, `tests/test_app.py`
- 修正内容: 人気ランキング、正解率ランキング、急上昇ランキングを公開ページ化する。
- 期待効果: SEO入口と再訪理由が増える。
- リスク: データが少ないとランキングが偏る。
- テスト方法: ランキングページが空データでも壊れないこと。
- 推奨コミットメッセージ: `Add public fetish rankings`

## 実装順序

1. PR-01: 誤コミット防止
2. PR-02: ログ保存先分離
3. PR-03: PNG OGP
4. PR-04: OGPフォント安定化
5. PR-05: 結果共有CTA強化
6. PR-06: 結果FB簡略化
7. PR-07: 途中演出
8. PR-08: 質問理由表示
9. PR-09: スマホ結果最適化
10. PR-10: スマホ回答操作最適化
11. PR-11: 誤診ペア分析
12. PR-12: 質問候補自動提案
13. PR-13: 作品URL修正キュー
14. PR-14: ASIN backfill強化
15. PR-15: SEO/共有ルート分離
16. PR-16: ゲームAPI分離
17. PR-17: 管理ルート分離
18. PR-18: 推論ロジック分離
19. PR-19: 質問選択分離
20. PR-20: 学習ロジック分離
21. PR-21: クライアント状態管理分離
22. PR-22: クライアント描画分離
23. PR-23: クライアントAPI分離
24. PR-24: デイリー統計
25. PR-25: 性癖コレクション
26. PR-26: 結果称号
27. PR-27: IDベース共有URL
28. PR-28: 相性診断
29. PR-29: 性癖ビンゴ
30. PR-30: 公開ランキング

## 最初に着手すべき5件

1. PR-01: `data/fetish_log.json` 誤コミット防止
2. PR-02: ログ保存先分離
3. PR-03: PNG OGP生成
4. PR-04: OGPフォント安定化
5. PR-05: 結果共有CTA強化

理由:

- PR-01/02は運用事故を防ぐ土台。
- PR-03/04はSNS拡散のボトルネックを直接潰す。
- PR-05は実装が小さく、共有率に効く。

## 寝てる間にgoalへ任せるならどこまでやらせるべきか

任せる範囲:

- PR-01からPR-05まで。

条件:

- 1 PR = 1 commitで進める。
- 各PRごとに `sh scripts/check.sh` を実行する。
- `data/fetish_log.json` は絶対にコミットしない。
- PNG OGPで新規依存を入れる場合は `requirements.txt` とCI成功まで含める。
- Pillow導入で本番フォントが不安な場合は、`OGP_FONT_PATH` 対応まで同時に入れる。

任せない方がよい範囲:

- `app.py` / `engine.py` の大規模分割。
- 結果FB簡略化以降のUX変更。
- 誤診ペア分析や質問候補自動提案。

理由:

- 巨大分割や推論変更は、設計判断と回帰確認が多い。
- まずは運用事故防止とSNS拡散の基礎を固める方が安全。

## 完了判定

各PRは以下を満たしてからマージする。

- `sh scripts/check.sh` が通る。
- 変更対象に応じた単体テストが追加されている。
- `git status --short` に意図しないデータ差分がない。
- スマホUI変更は360px幅と390px幅で目視確認する。
- 共有/SEO変更は生成HTMLのメタタグとレスポンスヘッダを確認する。
