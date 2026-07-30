# Work Catalog Migration and Rollback

inline `fetishes.works` / `compound_works`をsource of truthから外すための運用手順です。`/api/admin/works_health`の`migration`は判定材料であり、単独では旧データ削除を許可しません。

## Checked-in evidence (2026-07-29)

`data/work_catalog_review_decisions.json`は74件のinput-locked判断（merge 72、keep separate 2）を持ち、seed override、schema v3 correction、schema v2 bibliography manifestを順に適用します。現行seedはmaster 325、edition 253、edition identifier 14、alias 159、fetish link 373、compound link 141、pending 0です。23作品の媒体と14件のISBNを保持しながら、legacy projectionとのfetish/compound mismatchはいずれも0で、`automated_parity_ok=true`です。

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

既存DBへの自動運用は`.github/workflows/work-catalog-apply-manifests.yml`を使い、fresh v3 backupのdigest一致後にreview、seed override、corrections 1、bibliography 1、corrections 2、bibliography 2、link bindings 2を順に適用します。batch 1の55 corrections / 18 bibliography entriesは従来の固定承認件数を維持し、batch 2の20 corrections / 13 bibliography entries / 12 bindingsはchecked-in manifestから件数とcanonical SHA-256を算出して応答・監査ログと照合します。既存batch 1最終catalogはphase 2全体のinput lockをmutation前に通過した場合だけbatch 1操作をskipし、phase 2だけを適用します。fresh、batch 1最終、phase 2再適用のいずれも段階別digest lockと最終parityを検証します。

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

`data/work_catalog_corrections.json`はschema v3、55件（split 1、retitle 8、quarantine 45、link rebind 1）です。canonical SHA-256は`ad70a6240291b0c5b9501d6c83e9bc617c8060be1a8e9314379e0f5570f7f3c4`です。旧pending 39件の完全一致書誌調査により、`シンデレラの偽装婚約`は[A-WAGON表記のBOOK☆WALKER series](https://bookwalker.jp/series/549171/)と[コミックシーモア](https://www.cmoa.jp/title/335103/)で正式identityを確認しました。editionはseries landingではなく[合本版1の直接商品ページ](https://bookwalker.jp/dedd8698ce-91a7-4354-8239-3cc82613c858/)へ固定し、残る38件をquarantineしました。quarantine workは同一IDのまま`archived`にし、masterを監査用に保持します。

link removalはsource row全fieldと、edition付きの場合は`source_url`も固定します。forwardはlink update後にremove、reverseはremove復元後にupdateし、同manifestの削除から計算した最終positionだけを冪等状態として許容します。既適用inlineの不在は明示`allow_missing`かつ同signatureが他ownerへ移動していない場合だけskipします。`review_queue.updated_at`の既知UTC instant互換、player-added owner 104の保護、部分rollout時のresolved review fingerprint検証は従来どおりです。
`link_rebind`は本番で追加された性癖owner 107の推薦に限定し、旧link ID、作品、版、owner、position、aliasなし、表示title、URLをinput lockします。既存の表示aliasへ付け替えるだけなのでcanonical titleは正式名のまま、inline titleとURLも不変です。checked seedには対象linkがなく、`allow_missing=true`によりno-opになります。

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

成功時は`correction_count=55`、`split_count=1`、`retitle_count=8`、`quarantine_count=45`、`link_rebind_count=1`、4つの`inline_*_count`、監査fingerprint `ad70a6240291b0c5b9501d6c83e9bc617c8060be1a8e9314379e0f5570f7f3c4`を照合します。DBではcatalog訂正と対象`fetishes.works`を同一transactionへ含めます。review queueが全件解決済みで、現行correction manifestのsource lockに完全適合するcatalogでは、旧review段階をskipします。skip前には明示的な`review_updates.target`だけを検証用copyで`expected`へ戻し、review manifestの再適用が完全no-opであることに加え、UTC instant正規化後の全resolved row fingerprintを照合します。74件版は`97a4405d95af9031ae5fa4f275272f7e559037f520a73a5ba48609cb96aab217`、旧79件版は`9fdb1d44dfb930eb91dd1a679dddbd95116d9058748aa48ca0bdd841e6e2e215`です。これにより既存訂正の適用後に新しい訂正を追加した部分状態でも、旧reviewで訂正内容を上書きせず、seed cleanup、既存訂正の冪等確認、新規訂正、inline同期を順に実行します。source lock、review意味、titles/ASIN/version/timestampを含むrow fingerprintのいずれかが不適合ならfail-closedで停止します。

healthは2種類のparityを混同しません。`approved_projection_ok` / `approved_mismatch_count`はcorrection manifestで固定されたowner・position・旧title/URLを新title/URLへ厳密投影した期待値との比較です。`automated_parity_ok` / `mismatch_count`は同期済みinlineとのraw比較であり、実際のlegacy fallback同値性とinline廃止可否を判定します。旧signatureの別position・別ownerへの移動、owner・件数・順序・URLの差、未承認titleはfail-closedです。`allow_missing`は真偽値だけを許可し、旧sourceが全ownerから不存在の場合だけno-opにします。

本番ではGitHub Actionsの`Apply Work Catalog Manifests`を使用します。成功した直近の`Matrix Backup & DB Expiry Check` run ID、デプロイ済みmain commit SHA、正確な本番hostname、確認文`APPLY WORK CATALOG MANIFESTS TO PRODUCTION`が必要です。workflowはbackup v3とそのcatalog digestを現在の本番catalogに照合し、本番source digestに対応するchecked-in review manifestのcanonical SHA-256、ローカルpreflight結果、各操作直前のdigest optimistic lock、応答件数、適用後catalog・監査fingerprint・approved parityとraw parity 0を検証します。credentialやcatalog本文を含まない証跡だけを30日保存します。全workerの継続観測は、この適用後に別の`Work Catalog Rollout Gate`で行います。

manifest適用スクリプトは、一過性のtransport障害に対してGETだけを最大3回再試行します。POST mutationは結果が不明なまま二重適用されることを防ぐため、自動再試行しません。POST応答が途切れた場合は、直前・直後のbackupとcatalog digestで実状態を確認してから再実行を判断します。

### Repeated worker observation

`python scripts/work_catalog_rollout_check.py`はread-only tokenだけで`/api/admin/works_health`を反復取得し、worker集合、catalog/DB/cache revision、両parity、pending review、fallback/load failureを`artifacts/work_catalog_rollout_report.json`へ記録します。runtime catalog gateは承認済みprojectionとの一致を要求します。raw inline mismatchはworker errorにはせず`retirement_readiness.blockers`へ残しますが、同期releaseのmanifest適用後はraw mismatch 0が正常状態です。旧health contractのworkerはraw parityを保守的なruntime判定として扱います。`.github/workflows/work-catalog-rollout-check.yml`は同じ証拠をartifactとして30日保持します。

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

この時点の6 owner差はapproved projectionで全件説明されました。inline同期release `bbfe96aa541ae0bd88d988b6ed9b40ec6dca87d2`ではchecked fetish 6 linkとcompound 1 linkを承認済み表示へ更新し、同じcorrection manifestの再適用で本番DB `fetishes.works`も同期しました。catalog digestは不変です。

- release CI: workflow run `30484600035`（全check、coverage、Chromium E2E成功）
- 同期前v3 backup: workflow run `30485461682`
- inline同期manifest適用: workflow run `30485597961`（fetish link 5件・owner 5件を更新、player replacement 1件を保持、raw/approved mismatch 0、全revision 12）
- 12 sample rollout gate: workflow run `30485910957`（64.856秒、1 worker、revision 12、fallback/load failure 0、retirement blocker 0、`automated_eligible=true`）
- 同期後v3 backup: workflow run `30486049555`（137 fetish、153 question、20,961 matrix row、catalog digest・全件数・pending 0を再確認）

これにより`catalog_inline_mismatch`は解消しました。残るretirement条件はstaging v3 restore rehearsal、手動サインオフ、および必要な観測期間です。

### Schema v2 bibliography rollout (2026-07-30)

schema v2と一次書誌18件を本番へ適用しました。最終catalogはmaster 375、edition 307、edition identifier 12、alias 158、fetish link 396、compound link 185、resolved review 79、pending 0です。媒体種別18件、紙版書誌12件を保持し、最終digestは`1c31845b425884afaca632c3f5c53d3dedcc23548cfc6bd06cbf58212cbb1e80`です。

- 初回適用前v3 backup: workflow run `30497490375`
- 初回適用: workflow run `30497534529`（mutationは完了したが、適用後GETの一過性TLS resetでjobはfailure。直後backup `30497617944`で書誌12件とparity 0を確認）
- 安全性改善: GETだけを最大3回再試行し、POSTは自動再送しない。seed cleanup後の冗長alias整理状態もbibliographyの正規な冪等状態として検証する
- 最終release CI: workflow run `30500297413`（全check、coverage、Chromium E2E 8件成功）
- 最終適用前v3 backup: workflow run `30500737771`
- manifest最終検証: workflow run `30500779528`（review skip、bibliography 18 entries / edition 0 / identifier 0、raw/approved mismatch 0、pending 0、全revision 20、監査fingerprint一致）
- 最終適用後v3 backup: workflow run `30500836045`（上記digest・件数、137 fetish、153 question、20,961 matrix row、ISBN 12件を再確認）

最終backupをchecked compound sourceと照合したraw parityはfetish owner 137、compound owner 77、mismatch 0です。公開healthもPostgreSQL、degraded reasonなし、matrix 137x153、4xx/5xx 0を確認しました。

### 露出少女日記 P0 correction rollout (2026-07-30)

誤って紐付いていたASIN `B097ZSFLYR`を削除し、作者のFantia版`https://fantia.jp/products/685549`へ推薦を付け替えました。旧表示alias、fetish owner 55、position 1は維持しています。本番catalogはmaster 375、edition 307、edition identifier 12、alias 159、fetish link 396、compound link 185、resolved review 79、pending 0です。最終digestは`755464ef6731ca1b09883b2224d8707e7b8d2ac87985a1e4e6c9b25a0c4da845`です。

- correction release CI: workflow run `30504290394`（全check、coverage、Chromium E2E 8件成功）
- 初回適用前v3 backup: workflow run `30504705532`
- 初回preflight: workflow run `30504732377`（旧79件reviewを再適用しようとしたcandidate driftをmutation前に検出して安全停止）
- 部分rollout安全化release CI: workflow run `30505719463`（resolved reviewの意味検証と74/79件全行fingerprint、correction source lockをすべて満たす場合だけreviewをskip）
- 最終適用前v3 backup: workflow run `30506083944`
- manifest適用成功: workflow run `30506104611`（review skip、correction 5件、inline fetish owner 1件、bibliography no-op、raw/approved mismatch 0、pending 0、全revision 23）
- 最終適用後v3 backup: workflow run `30506142764`（誤ASIN 0件、Fantia edition 1件、上記digest・件数・owner/positionを再確認）

公開healthはPostgreSQL、degraded reasonなし、matrix 137x153、監査6件、4xx/5xx 0です。適用証跡と適用後backupの双方でcatalog validationとdigest一致を確認しました。

### Schema v3 quarantine preflight (2026-07-30)

適用後backup run `30506142764`のcatalog digest `755464ef6731ca1b09883b2224d8707e7b8d2ac87985a1e4e6c9b25a0c4da845`に対し、新schema v3 manifestをローカルでpreflightしました。旧79件reviewの全行fingerprintとcorrection source lockは互換、seed cleanupとbibliographyはno-op、correction再適用は冪等です。想定結果はmaster 375、edition 308、edition identifier 14、alias 160、fetish link 393、compound link 179、resolved review 79、pending 0、digest `c5fe0fe9d61ffef8d8a0633f3187fd29fb401d064656607a40f7e2a1a8486333`です。これはmutation前の検証値であり、本番反映の証跡ではありません。

### Schema v3 quarantine and production alias rebind rollout (2026-07-30)

release `eceb3ce`でschema v3 quarantineと本番追加推薦向けのoptional alias rebindを反映しました。最終catalogはmaster 375、edition 308、edition identifier 14、alias 160、fetish link 393、compound link 179、resolved review 79、pending 0で、digestは`f5bac98370b0af0fd5054be4257d6873378192c268366bf23ff475b79a1e52c6`です。

- release CI: workflow run `30514145701`
- 適用前v3 backup: workflow run `30514507429`
- manifest適用成功: workflow run `30514530917`
- 適用後v3 backup: workflow run `30514560153`（上記digestと全件数を再確認）
- 12 sample rollout gate: workflow run `30514599569`（68.428秒、1 worker、revision 29、fallback 0、catalog load failure 0、raw/approved parity mismatch 0、`automated_eligible=true`）

本番追加linkはsource `fwl_6eb279e52350c546dd7c`が消え、target `fwl_35eef2046426b62f78ae`が既存alias `wal_e3fdfa57179ebc08db2e`を参照しています。canonical titleは`逃げるは恥だが役に立つ`のまま、公開表示title `逃げるは恥だが役に立つ（漫画）`とURL `https://www.amazon.co.jp/dp/B00GWVP77W?tag=hekinator-22`は不変です。自動gateは成功していますが、staging restore rehearsalと運用担当者の手動サインオフは引き続き必須です。

### Pending research resolution rollout (2026-07-30)

旧pending 39件を完全一致titleで再調査し、`シンデレラの偽装婚約`だけを正式identityとしてedition・aliasへ接続し、残る38件をquarantineしました。research queueはpending 0、quarantined 45です。55件版correction manifestのcanonical SHA-256は`ad70a6240291b0c5b9501d6c83e9bc617c8060be1a8e9314379e0f5570f7f3c4`で、checked seedはmaster 325、edition 253、edition identifier 14、alias 159、fetish link 373、compound link 141、review 74、pending 0です。

local preflightでは、39 linkのinline同期、reverse/forward round-trip、deterministic rebuild、catalog validation、raw parity mismatch 0を確認しました。release `0339a8d`の55件版を本番へ適用した結果はmaster 375、edition 309、edition identifier 14、alias 161、fetish link 393、compound link 141、resolved review 79、pending 0です。45件は`archived`かつ推薦link 0で、検証済み作品は合本版1の直接商品URLを保持します。最終digestは`a106ff6d35574d48b53e5f554b491ca87800bc7f043efd754d172ebd10966747`です。

- release CI: workflow run `30517524073`
- 適用前v3 backup: workflow run `30517929031`
- manifest適用成功: workflow run `30517950724`（55 corrections、manifest SHA-256一致、raw/approved parity mismatch 0、revision 32）
- 適用後v3 backup: workflow run `30517999082`（上記digest・全件数・45 quarantineの推薦参照0を再確認）
- 12 sample rollout gate: workflow run `30518120489`（83.395秒、1 worker、全revision 32、fallback 0、catalog load failure 0、raw/approved parity mismatch 0、`automated_eligible=true`）

事前backupからchecked-in seed override、correction、bibliographyを同じ順序で適用したローカル結果と、事後backupのcatalogはbyte-equivalentです。自動gateは成功していますが、staging restore rehearsal、必要な観測期間、運用担当者の手動サインオフは引き続き必須です。

## Deploy前

1. backup format v3のmatrix backupを保存し、`work_catalog`を含むことを確認する。
2. 既存DBへreview、safe seed cleanup、P0 correctionの3 manifestを順に適用し、それぞれの監査fingerprint、応答件数、新digestを保存する。fresh DBが訂正済みseedから作られた場合、workflowは旧reviewをskipし、seed/correctionのno-opだけを確認する。
3. `/api/admin/works_health`で`migration.approved_projection_ok=true`、`approved_mismatch_count=0`、`automated_parity_ok=true`、`mismatch_count=0`、`pending_review_count=0`を確認する。raw parityが非ゼロなら影響ownerと表示順・実効title・安全化後URLを確認し、manifest workflowを失敗扱いにしてinline廃止を停止する。
4. platformのinstance一覧から各workerへ直接probeするか、十分な回数アクセスしてresponseの`worker_id`を収集し、想定worker集合を網羅する。各responseで`snapshot_revision == database_revision == cached_revision`も確認する。
5. 十分な観測期間、各workerの`legacy_fallback_reads_since_start`と`catalog_load_failures_since_start`が0であることを確認する。
6. [Staging v3 Restore Rehearsal](STAGING_V3_RESTORE_REHEARSAL.md)を実行し、artifactの自動gateを確認したうえで、通常/compound結果、作品理由、SEO/OGP、affiliate URLを手動サインオフする。
7. [`WORK_CATALOG_REVIEW_2026-07-28.md`](WORK_CATALOG_REVIEW_2026-07-28.md)の件数・keep判断・残るデータ品質項目を確認し、rollback担当者と実行時刻を決めて手動サインオフする。

`retirement.automated_eligible=true`でも、観測期間、restore rehearsal、手動サインオフがなければinlineを削除しません。

## Deploy後

- 移行期間中はchecked inline projectionとDB fetish inline同期を保持する。
- 管理更新後にrevision一致とparityを再確認する。
- `catalog_inline_mismatch`、`legacy_fallback_observed`、`catalog_load_failure_observed`、`worker_catalog_revision_mismatch`のいずれかが出た場合は廃止作業を停止する。
- DB modeのcompound更新はcatalogが正であり、旧JSONとの差異は意図的にretirement blockerとして報告される。rollback sourceはv3 backupのcatalogとする。

## Rollback

1. 管理更新を停止する。
2. 現在のbackup format v3 snapshotを追加保存する。
3. catalog-firstを無効化できる直前releaseへ戻すか、必要なら確認済みv3 backupを同じcorrection状態のcode/data revisionへrestoreする。pre-correction catalogへ戻す場合はmatching source compound deployを先に用意する。
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
