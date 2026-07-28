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

`scripts/check.sh`はPython compile、既存の安全性check、Ruff lint/format、段階導入したmypy、Python testとcoverage最低基準、ESLint、Vitestをまとめて実行します。PlaywrightのChromium E2Eは、診断完走、manifest/offline、continue/feedback/history、mobile viewportをCIの専用stepで検証します。

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

- 回答ボタンを押した直後に選択状態と考え中表示が出て、遅延時に文言が変わり、失敗時はボタンとfocusが復元される。
- 4回連続の「わからない」で具体的な別軸質問へ切り替わり、情報不足で終了した結果は暫定表示と追加質問導線を持つ。
- 除外再挑戦では除外結果が全質問選択経路から外れ、全候補除外時も診断が停止しない。
- 詳細○△×は全項目を1回のrequestで送信し、重複・不足・未知IDを学習前に拒否する。
- 詳細フィードバックの行列・診断ログ・累積統計・日次統計は、DB transactionまたはローカルjournalで一括確定し、保存失敗時は全てrollbackされる。
- 途中経過は7日保持され、最終回答時刻、期限、続行、破棄が表示される。
- 結果の主CTA、履歴再閲覧、作品3件先行表示、残り展開、共有fallbackをkeyboardと320px幅でも操作できる。
