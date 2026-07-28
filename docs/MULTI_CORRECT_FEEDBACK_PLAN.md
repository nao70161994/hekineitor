# Multi-Correct Feedback

Hekineitorでは近い複数の診断結果が同時に正解になり得ます。結果カードの詳細フィードバックは、表示された全項目を○・△・×のいずれかへ分類し、1回の`/api/confirm` requestで送信します。

## 現在の学習契約

- ○は選択対象へ正の学習を行い、複数の○には弱い共起学習も行う。
- △はnear-missとして○より弱い正の学習を行う。
- ×は表示対象へ負の学習を行う。
- 未知ID、分類の重複、表示項目の不足は、学習を始める前にHTTP 400で拒否する。
- test-playと学習無効時は、分類を受理しても行列・統計を更新しない。
- 表示結果、feedback target、share target、analytics target、session resultの対応を回帰テストで固定する。

## 原子性と障害復旧

1回の詳細フィードバックで生じる行列、診断ログ、累積統計、日次統計の変更はまとめて確定します。PostgreSQLでは単一transaction、ローカルJSONではwrite-ahead journalを使います。途中で失敗した場合は全変更をrollbackし、process停止でjournalが残った場合は次回起動時にroll-forwardします。APIは保存完了後にだけ成功を返します。

## 回帰テスト

- ○・△・×の混在と全件○が1 requestで処理される。
- 重複・不足・未知IDでは行列も統計も変化しない。
- ローカル保存失敗時に全ファイルとmemory上の行列が元へ戻る。
- PostgreSQLでは行列と各counterが同じtransactionを使う。
- 通常の単一正解、追加登録、学習無効の既存挙動を維持する。
