# Work Catalog

おすすめ作品のsource of truthをinline `{title, url}` から安定ID付きcatalogへ移行するためのデータ契約です。設計判断は[`adr/0004-normalized-work-catalog.md`](adr/0004-normalized-work-catalog.md)を参照してください。

## Seed snapshot

`data/work_catalog.json`は次のcollectionを持つschema version 1のsnapshotです。

- `works_master`
- `work_editions`
- `work_aliases`
- `fetish_work_links`
- `compound_work_links`
- `review_queue`

ローカル/seedではこのファイルが正規化catalogのsnapshotです。PostgreSQLでは同じcollectionを外部キー付きtableへ初回起動時に決定的に移行します。移行判定と全catalog writeは共通のtransaction advisory lockで直列化され、既存catalogがある場合は起動時に置換しません。

```sh
PYTHONPATH=. python scripts/build_work_catalog.py --write
PYTHONPATH=. python scripts/build_work_catalog.py
```

2つ目のコマンドはchecked-in snapshotが入力と一致することを検証し、`scripts/check.sh`とCIでも実行されます。手動でIDを変更せず、移行・管理repositoryを通して更新します。

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

公開結果とSEOはcatalogを優先して読み、catalog全体を読めない場合だけlegacy inline dataへfallbackします。同じownerについてcatalogとlegacyを結合しません。materialized IDは結果JSON、作品linkのDOM属性、クリックeventへ渡され、旧eventはtitle identityで集計できます。

## Runtime writes

管理画面からの性癖作品・複合作品更新は`Engine`のcatalog repositoryを唯一のproduction入口として扱います。対象ownerのlinkだけcopy-on-writeで差し替えるため、他owner、作品master、販売版metadata、review判断は保持されます。同一ASINは既存`work_id`/`edition_id`を再利用し、異なるASINや曖昧な同名候補は自動統合しません。

- PostgreSQL: catalog advisory lockを最初に取得し、`fetishes.works`と正規化tableを一つのtransactionで更新します。compoundは正規化tableをruntime source of truthとし、worker間の書き込みを同じlockで直列化します。各workerのread cacheは更新workerでは即時破棄され、他workerでは最大5秒のTTL後に追従します。
- Local JSON: `fetishes.json`、`compound_works.json`、`work_catalog.json`のbefore/afterを`work_catalog_mutation_journal.json`へ先にdurable保存します。全ファイルの置換成功後だけjournalを削除し、途中停止時は次回起動でafterへroll-forwardします。通常の書き込み失敗時はbeforeへrollbackします。
- 管理API: 既存のadmin認証・CSRFを維持し、成功した作品更新は件数とowner IDだけを監査ログへ記録します。
- 性癖lifecycle: deleteはその性癖の直接linkとcompound pairを削除し、promoteは新IDへ全ownerをrekeyします。mergeは削除側の直接作品を破棄し、compound pairは保持側へ統合して、既存pairを先・削除側pairを後の順で重複排除します。
- lifecycleのPostgreSQL更新はcatalog、matrix、fetish log、fetish rowを同じtransactionに置きます。ローカル更新はjournal version 2でmatrixとfetish logもbefore/afterへ含め、成功後だけin-memory state/cacheを切り替えます。

## Review policy

`review_queue`は緩いタイトル正規化で近い候補を示すだけで、自動mergeはしません。

- `normalization_candidate`: ASIN衝突がない候補。
- `normalization_conflict`: 複数ASINを持つ候補。必ず人手確認する。

管理者が判断するまでは別`work_id`のまま保持します。


## Backup and restore

`/api/admin/export_matrix`とimport/restore前snapshotは`backup_format_version: 3`として、matrix、全fetish metadata、question schema、`work_catalog`を一つのpayloadへ保存します。

- v3 importはcatalogのschemaと参照整合性をwrite前に検証します。
- PostgreSQLでは不足player fetish、catalog、matrixを同一transactionで復元します。
- ローカルではrestore journal version 2にcatalogのbefore/afterも保存し、途中停止時は3ファイルを同じ世代へroll-forwardします。
- 通常の作品編集journal version 1は3つの作品data fileを、性癖lifecycle journal version 2はさらにmatrixとfetish logを同じ世代へ復旧します。
- 旧v1/v2 matrix backupはcatalogを変更せず、従来どおりimportできます。
- review queueの`decision`、`target_work_id`、`version`、`updated_at`もDB snapshotとrestoreで保持します。

## Migration safety

初回DB移行はlegacy `fetishes.works`のURL補正後に、同一transaction内でcatalog tableへ展開します。ASINまたは厳密な正規化titleだけを自動identityに使い、緩い候補はreview queueへ残します。存在しないfetish IDや同一ID pairを参照するcompound linkは生成時に拒否します。
