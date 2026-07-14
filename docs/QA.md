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

`scripts/check.sh`はPython compile、既存の安全性check、Ruff lint/format、段階導入したmypy、Python testとcoverage最低基準、ESLint、Vitestをまとめて実行します。Playwrightの最小browser E2EはCIの専用stepでも実行します。

個別に問題を切り分ける場合は次を使います。

```sh
python -m ruff check .
python -m ruff format --check .
python -m mypy matrix_service.py work_utils.py services/ids.py services/csv_safety.py services/name_matching.py
python run_coverage.py
npm run lint
npm run test:unit
npm run test:e2e
```

設定のsource of truthは`pyproject.toml`、`package.json`、`playwright.config.js`です。対象や閾値を変更した場合は、CIと`scripts/check.sh`も同じ変更で更新します。

## Manual checks

自動化だけでは外部サービスや実機固有の挙動を保証できません。リリース対象に変更がある場合は次を確認します。

- iOS Safari / Android Chromeのtap target、長い結果名、native share sheet
- 公開URLを使ったX、LINE、DiscordのOGP preview
- 実browser profileでのPWA install/update/offline lifecycle
