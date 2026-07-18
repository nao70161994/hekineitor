# Documentation index

このディレクトリの文書は、実装と一緒に更新する現行文書です。完了した計画や過去の実行記録は[`archive/`](archive/README.md)に保存し、現在の仕様判断には使用しません。

## Architecture and contracts

- [`APP_BOOTSTRAP.md`](APP_BOOTSTRAP.md): Flask composition rootと依存関係の組み立て
- [`ENGINE_FACADE_CONTRACT.md`](ENGINE_FACADE_CONTRACT.md): `engine` packageの公開互換性と状態所有権
- [`QA.md`](QA.md): 自動検証コマンドと手動QAの現行方針
- [`adr/`](adr/README.md): 変更時にも維持するアーキテクチャ判断

## Operations and release

- [`OPERATIONS_MONITORING.md`](OPERATIONS_MONITORING.md): health check、監視、バックアップ
- [`RELEASE_CHECKLIST.md`](RELEASE_CHECKLIST.md): リリース前後の確認
- [`REVIEW_CHECKLIST.md`](REVIEW_CHECKLIST.md): レビュー観点
- [`ADMIN_READ_ACCESS.md`](ADMIN_READ_ACCESS.md): 管理系read access
- [`PROMOTED_STATS_REPAIR.md`](PROMOTED_STATS_REPAIR.md): promoted stats修復手順
- [`ADSENSE_SETUP.md`](ADSENSE_SETUP.md): AdSense設定
- [`OGP_FONT_SETUP.md`](OGP_FONT_SETUP.md): OGPフォント設定

## QA and browser behavior

- [`LIGHTWEIGHT_E2E.md`](LIGHTWEIGHT_E2E.md): E2Eテストの責務分担
- [`MANUAL_DEVICE_QA.md`](MANUAL_DEVICE_QA.md): 実機QA
- [`MOBILE_QA.md`](MOBILE_QA.md): モバイル表示と操作
- [`OGP_QA.md`](OGP_QA.md): 外部サービスのOGP preview
- [`TEST_PLAY_MODE.md`](TEST_PLAY_MODE.md): test play mode

## Product and analytics

- [`BIAS_MITIGATION.md`](BIAS_MITIGATION.md) / [`RESULT_BIAS_MITIGATION.md`](RESULT_BIAS_MITIGATION.md): 診断結果の偏り対策
- [`FUNNEL_METRICS.md`](FUNNEL_METRICS.md): funnel指標
- [`QUESTION_ANALYTICS.md`](QUESTION_ANALYTICS.md): 質問分析
- [`QUESTION_CATEGORY_BALANCE.md`](QUESTION_CATEGORY_BALANCE.md): 質問カテゴリのバランス
- [`RESULT_ANALYTICS_LIFECYCLE.md`](RESULT_ANALYTICS_LIFECYCLE.md): result analyticsの保存期間
- [`SHARE_EVENT_TRACKING.md`](SHARE_EVENT_TRACKING.md): share event計測
- [`SHARE_IMPROVEMENT_NOTES.md`](SHARE_IMPROVEMENT_NOTES.md): share改善メモ
- [`SHARE_LINKS.md`](SHARE_LINKS.md): share link仕様
- [`MULTI_CORRECT_FEEDBACK_PLAN.md`](MULTI_CORRECT_FEEDBACK_PLAN.md): 複数正解feedbackの設計
- [`RECOMMENDED_WORKS_LIST.md`](RECOMMENDED_WORKS_LIST.md): 推薦作品リスト
- [`WORK_CATALOG.md`](WORK_CATALOG.md): 正規化作品catalogのデータ契約・生成・review方針
- [`PR_MAPPING.md`](PR_MAPPING.md): 過去の改善項目とPR対応表（履歴寄りの参照資料）

## 文書の更新ルール

- 現在の実装・運用手順はこの階層の文書へ反映します。
- 一時的な計画や実行ログは、完了後に`archive/`へ移動します。
- 長期的な設計判断はADRとして追加し、置き換え時は旧ADRを削除せず状態を更新します。
