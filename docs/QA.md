# QA and validation

このページを現在の検証方法の入口とします。過去の実行結果は[`archive/QA_EXECUTION_LOG.md`](archive/QA_EXECUTION_LOG.md)にあり、現在の成功状態を保証するものではありません。

## Required automated checks

PythonとJavaScriptの標準検証は次のコマンドで実行します。

```sh
python -m pip install -r requirements-dev.txt
npm ci
sh scripts/check.sh
npm run test:e2e
```

`scripts/check.sh`はPython compile、既存の安全性check、Ruff lint/format、段階導入したmypy、Python testとcoverage最低基準、ESLint、Vitestをまとめて実行します。PlaywrightのChromium E2Eは、診断完走、manifest/offline、回答待機と通信失敗復帰、中断復帰、通常・除外再挑戦、追加質問、簡易・複合詳細feedbackと完了event、対抗候補との差・複合説明、理由付き作品表示とclick計測、共有失敗fallback、履歴再閲覧、320px/横向きでの最下部到達をCIの専用stepで検証します。

個別に問題を切り分ける場合は次を使います。

```sh
python -m ruff check .
python -m ruff format --check .
python -m mypy matrix_service.py work_utils.py services/ids.py services/csv_safety.py services/name_matching.py
python run_coverage.py
npm run lint
npm run test:unit
npm run test:js       # ESLint + Vitest
npm run test:static   # 静的asset・AdSense smoke
npm run test:pwa      # service worker・share/OGP/PWA contract
npm run test:e2e      # Chromium browser E2E
```

設定のsource of truthは`pyproject.toml`、`package.json`、`playwright.config.js`です。対象や閾値を変更した場合は、CIと`scripts/check.sh`も同じ変更で更新します。

## Manual checks

自動化だけでは外部サービスや実機固有の挙動を保証できません。リリース対象に変更がある場合は次を確認します。

- iOS Safari / Android Chromeのtap target、長い結果名、native share sheet
- 公開URLを使ったX、LINE、DiscordのOGP preview
- 実browser profileでのPWA install/update/offline lifecycle

## ゲーム体験回帰

- 回答ボタンを押した直後に選択状態と考え中表示が出る。確定的な失敗とsession expiryではボタンとfocusを復元し、応答消失のような曖昧な失敗では旧質問を再有効化せず、同じ回答IDでの状態確認導線を表示する。
- 4回連続の「わからない」では、直近4件の「わからない」に含まれない軸を必ず選ぶ。該当する未回答質問が本当にない場合だけ`recovery_fallback: true`を返し、通常選択に戻った旨を表示する。情報不足で終了した結果は暫定表示と追加質問導線を持つ。
- 除外再挑戦では除外結果が全質問選択経路から外れ、全候補除外時も診断が停止しない。
- 詳細○△×は全項目を1回のrequestで送信し、重複・不足・未知IDを学習前に拒否する。
- 詳細フィードバックの行列・診断ログ・累積統計・日次統計は、DB transactionまたはローカルjournalで一括確定し、保存失敗時は全てrollbackされる。
- 途中経過は回答と`exclude_ids`を7日保持する。保存してタイトルへ戻った場合と復帰後は両方を維持し、旧draftは除外なしとして復帰でき、明示的な破棄時だけ両方を消す。最終回答時刻、期限、続行、破棄を表示する。
- 結果の主CTA、履歴再閲覧、作品3件先行表示、残り展開、共有fallbackをkeyboardと320px幅でも操作できる。作品impressionは可視化時だけ安定ID付きで1回送信し、未展開作品や重複描画を数えない。

## 回答APIの冪等性

- clientは`POST /api/answer`ごとに、英数字・`_`・`-`からなる8〜64文字の`answer_request_id`を生成する。
- serverはsession内に直近1件だけrequest payloadと成功response（次質問またはguess）を保存する。同じID・同じ`question_id`・同じ回答の再送には保存responseを返し、診断状態を二重に進めない。
- 同じIDでpayloadが異なる場合は409を返す。別IDで古い`question_id`を送った場合も従来どおり409を返す。
- timeout・通信断・5xxでは同じIDだけを再利用する。400系や`session_expired`は状態照会せず、回答を選び直せる状態へ戻す。
