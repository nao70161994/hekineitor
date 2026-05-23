# Test Play Mode

管理者だけが使える「学習OFFテストプレイ」モードです。診断の推論、質問、結果表示、共有、OGP、share analytics は通常通り動かし、学習データや診断精度に影響する保存だけを止めます。

## 起動方法

- 管理画面の「🧪 学習OFFでテストプレイ開始」から開始します。
- 管理画面の「テストプレイ終了」から通常モードへ戻します。
- URL query parameter だけでは有効化できません。
- `/admin/test_play/start` と `/admin/test_play/stop` は既存の管理者認証ガードを通ります。
- 有効化すると session に `heki_test_play_learning_disabled` を保存し、終了時に解除します。

## 画面表示

テストプレイ中のトップ画面には以下のバナーを表示します。

> 🧪 テストプレイ中：この診断は学習に反映されません

一般ユーザー向けの切り替え UI はありません。管理画面には現在の状態として「通常モード」または「学習OFFテストプレイ中」を表示します。

## 学習OFF中に保存しない処理

- `/api/confirm` の正解学習、複合共起学習、wrong log、quality feedback
- `/api/teach` の正解学習と correct log
- `/api/add_fetish` の新規性癖追加
- `/api/finalize_added` の新規性癖 boost、positive/negative/cooccurrence 学習
- 結果表示時の quality event 保存

## 学習OFF中も動く処理

- 推論
- 質問選択
- 結果表示
- 共有導線
- OGP表示
- share analytics
- 管理画面閲覧

## セキュリティと制約

- DB schema は変更しません。
- 個人情報、IP、User-Agent、ユーザーIDは追加保存しません。
- session key は `heki_test_play_learning_disabled` に限定します。
- フロントエンドだけではなく server 側で `learning_disabled` を判定します。
- API は成功扱いを維持し、保存だけを skip します。

## 文言出し分け

通常プレイでは従来通り「学習しました」系の文言を表示します。テストプレイ中に `learning_disabled: true` が返った場合だけ、完了文言を「保存せず確認しました」に切り替えます。


## 監査ログ表示

開始/終了時は既存の管理監査ログへ `test_play_start` / `test_play_stop` を記録します。記録する detail は `event_name` と `mode` のみです。request を渡さないため、IP、User-Agent、個人IDは保存しません。

管理画面には直近の開始/終了履歴を「テストプレイ開始/終了履歴」として表示します。表示項目は event_name、timestamp、mode 相当の状態文言です。
