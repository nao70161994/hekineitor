# Work Catalog Migration and Rollback

inline `fetishes.works` / `compound_works`をsource of truthから外すための運用手順です。`/api/admin/works_health`の`migration`は判定材料であり、単独では旧データ削除を許可しません。

## Checked-in evidence (2026-07-29)

`data/work_catalog_review_decisions.json`は74件のinput-locked判断（merge 72、keep separate 2）を持ち、`data/work_catalog_seed_overrides.json`は確実な46表記のcanonical/alias/context分離とplaceholder 4件の削除を固定します。両方を適用済みのseedはmaster 325、edition 239、alias 150、fetish link 376、compound link 185、context付きlink 52、pending 0です。legacy projectionとのfetish/compound mismatchはいずれも0で、`automated_parity_ok=true`です。

既存DBへ適用するときは、まず`GET /api/admin/work_catalog`で最新`digest`を取得し、`POST /api/admin/work_catalog/mutate`へ次を送ります。

```json
{
  "operation": "review_apply_manifest",
  "expected_digest": "GETで取得した64桁digest",
  "confirm_text": "WORK_CATALOG",
  "payload": {
    "decision_manifest": "data/work_catalog_review_decisions.jsonのJSON object"
  }
}
```

manifestは全件を一つのtransaction/journalで適用します。同一manifestを適用済みcatalogへ再送した場合はno-opです。成功応答の`result.resolved_count=74`、`result.pending_count=0`と新digestを保存し、監査ログの`manifest_sha256`をchecked-in fileと照合します。409なら再取得して差分を調べ、別manifestとして再reviewするまでは強制適用しません。

既存catalogへsafe seed cleanupを適用する場合は、同じ最新digestを取得し直して次を送ります。

```json
{
  "operation": "seed_overrides_apply_manifest",
  "expected_digest": "GETで再取得した64桁digest",
  "confirm_text": "WORK_CATALOG",
  "payload": {
    "seed_overrides": "data/work_catalog_seed_overrides.jsonのJSON object"
  }
}
```

この操作もDBではcatalog lock内の一transaction、localでは一つのmutation journalで適用されます。displayの欠落・複数work一致、canonical衝突、削除後の参照残りはfail-closedです。成功時は`normalized_title_count=46`、初回のみ`removed_work_count=4`を確認し、監査ログの`manifest_sha256=e960ed79e1f77c0af61275d536f311b3d8c3b93b563bf522e55b0ed4dbde32c3`を照合します。再適用は`removed_work_count=0`のno-opとなり、digestも変化しません。

`data/work_catalog_corrections.json`は、一次情報で確認したP0誤紐付け4件を、source row完全一致・決定的ID・冪等適用で訂正します。1件は別作品editionを新masterへ分離し、3件は誤ったmaster identityを正式作品名へretitleします。edition/linkのownerとpositionを維持し、誤aliasを削除して推薦文脈をlink contextへ移します。`review_queue.updated_at`だけはUTC instantとして比較し、checked seedの`2026-07-28`に加えて、旧79件review manifestが本番へdurable保存した既知値`2026-07-29T00:00:00+00:00`をmanifestの`accepted_source_updated_at`で明示許可します。同一instantのdate/ISO表現だけが一致し、未列挙の日付や他fieldの差異はfail-closedです。本番でplayer-added owner 104の推薦置換により既に不存在となったseed alias `wal_d6cfef435e8063b178c5`とlink `fwl_0491358730a92c95b5dc`だけは`allow_missing`でskipします。存在する場合は完全一致を必須とし、異内容のrowは拒否します。不在のseed linkを再作成しないため、本番のplayer-added推薦・owner/positionは保持されます。

```json
{
  "operation": "corrections_apply_manifest",
  "expected_digest": "seed cleanup後に再取得した64桁digest",
  "confirm_text": "WORK_CATALOG",
  "payload": {
    "corrections_manifest": "data/work_catalog_corrections.jsonのJSON object"
  }
}
```

成功時は`correction_count=4`、`split_count=1`、`retitle_count=3`と監査fingerprint `2e629957bd11a85f14269298aa8227298faa16fdba21cf82e19fbceb9d0bf76e`を照合します。訂正済みcatalogへworkflowを再実行すると、訂正内容を上書きする旧review段階はskipし、seed cleanupとcorrection manifestだけを冪等確認します。

healthは2種類のparityを混同しません。従来の`automated_parity_ok` / `mismatch_count`は未変換inlineとのraw比較を維持し、legacy fallbackの同値性とinline廃止可否だけに使います。`approved_projection_ok` / `approved_mismatch_count`は、correction manifestで固定されたowner・position・旧title/URLを新title/URLへ厳密投影した期待値との比較です。旧signatureの別position・別ownerへの移動、owner・件数・順序・URLの差、未承認titleはfail-closedです。`allow_missing`は真偽値だけを許可し、旧sourceが全ownerから不存在の場合だけno-opにします。

本番ではGitHub Actionsの`Apply Work Catalog Manifests`を使用します。成功した直近の`Matrix Backup & DB Expiry Check` run ID、デプロイ済みmain commit SHA、正確な本番hostname、確認文`APPLY WORK CATALOG MANIFESTS TO PRODUCTION`が必要です。workflowはbackup v3とそのcatalog digestを現在の本番catalogに照合し、本番source digestに対応するchecked-in review manifestのcanonical SHA-256、ローカルpreflight結果、各操作直前のdigest optimistic lock、応答件数、適用後catalog・監査fingerprint・healthを検証します。credentialやcatalog本文を含まない証跡だけを30日保存します。全workerの継続観測は、この適用後に別の`Work Catalog Rollout Gate`で行います。

### Repeated worker observation

`python scripts/work_catalog_rollout_check.py`はread-only tokenだけで`/api/admin/works_health`を反復取得し、worker集合、catalog/DB/cache revision、両parity、pending review、fallback/load failureを`artifacts/work_catalog_rollout_report.json`へ記録します。runtime catalog gateは承認済みprojectionとの一致を要求します。raw inline mismatchはworker errorにはせず、`retirement_readiness.blockers`へ残します。このため訂正済みcatalogの稼働確認は成功できても、fallbackが古い表示を返し得る間はinline廃止不可です。旧health contractのworkerはraw parityを保守的なruntime判定として扱います。`.github/workflows/work-catalog-rollout-check.yml`は同じ証拠をartifactとして30日保持します。

`WORK_CATALOG_EXPECTED_WORKERS`はplatformのinstance一覧から設定し、観測できた数に合わせて下げません。自動gate成功後も、十分な期間のartifactを比較し、v3 restore rehearsalと手動サインオフを完了するまではinlineを廃止しません。

## Production evidence (2026-07-29)

旧生成規則で初期化済みの本番PostgreSQLには、source digest `7bbadf34074f154d1e69cf40382834c641aaf30b5edb6432d05b7aa86b87bd17`専用の互換review manifestを適用しました。既存の追加性癖・推薦を保持した結果はmaster 374、edition 295、alias 156、fetish link 396、compound link 185、resolved review 79、pending 0です。最終catalog digestは`a80fe4106e76f906fb09bbe2338b79bbad641edcfbcca0daafd7958609ae2501`です。

- 適用前v3 backup: workflow run `30426638387`
- manifest適用成功: workflow run `30426768281`（review 79 / pending 0、normalization 46、placeholder removal 4、revision 3）
- 65秒・12 sample rollout gate: workflow run `30426804937`（rolling deploy中の2 worker IDを観測し、双方revision 3、fallback/load failure/mismatch 0）
- 適用後v3 backup: workflow run `30427085538`（上記最終digestと件数を再確認）
- 通常/compound診断の手動完走: 確認済み

この証跡は本番移行の自動gateを満たしますが、staging v3 restore rehearsalと旧inline廃止の最終承認を代替しません。

P0 correction適用後の本番catalogはmaster 375、edition 295、alias 153、fetish link 396、compound link 185、resolved review 79、pending 0、revision 10です。最終digestは`db0f725764a785303dc53073b935585460611b1f1cc2c2628f4874318fc5c0fa`です。

- 初回correction mutation: workflow run `30435445845`（catalog更新とrevision 8へのcommitは成功。旧post-healthがraw mismatchをruntime異常扱いしたためjob自体はfailure）
- manifest冪等再検証: workflow run `30472630524`（成功。review skip、seed/correction no-op、approved mismatch 0、raw mismatch 6、全revision 10、監査fingerprint一致）
- 12 sample rollout gate: workflow run `30472753297`（成功。63.6秒、1 worker、全revision 10、fallback/load failure 0、runtime error 0）
- 適用後v3 backup: workflow run `30473032447`（上記digest・件数・pending 0を再確認）

この6 owner差はapproved projectionでは全件説明されますが、raw inline fallbackは旧titleのままです。したがってruntime catalog gateとmutation成功の証拠には使える一方、`catalog_inline_mismatch`はretirement blockerとして維持します。

## Deploy前

1. backup format v3のmatrix backupを保存し、`work_catalog`を含むことを確認する。
2. 既存DBへreview、safe seed cleanup、P0 correctionの3 manifestを順に適用し、それぞれの監査fingerprint、応答件数、新digestを保存する。fresh DBが訂正済みseedから作られた場合、workflowは旧reviewをskipし、seed/correctionのno-opだけを確認する。
3. `/api/admin/works_health`で`migration.approved_projection_ok=true`、`approved_mismatch_count=0`、`pending_review_count=0`を確認する。`automated_parity_ok` / `mismatch_count`が非ゼロならruntime correctionの失敗とはみなさないが、影響ownerと表示順・実効title・安全化後URLを確認し、raw parityが0へ戻るまでinline廃止を停止する。
4. platformのinstance一覧から各workerへ直接probeするか、十分な回数アクセスしてresponseの`worker_id`を収集し、想定worker集合を網羅する。各responseで`snapshot_revision == database_revision == cached_revision`も確認する。
5. 十分な観測期間、各workerの`legacy_fallback_reads_since_start`と`catalog_load_failures_since_start`が0であることを確認する。
6. [Staging v3 Restore Rehearsal](STAGING_V3_RESTORE_REHEARSAL.md)を実行し、artifactの自動gateを確認したうえで、通常/compound結果、作品理由、SEO/OGP、affiliate URLを手動サインオフする。
7. [`WORK_CATALOG_REVIEW_2026-07-28.md`](WORK_CATALOG_REVIEW_2026-07-28.md)の件数・keep判断・残るデータ品質項目を確認し、rollback担当者と実行時刻を決めて手動サインオフする。

`retirement.automated_eligible=true`でも、観測期間、restore rehearsal、手動サインオフがなければinlineを削除しません。

## Deploy後

- 移行期間中はinline projectionを保持する。
- 管理更新後にrevision一致とparityを再確認する。
- `catalog_inline_mismatch`、`legacy_fallback_observed`、`catalog_load_failure_observed`、`worker_catalog_revision_mismatch`のいずれかが出た場合は廃止作業を停止する。
- DB modeのcompound更新はcatalogが正であり、旧JSONとの差異は意図的にretirement blockerとして報告される。rollback sourceはv3 backupのcatalogとする。

## Rollback

1. 管理更新を停止する。
2. 現在のbackup format v3 snapshotを追加保存する。
3. catalog-firstを無効化できる直前releaseへ戻すか、必要なら確認済みv3 backupをrestoreする。
4. `/api/admin/works_health`でparityとrevisionを再確認する。
5. 診断結果、作品表示順、compound結果、共有、SEO/OGP、affiliate URLをsmoke testする。
6. 原因と影響ownerを監査ログおよび移行記録へ残す。

## Inline廃止条件

- raw inlineの`automated_parity_ok=true`かつ`mismatch_count=0`である（approved projection parityだけでは代替しない）。
- pending reviewがない。
- 全workerでrevisionが一致する。
- 観測期間中にfallback/load failureがない。
- v3 backup restore rehearsalが成功している。
- 運用担当者が件数・リンク・衝突レポートへ手動サインオフしている。
