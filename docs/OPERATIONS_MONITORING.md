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

## GitHub Actions例

```yaml
name: Operations monitoring

on:
  schedule:
    - cron: "*/30 * * * *"
    - cron: "5 15 * * *" # JST 00:05 daily report
  workflow_dispatch:

jobs:
  monitor:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"
      - name: Health and warning check
        run: python scripts/operations_check.py
        env:
          HEKI_BASE_URL: https://hekineitor.onrender.com
          ADMIN_READ_TOKEN: ${{ secrets.ADMIN_READ_TOKEN }}
          NTFY_TOPIC: ${{ secrets.NTFY_TOPIC }}
          NTFY_SERVER: https://ntfy.sh
      - name: Daily analytics report
        if: github.event.schedule == '5 15 * * *'
        run: python scripts/daily_analytics_report.py
        env:
          HEKI_BASE_URL: https://hekineitor.onrender.com
          ADMIN_READ_TOKEN: ${{ secrets.ADMIN_READ_TOKEN }}
          NTFY_TOPIC: ${{ secrets.NTFY_TOPIC }}
          NTFY_SERVER: https://ntfy.sh
```

## Render Cron例

Render Cron の Environment に `HEKI_BASE_URL` / `ADMIN_READ_TOKEN` / `NTFY_TOPIC` / `NTFY_SERVER` を登録し、Command にはsecret値を書かないでください。

30分ごとのhealth check:

```sh
python scripts/operations_check.py
```

JST深夜の日次レポート:

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
