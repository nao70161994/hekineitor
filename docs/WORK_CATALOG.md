# Work Catalog

おすすめ作品の唯一のsource of truthである、安定ID付きcatalogのデータ契約です。旧inline保存は2026-07-31に廃止しました。設計判断は[`adr/0004-normalized-work-catalog.md`](adr/0004-normalized-work-catalog.md)を参照してください。

## Seed snapshot

`data/work_catalog.json`は次のcollectionを持つschema version 2のsnapshotです。

- `works_master`
- `work_editions`
- `work_edition_identifiers`
- `work_aliases`
- `fetish_work_links`
- `compound_work_links`
- `review_queue`

ローカル/seedではこのファイルが正規化catalogのsnapshotです。PostgreSQLでは同じcollectionを外部キー付きtableへ初回起動時に決定的に移行します。移行判定と全catalog writeは共通のtransaction advisory lockで直列化され、既存catalogがある場合は起動時に置換しません。

schema v2は版名と出版社を`work_editions.edition_title` / `publisher`へ分離し、ASIN以外の識別子を`work_edition_identifiers`へ保持します。ASINは後方互換のため`work_editions.asin`に残し、子tableへの重複登録を拒否します。ISBN-10/13はchecksumを検証し、ISBN-10は正しいISBN-13へ正規化します。v1 backupは空の版名・出版社・identifier配列へだけupgradeし、ISBNを推測backfillしません。

`data/work_catalog_bibliography.json`は一次情報で確認した18作品のinput-locked manifestです。12作品には版名、出版社、紙版URL、ISBN-13を、残る6作品には媒体種別と根拠URLだけを登録します。版を推薦linkへ自動接続しないため公開URLは変わらず、正式名変更時は旧表示をaliasにしてraw parityを維持します。

書誌manifestはschema version 1のまま、版ごとに従来の`edition.isbn`、単一の汎用`edition.identifier`（`scheme`、`authority`、`value`）、または識別子なしのいずれかを受け付けます。`isbn`と`identifier`の併記は曖昧なため拒否します。汎用識別子はschemeとauthorityを小文字へ正規化し、scheme・authority・valueの組をcatalog全体で一意に保ちます。ISBNは従来どおりchecksumを検証してISBN-13へ正規化します。版のcanonical URL自体が根拠になる場合は識別子なしでも登録でき、ASINは汎用識別子にせずURLから`work_editions.asin`へ保持します。先に媒体種別と根拠URLだけを適用したentryへ版を追加する場合や、識別子なしの版へ後から識別子を補う場合は、既存work・旧名alias・版metadataが完全一致するときだけ不足行を追加します。

```sh
PYTHONPATH=. python scripts/build_work_catalog.py --write
PYTHONPATH=. python scripts/build_work_catalog_research_candidates.py --write
PYTHONPATH=. python scripts/build_recommended_works_list.py --write
PYTHONPATH=. python scripts/build_work_catalog.py
PYTHONPATH=. python scripts/build_work_catalog_research_candidates.py
PYTHONPATH=. python scripts/build_recommended_works_list.py
```

`docs/RECOMMENDED_WORKS_LIST.md`は正規catalogの公開fetish projectionから生成します。作品一覧を手編集せず、catalog/manifest更新後にgeneratorを実行してください。通常実行はchecked-in文書との完全一致を検証し、CIでもdriftを拒否します。

`data/work_catalog_research_candidates.json`は、現行catalogで公開参照されているactive masterのうち、販売版が未登録の作品を機械的に抽出した調査候補です。作品ごとに全fetish/compound owner参照と書誌確認状態を保持し、catalog digestに結び付けます。通常実行はchecked-in artifactとのbyte一致を検証し、`--write`だけが更新します。`generated_at`と選定規則は再現性のため固定値であり、実行日時を表しません。

この候補artifactは「現行公開linkに版を補うための作業リスト」です。`data/work_catalog_research_queue.json`の45件は、根拠不足により既に公開linkから隔離した作品の監査履歴であり、再公開候補や現行の不足一覧ではありません。両者を結合したり、一方の件数から他方の進捗を推定したりしません。

active・参照中・版なし33件の再調査は、一次情報で13件を確認し、19件をidentity未確認、`囚われのパルマ`1件を推薦文脈不適合と判定しました。`data/work_catalog_bibliography_batch2.json`は確認済み13件のうち12件へ直接版を追加し、`花は咲くか`は作品identityと媒体だけを根拠URLで固定します。実写映画ページは原作漫画の直接版ではないためeditionとして登録しません。`data/work_catalog_corrections_batch2.json`は未確認19件と不適合1件の計20 masterを監査可能な`archived`状態へ移し、21 compound linkを除去します。`data/work_catalog_link_bindings_batch2.json`は確認済み12版を既存推薦linkへ接続し、表示aliasを維持したまま空URLを一次情報のdirect URLへ置き換えます。

適用順はreview→seed override→corrections batch 1→bibliography batch 1→corrections batch 2→bibliography batch 2→link bindings batch 2です。初期catalogの再現性検証だけは、`tests/fixtures/legacy_work_catalog/`の固定fixtureを厳密に逆投影してから同じ順序でmanifestを適用します。quarantineの`link_removals.source_title`はschema v3のquarantineだけで利用でき、catalog linkの完全一致検証を弱めません。

候補generatorは通常書誌manifestとbatch2を合わせて`bibliography_state`を判定します。correction manifestは公開可否と参照除去、bibliography manifestは確認できたidentity・媒体・版metadataだけを担当し、類似題や別媒体から版を推定しません。最終候補は媒体確認済み・版なしの`花は咲くか`1件です。

旧inline同期scriptは削除済みです。catalog buildはテスト専用の固定legacy fixtureをsource状態へ逆投影してからreviewとcorrectionを再適用するため、移行履歴の安定IDとcatalog digestを再検証できます。新しい作品情報は正規catalogとmanifestだけを更新し、fixtureをruntimeデータへ戻しません。

`data/work_catalog_review_decisions.json`はraw inline入力に対する人手判断を固定するmanifestです。buildは候補keyと元`work_ids`が一致する場合だけ全判断を適用し、同じmanifestの再適用はno-opになります。英題・略称など緩い正規化では拾えない明白な同一作品は、`identity_override`として元IDを固定したreviewを追加してから統合します。

`data/work_catalog_review_decisions_legacy_v0.json`は、旧catalog生成規則で初期化済みの本番DBだけを現在の判断へ移す互換manifestです。`source_catalog_digest`が完全一致する場合だけ運用scriptが選択し、既存の追加性癖・推薦リンクを保持します。fresh DBと現行seedのsource of truthは引き続き`work_catalog_review_decisions.json`です。

## Compatibility projection

resolverはlinkを表示順に解決し、次の互換shapeを返します。

```json
{
  "title": "表示に使う正式名またはalias",
  "url": "販売版のcanonical URL",
  "work_id": "wrk_...",
  "edition_id": "wed_...",
  "alias_id": null,
  "context_label": "",
  "recommendation_reason": ""
}
```

`title`と`url`は従来の推薦表示、SEO、affiliate linkを維持します。新しいIDは管理・分析・重複排除に使います。

公開結果、SEO、管理reportはすべてcatalogだけを読みます。catalogを取得・検証できない場合はfail closedし、旧データへfallbackしません。materialized IDは結果JSON、作品linkのDOM属性、クリックeventへ渡され、旧eventはtitle identityでも集計できます。

## Runtime writes

管理画面からの性癖作品・複合作品更新は`Engine`のcatalog repositoryを唯一のproduction入口として扱います。対象ownerのlinkだけcopy-on-writeで差し替えるため、他owner、作品master、販売版metadata、review判断は保持されます。同一ASINは既存`work_id`/`edition_id`を再利用し、異なるASINや曖昧な同名候補は自動統合しません。
- correction manifestはcatalogだけを一つのcommit単位で更新します。旧inline向けの件数やprojectionは成功応答に含めません。

- PostgreSQL: catalog advisory lockを最初に取得し、正規化tableを一つのtransactionで更新します。互換列`fetishes.works`は起動時に空へし、読み書きしません。全catalog transactionは`work_catalog_meta.revision`を増分し、各workerはread前にrevisionを照合します。
- Local JSON: `fetishes.json`と`work_catalog.json`のbefore/afterをjournal format version 3で先にdurable保存します。lifecycle操作ではmatrixとfetish logも同じjournalへ含めます。全置換成功後だけjournalを削除し、途中停止時はafterへroll-forward、通常の失敗時はbeforeへrollbackします。
- 管理API: 既存のadmin認証・CSRFを維持し、成功した作品更新は件数とowner IDだけを監査ログへ記録します。
- 性癖lifecycle: deleteはその性癖の直接linkとcompound pairを削除し、promoteは新IDへ全ownerをrekeyします。mergeは削除側の直接作品を破棄し、compound pairは保持側へ統合して、既存pairを先・削除側pairを後の順で重複排除します。
- lifecycleのPostgreSQL更新はcatalog、matrix、fetish log、fetish rowを同じtransactionに置きます。ローカル更新はjournal version 2でmatrixとfetish logもbefore/afterへ含め、成功後だけin-memory state/cacheを切り替えます。

## Admin catalog API

`GET /api/admin/work_catalog`は全正規化collectionとSHA-256 `digest`を返します。更新は`POST /api/admin/work_catalog/mutate`へ`operation`、`payload`、取得時の`expected_digest`を送り、古いdigestはHTTP 409で拒否されます。master、edition、alias、推薦link metadata、review判断を操作でき、参照中のmaster/edition/alias削除は拒否します。削除、review merge、bulk manifest適用には`confirm_text: WORK_CATALOG`も必要です。全mutationは既存admin認証、CSRF、監査ログの対象です。

review一括適用は`operation: review_apply_manifest`、`payload.decision_manifest`にchecked-in manifest全体を指定します。DBではcatalog lockと一つのtransaction内で全件を適用し、途中の不整合は全体をrollbackします。ローカルでは既存mutation journalを使います。監査ログにはmanifest SHA-256、reviewer、総件数、merge件数、keep件数を保存し、manifest本文は保存しません。

reviewの`keep_separate`または`merge`には現在の`expected_version`が必須です。merge先は候補`work_ids`の一つに限定されます。URLは安全なcanonical URLだけを許可し、タイトル・媒体・版名・出版社・context・推薦理由には長さ制限があります。版identifierはcreate/update/deleteでき、ISBN checksum、global uniqueness、edition外部キーを同じtransactionで検証します。書誌一括適用は`bibliography_apply_manifest`としてdigest lock、`WORK_CATALOG`確認、監査fingerprintの対象です。

旧形式をsource of truthから外す判定とrollback手順は[`WORK_CATALOG_MIGRATION.md`](WORK_CATALOG_MIGRATION.md)を参照してください。

## Review policy

`review_queue`は自動統合の根拠ではなく、候補と人手判断の監査証跡です。

- `normalization_candidate`: 緩いタイトル正規化で近く、ASIN衝突がない候補。
- `normalization_conflict`: 緩いタイトル正規化で近く、複数ASINを持つ候補。
- `identity_override`: 英題・和題・略称など、機械的な候補抽出では結び付かないが人手で同一と確認した候補。

未判断の候補は別`work_id`のまま保持します。2026-07-28のseed reviewでは74件すべてを解決し、72件をmerge、2件を`keep_separate`としました。その後、seed cleanupと2段階のcorrection/bibliography、版link bindingを適用しました。現行seedは325 master、265 edition、25 edition identifier、164 alias、373 fetish link、120 compound link、pending 0です。媒体種別は31件で、legacy公開projectionとのmismatchは0です。判断根拠と保留事項は[`WORK_CATALOG_REVIEW_2026-07-28.md`](WORK_CATALOG_REVIEW_2026-07-28.md)と[`WORK_CATALOG_DATA_QUALITY_2026-07-29.md`](WORK_CATALOG_DATA_QUALITY_2026-07-29.md)に記録します。

## Backup and restore

`/api/admin/export_matrix`とimport/restore前snapshotは`backup_format_version: 3`として、matrix、全fetish metadata、question schema、`work_catalog`を一つのpayloadへ保存します。

- v3 importはcatalogのschemaと参照整合性をwrite前に検証し、catalog、fetish metadata、matrixを同一transaction/journalで復元します。
- v3ではseedにないmanaged/player fetishをIDとmetadataごと復元します。作品情報は`work_catalog`だけから復元します。
- ローカルのcatalog/lifecycle restoreはjournal format version 3で同じ世代へroll-forwardします。
- 旧v1/v2 matrix backupは引き続きimportできますが、そこに含まれるinline作品は意図的に無視します。
- review queueの`decision`、`target_work_id`、`version`、`updated_at`もDB snapshotとrestoreで保持します。

## Migration safety

fresh DBはchecked-in `data/work_catalog.json`を同一transaction内で正規化tableへ展開します。既存DBにcatalogがある場合は置換しません。存在しないfetish IDや同一ID pairを参照するcompound linkは検証時に拒否します。旧inlineからの決定的移行は完了済みで、再現性だけをテストfixtureで検証します。

forward/reverse投影は任意の履歴変換ではありません。checked correction manifestが認識するsourceまたはtarget signatureだけを受け入れます。古いbackupへ戻す場合は、catalog snapshotと同じ世代のcode/data artifactを組にして扱います。
