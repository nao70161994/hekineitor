# Work Catalog Migration and Rollback

inline `fetishes.works` / `compound_works`をsource of truthから外すための運用手順です。`/api/admin/works_health`の`migration`は判定材料であり、単独では旧データ削除を許可しません。

## Checked-in evidence (2026-07-28)

`data/work_catalog_review_decisions.json`は74件のinput-locked判断（merge 72、keep separate 2）を持ち、`data/work_catalog_seed_overrides.json`は確実な46表記のcanonical/alias/context分離とplaceholder 4件の削除を固定します。両方を適用済みのseedはmaster 324、edition 239、alias 154、fetish link 376、compound link 185、context付きlink 52、pending 0です。legacy projectionとのfetish/compound mismatchはいずれも0で、`automated_parity_ok=true`です。

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

### Repeated worker observation

`python scripts/work_catalog_rollout_check.py`はread-only tokenだけで`/api/admin/works_health`を反復取得し、worker集合、catalog/DB/cache revision、parity、pending review、fallback/load failureを`artifacts/work_catalog_rollout_report.json`へ記録します。`.github/workflows/work-catalog-rollout-check.yml`は同じ証拠をartifactとして30日保持します。

`WORK_CATALOG_EXPECTED_WORKERS`はplatformのinstance一覧から設定し、観測できた数に合わせて下げません。自動gate成功後も、十分な期間のartifactを比較し、v3 restore rehearsalと手動サインオフを完了するまではinlineを廃止しません。
## Deploy前

1. backup format v3のmatrix backupを保存し、`work_catalog`を含むことを確認する。
2. 既存DBのreview manifestとsafe seed cleanup manifestを順に適用し、それぞれの監査fingerprint、応答件数、新digestを保存する。fresh DBが適用済みseedから作られた場合は両方のno-op確認だけでよい。
3. `/api/admin/works_health`で`migration.automated_parity_ok=true`、`mismatch_count=0`、`pending_review_count=0`を確認する。差異は表示順、実効title、安全化後URLまで確認する。
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

- 自動parityが成功している。
- pending reviewがない。
- 全workerでrevisionが一致する。
- 観測期間中にfallback/load failureがない。
- v3 backup restore rehearsalが成功している。
- 運用担当者が件数・リンク・衝突レポートへ手動サインオフしている。
