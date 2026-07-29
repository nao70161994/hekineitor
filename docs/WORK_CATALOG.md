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

公開結果とSEOはcatalogを優先して読み、catalog全体を読めない場合だけlegacy inline dataへfallbackします。同じownerについてcatalogとlegacyを結合しません。materialized IDは結果JSON、作品linkのDOM属性、クリックeventへ渡され、旧eventはtitle identityで集計できます。legacy fallbackは未変換inlineを返すため、correction manifestによる承認済み差分もraw parity上は意図的な不一致です。healthのapproved projection parityはcatalog訂正の正当性を示しますが、fallback同値性やinline廃止可否はraw parityで別に判定します。

## Runtime writes

管理画面からの性癖作品・複合作品更新は`Engine`のcatalog repositoryを唯一のproduction入口として扱います。対象ownerのlinkだけcopy-on-writeで差し替えるため、他owner、作品master、販売版metadata、review判断は保持されます。同一ASINは既存`work_id`/`edition_id`を再利用し、異なるASINや曖昧な同名候補は自動統合しません。

- PostgreSQL: catalog advisory lockを最初に取得し、`fetishes.works`と正規化tableを一つのtransactionで更新します。compoundは正規化tableをruntime source of truthとし、worker間の書き込みを同じlockで直列化します。全catalog transactionは`work_catalog_meta.revision`を増分し、各workerはread前にrevisionを照合します。変更を検出したworkerはcatalogとrevisionを同じrepeatable-read snapshotから再取得するため、古いcacheをTTL終了まで返しません。
- Local JSON: `fetishes.json`、`compound_works.json`、`work_catalog.json`のbefore/afterを`work_catalog_mutation_journal.json`へ先にdurable保存します。全ファイルの置換成功後だけjournalを削除し、途中停止時は次回起動でafterへroll-forwardします。通常の書き込み失敗時はbeforeへrollbackします。
- 管理API: 既存のadmin認証・CSRFを維持し、成功した作品更新は件数とowner IDだけを監査ログへ記録します。
- 性癖lifecycle: deleteはその性癖の直接linkとcompound pairを削除し、promoteは新IDへ全ownerをrekeyします。mergeは削除側の直接作品を破棄し、compound pairは保持側へ統合して、既存pairを先・削除側pairを後の順で重複排除します。
- lifecycleのPostgreSQL更新はcatalog、matrix、fetish log、fetish rowを同じtransactionに置きます。ローカル更新はjournal version 2でmatrixとfetish logもbefore/afterへ含め、成功後だけin-memory state/cacheを切り替えます。

## Admin catalog API

`GET /api/admin/work_catalog`は全正規化collectionとSHA-256 `digest`を返します。更新は`POST /api/admin/work_catalog/mutate`へ`operation`、`payload`、取得時の`expected_digest`を送り、古いdigestはHTTP 409で拒否されます。master、edition、alias、推薦link metadata、review判断を操作でき、参照中のmaster/edition/alias削除は拒否します。削除、review merge、bulk manifest適用には`confirm_text: WORK_CATALOG`も必要です。全mutationは既存admin認証、CSRF、監査ログの対象です。

review一括適用は`operation: review_apply_manifest`、`payload.decision_manifest`にchecked-in manifest全体を指定します。DBではcatalog lockと一つのtransaction内で全件を適用し、途中の不整合は全体をrollbackします。ローカルでは既存mutation journalを使います。監査ログにはmanifest SHA-256、reviewer、総件数、merge件数、keep件数を保存し、manifest本文は保存しません。

reviewの`keep_separate`または`merge`には現在の`expected_version`が必須です。merge先は候補`work_ids`の一つに限定されます。URLは安全なcanonical URLだけを許可し、タイトル・媒体・context・推薦理由には長さ制限があります。

旧形式をsource of truthから外す判定とrollback手順は[`WORK_CATALOG_MIGRATION.md`](WORK_CATALOG_MIGRATION.md)を参照してください。

## Review policy

`review_queue`は自動統合の根拠ではなく、候補と人手判断の監査証跡です。

- `normalization_candidate`: 緩いタイトル正規化で近く、ASIN衝突がない候補。
- `normalization_conflict`: 緩いタイトル正規化で近く、複数ASINを持つ候補。
- `identity_override`: 英題・和題・略称など、機械的な候補抽出では結び付かないが人手で同一と確認した候補。

未判断の候補は別`work_id`のまま保持します。2026-07-28のseed reviewでは74件すべてを解決し、72件をmerge、2件を`keep_separate`としました。その後、確実なseed cleanupでplaceholder 4件を削除し、46表記をcanonical/alias/contextへ責務分離しました。結果は324 master、239 edition、154 alias、376 fetish link、185 compound link、pending 0で、legacy公開projectionとのmismatchは0です。判断根拠と保留事項は[`WORK_CATALOG_REVIEW_2026-07-28.md`](WORK_CATALOG_REVIEW_2026-07-28.md)に記録します。

## Backup and restore

`/api/admin/export_matrix`とimport/restore前snapshotは`backup_format_version: 3`として、matrix、全fetish metadata、question schema、`work_catalog`を一つのpayloadへ保存します。

- v3 importはcatalogのschemaと参照整合性をwrite前に検証します。
- PostgreSQLでは不足player fetish、catalog、matrixを同一transactionで復元します。
- ローカルではrestore journal version 2にcatalogのbefore/afterも保存し、途中停止時は3ファイルを同じ世代へroll-forwardします。
- 通常の作品編集journal version 1は3つの作品data fileを、性癖lifecycle journal version 2はさらにmatrixとfetish logを同じ世代へ復旧します。
- 旧v1/v2 matrix backupも従来どおりimportでき、復元されたplayer-added fetishにinline作品がある場合は既存の管理済みID・metadata・review判断を保持したまま、その新規ownerのcatalog linkを同じtransaction/journalへ追加します。
- review queueの`decision`、`target_work_id`、`version`、`updated_at`もDB snapshotとrestoreで保持します。

## Migration safety

初回DB移行はlegacy `fetishes.works`のURL補正後に、同一transaction内でcatalog tableへ展開します。ASINまたは厳密な正規化titleだけを自動identityに使い、緩い候補はreview queueへ残します。存在しないfetish IDや同一ID pairを参照するcompound linkは生成時に拒否します。
