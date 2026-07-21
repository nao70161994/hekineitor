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
- 旧v1/v2 matrix backupはcatalogを変更せず、従来どおりimportできます。
- review queueの`decision`、`target_work_id`、`version`、`updated_at`もDB snapshotとrestoreで保持します。

## Migration safety

初回DB移行はlegacy `fetishes.works`のURL補正後に、同一transaction内でcatalog tableへ展開します。ASINまたは厳密な正規化titleだけを自動identityに使い、緩い候補はreview queueへ残します。存在しないfetish IDや同一ID pairを参照するcompound linkは生成時に拒否します。
