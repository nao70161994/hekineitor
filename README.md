# へきネイター

Flask 製の診断アプリです。質問への回答から性癖候補を推定し、フィードバックで matrix を学習します。

## ローカル実行

```sh
python -m pip install -r requirements.txt
SECRET_KEY=dev_secret_key_for_local flask --app app run
```

本番では `SECRET_KEY` は必須です。`DATABASE_URL` がある場合は PostgreSQL を使い、ない場合は `data/*.json` をローカル永続化に使います。

## 主な環境変数

- `SECRET_KEY`: Flask セッション署名用。本番必須。
- `DATABASE_URL`: PostgreSQL 接続 URL。Render の `postgres://` 形式も受け付けます。
- `ADMIN_USER`: 管理画面 Basic 認証ユーザー。未指定時は `admin`。
- `ADMIN_PASS`: 管理画面 Basic 認証パスワード。本番運用では必須。
- `AMAZON_ASSOCIATE_ID`: 作品リンクに付与する Amazon アソシエイト ID。
- `RATE_LIMIT_API_START_LIMIT` / `RATE_LIMIT_API_START_WINDOW`: `/api/start` のレート制限。
- `RATE_LIMIT_API_ANSWER_LIMIT` / `RATE_LIMIT_API_ANSWER_WINDOW`: `/api/answer` のレート制限。
- `RATE_LIMIT_ADMIN_API_LIMIT` / `RATE_LIMIT_ADMIN_API_WINDOW`: 管理 API のレート制限。
- `MATRIX_IMPORT_BACKUP_KEEP`: import/restore 前バックアップの保持件数。未指定時は20件。
- `ADMIN_CSRF_TTL_SECONDS`: 管理画面 CSRF トークンの有効期限。未指定時は7200秒。

## テスト

```sh
sh scripts/check.sh
```

チェックでは Python コンパイル、標準ライブラリ製の静的解析、ユニットテスト、E2E smoke を実行します。テストはデータファイルのスナップショットを復元し、通常のテスト実行で `data/*.json` を汚さないようにしています。

## 運用

- `/health`: ストレージ種別、DB 接続状態、matrix サイズ整合性、バックアップ mtime、起動時刻、エラー件数、保存時刻を返します。
- `/admin`: 管理画面。`ADMIN_PASS` が未設定の場合は利用できません。
- `/api/admin/export_matrix`: matrix backup JSON を出力します。
- `/api/admin/import_matrix`: backup JSON を復元します。実行前に現在のmatrixを自動バックアップし、`0 <= yes <= total` を満たさない行は拒否されます。
- `/api/admin/import_matrix/dry_run`: matrix backup JSON を保存せず検証し、反映対象件数を返します。
- `/api/admin/matrix_backups`: import/restore 前バックアップ一覧を返します。
- `/api/admin/matrix_backups/<name>/restore`: 指定バックアップを復元します。
- `/api/admin/audit_log`: 管理操作ログを JSON/CSV で出力します。
- `/api/admin/preflight`: 本番起動前に確認したい設定・保存状態を返します。
- `/api/admin/performance`: 代表的な管理集計・推論処理の実行時間を返します。
- `/api/admin/fetish_log_rows`: 診断ログ表をサーバー側で絞り込み・ページングして返します。
- `/api/admin/quality_report`: 低識別力質問、重複度が高い質問ペア、改善候補の性癖を JSON で返します。

管理系の更新APIは `data/admin_audit_log_YYYYMM.json` に月次ローテーションで直近500件/月の監査ログを残します。import / restore / merge / delete は確認文字列付きの二段階確認です。`/api/fetish/<id>` の DELETE は、そのセッションで追加した性癖だけ本人削除でき、それ以外は管理認証と CSRF が必要です。レート制限の 429 応答には `retry_after` と `Retry-After` が含まれます。
全レスポンスに基本的なセキュリティヘッダーを付与しています。管理画面はログ表のサーバー側ページング、preflight/performance表示、キーボード向け skip link を備えています。

GitHub Actions:

- `CI`: push / pull request でコンパイルとユニットテストを実行します。
- `Matrix Backup & DB Expiry Check`: Render から matrix を定期バックアップし、DB 期限を確認します。
- `Restore Matrix`: `data/matrix_backup.json` を Render へ復元します。

## コード構成

- `app.py`: Flask ルーティング、セッション、API。
- `engine.py`: 推論、学習、matrix 操作。
- `storage.py`: DB/ローカル JSON の設定と DB 接続。
- `matrix_service.py`: matrix import の検証・更新対象抽出。
- `audit.py`: 管理APIの監査ログ。
- `work_utils.py`: 作品データの正規化と URL 検証。
- `analytics.py`: 管理画面向け品質レポート。
- `static/app.js`: メイン画面 JS。
- `static/app.css`: メイン画面 CSS。
- `static/admin.js`: 管理画面 JS。
- `static/admin_ops.js`: 管理画面の import / backup / preflight 操作用 JS。
- `static/admin.css`: 管理画面 CSS。
