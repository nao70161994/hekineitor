# Staging v3 Restore Rehearsal

正規化作品catalogを含むMatrix Backup v3をstagingへ復元し、production移行前の復元可能性を証明する手順です。production用の`Restore Matrix` workflowとは独立しており、productionへは接続しません。

## 前提

GitHubの`staging` Environmentを作成し、必要ならrequired reviewerを設定します。Environment secretsにはproduction用credentialを流用せず、次を登録します。

```text
STAGING_APP_URL=https://<staging-host>
STAGING_ADMIN_USER=<staging-only admin user>
STAGING_ADMIN_PASS=<staging-only admin password>
PRODUCTION_APP_URL=https://<production-host>
```

`PRODUCTION_APP_URL`は接続には使わず、staging URLと異なることをfail-closedで確認するためだけに使います。値が欠けていても演習を続行しません。

復元元は`Matrix Backup & DB Expiry Check`の成功runが生成した`matrix-backup-<run_id>` artifactです。artifactには`data/matrix_backup.json`が含まれ、30日以内である必要があります。

P0 correctionとinline同期後の現行releaseを検証する復元元は、post-sync backup run `30486049555`以降を使います。backupのcatalog correction状態とstagingへdeployしたchecked inline projectionが一致しなければ実行しません。pre-correction backupを使うrollback演習は、同じsource世代のcode/data artifactを別途deployして行います。DB modeではcompound inlineをDBへ永続化できないため、backup catalogに必要なprojectionとdeploy済みcompound JSONが異なる場合はimport前にfail-closedします。

本番backupをstagingへ復元してよいのはデータを受け入れる隔離されたstaging serviceだけです。production credential、production database、production serviceの複製接続先は使いません。

隔離環境が未作成の場合は`Provision Isolated Staging` workflowを使います。`confirm`へ
`PROVISION ISOLATED STAGING`と正確に入力すると、`main`の現行commitを使うWeb Starter 1台と
PostgreSQL Basic 256 MBを作成します。DBは外部接続を許可せず、Webはstaging専用管理認証と
staging DBだけを受け取り、自動deployを無効にします。workflowは同名リソースを再利用するため
再実行で重複作成しません。`render-staging-provision-<run_id>` artifactにcredentialを含まない
service/database ID、URL、plan、release commitを保存します。Renderでは空のIP allow listが
外部接続許可を意味するため、外部から到達不能なTEST-NET-1の単一hostをdeny-all sentinelとして設定し、
再取得した値の完全一致を必須にします。追加料金が発生するため、初回実行は
費用承認後だけ行います。

## 実行

Actionsの`Staging v3 Restore Rehearsal`を手動実行し、次を指定します。

- `confirm`: `RESTORE V3 TO STAGING`と正確に入力
- `backup_run_id`: Matrix Backup workflowの数値run ID
- `expected_staging_host`: scheme、port、pathを含まないstagingのhostname

最初のstaging通信より前に、スクリプトは以下をすべて検証します。

1. confirmが完全一致する。
2. `STAGING_APP_URL`がHTTPSで、credential、query、fragment、pathを含まない。
3. URLのhostnameが`expected_staging_host`と完全一致する。
4. URL/hostnameが`PRODUCTION_APP_URL`と異なる。
5. backup run IDが正の整数である。

どれか1つでも満たさない場合は、download後の復元処理へ進みません。workflow自体もconfirm不一致ならjobを開始しません。

## 自動検証範囲

workflowは次を順に実行します。

1. 指定run IDの`Matrix Backup` artifactだけを取得する。
2. `validate_matrix_backup.py --max-age-days 30`でv3、matrix全積、fetish/question schema、`work_catalog`参照整合性を検証する。
3. staging専用Basic認証で`/admin`のcookieとCSRF tokenを取得する。
4. `/api/admin/import_matrix/dry_run`で`complete=true`、`valid_rows=expected_rows`、`skipped_rows=0`、`ignored_source_rows=0`を確認する。
5. payloadへ`confirm_text=IMPORT`を加え、CSRF付きでimportする。seedにないmanaged/player fetishをすべて復元し、imported/expected/restored件数とskipped/ignoredを再検証する。
6. stagingからv3 backupを再exportし、復元前後の正規化catalog SHA-256 digestと全テーブル件数を照合する。既存ownerのbackup inline worksも同じtransactionで復元され、catalogとのraw parityが0であることを確認する。
7. `/api/admin/works_health`でparity、DB/snapshot/cache revision一致、pending review=0、fallback/load failure=0を確認する。
8. 公開`/health`、`/`、`/fetishes`、active HTTPS editionを持つ`/fetish/<id>`、`/api/start`をsmokeする。canonical、OG title、JSON-LD、affiliate tag、診断開始response contractを確認する。
9. `compound_work_links`が復元・再exportされdigestに含まれることを確認する。

fresh stagingのseedに本番追加fetishが存在しなくても、v3 dry-runは全metadataを復元対象として`ignored_source_rows=0`を要求します。既存ownerのinline worksもbackup値へ揃えてからcatalog parityを検証します。旧v1/v2 backupでは、従来どおりplayer-added fetishだけを復元します。

`/api/start`はstagingで診断セッションを1件開始しますが、回答、結果確定、フィードバック学習は行いません。複合結果は質問回答によって非決定的に変わるため、自動処理で無理に生成しません。artifactには`manual_compound_result_signoff_required=true`を残します。

## 証跡と手動サインオフ

成功・失敗にかかわらず、`staging-v3-restore-rehearsal-<workflow_run_id>` artifactを30日保持します。

- `artifacts_backup_validation.json`: v3 validatorの件数
- `artifacts/staging_v3_restore_rehearsal.json`: dry-run/import件数、catalog digest/count、revision/parity、公開smoke結果

証跡にcredential、cookie、CSRF token、backup本体、admin response bodyは保存しません。HTTP失敗時もmethod、path、statusだけを記録します。

自動gate成功後、担当者がstagingで通常結果と複合結果を各1回表示し、次を確認します。

- 通常/複合のタイトル、説明、各要素の決め手が表示される。
- おすすめ作品の表示順、推薦理由、affiliate遷移先が妥当である。
- OGP previewと共有URLがstaging hostを指す。
- 追加質問、当て直し、履歴再閲覧が動作する。

確認者、日時、workflow run URL、artifact名をrelease checklistへ記録して初めてstaging復元演習を完了扱いにします。`status=passed`だけで旧inline source of truthを廃止しません。

## ローカル単体検証

外部接続や復元は行わず、guardとresponse検証だけを実行できます。

```sh
PYTHONPATH=. pytest -q tests/test_staging_v3_restore_rehearsal.py
```
