# Operations Monitoring

ヘキネイターの運用通知は `ADMIN_READ_TOKEN` だけで読み取りAPIを取得し、`ntfy.sh` へ軽量通知します。`ADMIN_PASS` は使わず、POST/変更系の管理APIも呼びません。

## 環境変数

```text
HEKI_BASE_URL=https://hekineitor.onrender.com
ADMIN_READ_TOKEN=<read-only token>
NTFY_TOPIC=<ntfy topic>
NTFY_SERVER=https://ntfy.sh
```

`NTFY_TOPIC` が未設定の場合、通知送信はスキップされます。ローカルやCIで同じコマンドを実行しても失敗扱いにはしません。

任意のしきい値:

```text
NTFY_HEAVY_RESULT_WARN_RATIO=65
NTFY_RELATION_ATTACHMENT_WARN_RATIO=55
NTFY_QUESTION_YES_WARN_RATE=90
NTFY_DROPOFF_WARN_RATE=35
NTFY_FEEDBACK_WARN_RATE=5
NTFY_SHARE_WARN_RATE=3
NTFY_WORKS_MIN_COUNT=0
NTFY_5XX_CRITICAL_COUNT=1
```

## コマンド

Health / warning check:

```sh
python scripts/operations_check.py
```

Daily report:

```sh
python scripts/daily_analytics_report.py
```

`HEKI_BASE_URL` / `ADMIN_READ_TOKEN` / `NTFY_TOPIC` は実行環境のsecret/env設定に入れ、コマンド文字列には値を書かないでください。

ntfy helper単体テスト:

```sh
NTFY_TOPIC=$NTFY_TOPIC python scripts/ntfy_notifier.py   --title "Hekineitor test"   --message "notification test"
```

## 通知対象

CRITICAL:

- `/health` NG
- `storage != postgres`
- matrix shape mismatch
- works_count が `NTFY_WORKS_MIN_COUNT` 未満
- `/ogp.png` PNG signature failure
- 5xx count が `NTFY_5XX_CRITICAL_COUNT` 以上
- `/api/admin/preflight` の失敗check

WARN:

- heavy_result_ratio が高すぎる
- relation/attachment 質問表示比率が高すぎる
- YES率90%以上の質問
- 離脱率急増候補
- share率低下
- feedback/completion率低下
- 読み取りAPI取得失敗

DAILY:

- 前日プレイ数
- 完走/feedback率
- 上位結果
- heavy_result_ratio
- シェア率
- 離脱質問TOP
- YES率異常質問
- question_events / share_events 件数

## 通知例

```text
[WARN] Hekineitor operations check
WARN:
- heavy_result_ratio=71.0% TOP: 共依存 41, 激重感情 27
- relation/attachment share=58.3%
metrics:
- question_events=361
- share_events=10
- share_rate=4.2%
```

Daily:

```text
[DAILY] Hekineitor analytics
date: 2026-05-26
plays: 142
completion_rate: 18.3%
heavy_result_ratio: 63.1%
share_rate: 5.4% (7/130)
top_results:
- 共依存 44 (31.0%)
- 眼鏡 18 (12.7%)
```

## GitHub Actions推奨構成

追加課金を避けるため、定期監視は Render Cron ではなく GitHub Actions の schedule で実行します。workflow は2本に分けています。

- `.github/workflows/hekineitor-ops-check.yml`: 3時間ごとのhealth / warning check
- `.github/workflows/hekineitor-daily-report.yml`: 毎朝9時JSTの日次分析レポート

GitHub repository の `Settings` -> `Secrets and variables` -> `Actions` に以下を登録します。

```text
HEKI_BASE_URL=https://hekineitor.onrender.com
ADMIN_READ_TOKEN=<read-only token>
NTFY_TOPIC=<ntfy topic>
NTFY_SERVER=https://ntfy.sh
```

`NTFY_SERVER` は ntfy.sh を使うなら `https://ntfy.sh` で構いません。未設定でもスクリプト側は `https://ntfy.sh` にfallbackしますが、Actions secretsには明示しておくと運用確認が楽です。

### 3時間ごとの監視

```yaml
name: Hekineitor Ops Check

on:
  schedule:
    - cron: "0 */3 * * *"
  workflow_dispatch:

jobs:
  operations-check:
    runs-on: ubuntu-latest
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"
      - name: Run read-only operations check
        run: python scripts/operations_check.py
        env:
          PYTHONPATH: .
          HEKI_BASE_URL: ${{ secrets.HEKI_BASE_URL }}
          ADMIN_READ_TOKEN: ${{ secrets.ADMIN_READ_TOKEN }}
          NTFY_TOPIC: ${{ secrets.NTFY_TOPIC }}
          NTFY_SERVER: ${{ secrets.NTFY_SERVER }}
```

### 毎朝9時JSTの日次レポート

GitHub Actions のcronはUTCなので、JST 09:00 は `0 0 * * *` です。

```yaml
name: Hekineitor Daily Report

on:
  schedule:
    - cron: "0 0 * * *"
  workflow_dispatch:

jobs:
  daily-report:
    runs-on: ubuntu-latest
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"
      - name: Send read-only daily analytics report
        run: python scripts/daily_analytics_report.py
        env:
          PYTHONPATH: .
          HEKI_BASE_URL: ${{ secrets.HEKI_BASE_URL }}
          ADMIN_READ_TOKEN: ${{ secrets.ADMIN_READ_TOKEN }}
          NTFY_TOPIC: ${{ secrets.NTFY_TOPIC }}
          NTFY_SERVER: ${{ secrets.NTFY_SERVER }}
```

### 手動実行

GitHub の `Actions` タブで以下を選び、`Run workflow` を押します。

- `Hekineitor Ops Check`
- `Hekineitor Daily Report`

Secretsはworkflowの `env` に渡すだけで、コマンド内で `echo` しません。

## Render Cron補足

Render Cronでも同じスクリプトを実行できますが、追加課金回避のため通常はGitHub Actionsを推奨します。使う場合も Render Cron の Environment に `HEKI_BASE_URL` / `ADMIN_READ_TOKEN` / `NTFY_TOPIC` / `NTFY_SERVER` を登録し、Command にはsecret値を書かないでください。

Health check:

```sh
python scripts/operations_check.py
```

Daily report:

```sh
python scripts/daily_analytics_report.py
```

## セキュリティ方針

- `ADMIN_READ_TOKEN` のBearer認証だけを使います。
- `ADMIN_PASS` は使いません。
- POST/PUT/PATCH/DELETE の管理APIは呼びません。
- 通知にはIP、User-Agent、session id、個人識別子を含めません。
- スクリプトはtoken値を標準出力や通知本文に出しません。
- 通知本文は集計済みの件数、比率、質問ID、短い質問文サンプルだけに制限します。

## 運用メモ

初回は `NTFY_TOPIC` を未設定で `python scripts/operations_check.py` を実行し、判定本文だけ確認してください。問題なければ ntfy topic を設定して通知を有効化します。
