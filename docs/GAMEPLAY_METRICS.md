# ゲームプレイ指標

`/api/gameplay_event` はゲームループ改善のための匿名イベントだけを保存します。IP、User-Agent、session ID、自由記述、回答値は保存しません。event/source/outcomeはallowlist、IDと回答数は上限付き整数です。DB event storeが有効なら`event_type=gameplay`、それ以外は`data/gameplay_events.jsonl`を使います。

## 管理レポート

管理者またはread-only管理者は `GET /api/admin/gameplay_events?limit=5000` で次を確認できます。

- 通常再挑戦率
- 除外再挑戦率
- 追加質問率
- フィードバック完了率
- おすすめ作品クリック率
- 質問重複率

`/api/admin/operations_snapshot` の `gameplay_events_summary` にも同じ集約を含みます。作品クリック数は安定した`work_id`/`edition_id`を持つshare event、質問表示数はquestion eventと結合して率を算出します。

## 運用

1. リリース直後は母数が少ないため率だけで判断せず、`total`と`by_event`を同時に確認する。
2. 週次で再挑戦、追加質問、feedback、作品クリックを前週と比較する。
3. `question_repeat_rate`が増えた場合は通常・後半識別・除外・IDK回復の各質問選択を再現する。
4. ログ肥大化時はJSONLが5 MiBで世代ローテーションされる。DB利用時は既存event storeの保持方針に従う。
5. test-playでは記録しない。計測失敗はゲーム進行を止めない。

## イベント契約

`diagnosis_started`, `result_shown`, `retry_started`, `exclude_retry_started`, `continue_started`, `feedback_completed`, `work_impression`, `history_reopened`, `resume_started`, `draft_discarded`, `question_repeated`のみを受け付けます。未知のイベントやsource/outcomeはHTTP 400で拒否します。
