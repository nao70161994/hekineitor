# Work Catalog

おすすめ作品のsource of truthをinline `{title, url}` から安定ID付きcatalogへ移行するためのデータ契約です。設計判断は[`adr/0004-normalized-work-catalog.md`](adr/0004-normalized-work-catalog.md)を参照してください。

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

```sh
PYTHONPATH=. python scripts/sync_work_catalog_inline.py --write
PYTHONPATH=. python scripts/build_work_catalog.py --write
PYTHONPATH=. python scripts/sync_work_catalog_inline.py
PYTHONPATH=. python scripts/build_work_catalog.py
```

`sync_work_catalog_inline.py`はcorrection manifestで承認されたtitle/URL差分だけを、ownerとpositionを変えずに`fetishes.json`と`compound_works.json`へ投影します。位置・source signature・URL・ownerのdriftはfail-closedです。catalog buildは訂正済みinlineを厳密にsource状態へ逆投影してからreviewとcorrectionを再適用するため、既存の安定IDとcatalog digestは変わりません。検証コマンドは`scripts/check.sh`とCIでも実行されます。手動でIDや承認済み表示を変更せず、manifestと同期scriptを通して更新します。

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

公開結果とSEOはcatalogを優先して読み、catalog全体を読めない場合だけlegacy inline dataへfallbackします。同じownerについてcatalogとlegacyを結合しません。materialized IDは結果JSON、作品linkのDOM属性、クリックeventへ渡され、旧eventはtitle identityで集計できます。checked inlineとcorrection適用時のDB `fetishes.works`は承認済み表示へ同期し、fallbackでもcatalogと同じtitle/URL/orderを返します。healthのapproved projection parityはmanifest適用の正当性を、raw parityは実際のfallback同値性とinline廃止可否を独立に検証します。

## Runtime writes

管理画面からの性癖作品・複合作品更新は`Engine`のcatalog repositoryを唯一のproduction入口として扱います。対象ownerのlinkだけcopy-on-writeで差し替えるため、他owner、作品master、販売版metadata、review判断は保持されます。同一ASINは既存`work_id`/`edition_id`を再利用し、異なるASINや曖昧な同名候補は自動統合しません。
- correction manifestはcatalogとlegacy inlineを同じcommit単位で同期します。PostgreSQLはcatalog lock下で対象`fetishes.works`を同一transactionへ含め、Local JSONはfetish・compound・catalogを一つのjournalへ含めます。player-added ownerでmanifest sourceが既に置換済みの場合は、その作品を保持したまま明示された`allow_missing`だけをno-opにします。成功応答には適用link数、fetish/compound owner数、許可済みmissing数を含めます。

- PostgreSQL: catalog advisory lockを最初に取得し、`fetishes.works`と正規化tableを一つのtransactionで更新します。compoundは正規化tableをruntime source of truthとし、worker間の書き込みを同じlockで直列化します。全catalog transactionは`work_catalog_meta.revision`を増分し、各workerはread前にrevisionを照合します。変更を検出したworkerはcatalogとrevisionを同じrepeatable-read snapshotから再取得するため、古いcacheをTTL終了まで返しません。
- Local JSON: `fetishes.json`、`compound_works.json`、`work_catalog.json`のbefore/afterを`work_catalog_mutation_journal.json`へ先にdurable保存します。全ファイルの置換成功後だけjournalを削除し、途中停止時は次回起動でafterへroll-forwardします。通常の書き込み失敗時はbeforeへrollbackします。
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

未判断の候補は別`work_id`のまま保持します。2026-07-28のseed reviewでは74件すべてを解決し、72件をmerge、2件を`keep_separate`としました。その後、確実なseed cleanup、P0訂正、一次書誌batchを適用しました。現行seedは325 master、253 edition、14 edition identifier、159 alias、373 fetish link、141 compound link、pending 0です。媒体種別は23件、紙版metadataは12件で、legacy公開projectionとのmismatchは0です。判断根拠と保留事項は[`WORK_CATALOG_REVIEW_2026-07-28.md`](WORK_CATALOG_REVIEW_2026-07-28.md)と[`WORK_CATALOG_DATA_QUALITY_2026-07-29.md`](WORK_CATALOG_DATA_QUALITY_2026-07-29.md)に記録します。

## Backup and restore

`/api/admin/export_matrix`とimport/restore前snapshotは`backup_format_version: 3`として、matrix、全fetish metadata、question schema、`work_catalog`を一つのpayloadへ保存します。

- v3 importはcatalogのschemaと参照整合性をwrite前に検証し、backupのinline fetish worksをcatalogのcorrection状態へforward/reverse投影してraw parity 0を要求します。
- PostgreSQLでは不足player fetish、既存ownerのinline works、catalog、matrixを同一transactionで復元します。compound inlineはdeploy artifactであるため、backup catalogに合わせたforward/reverse投影が現行compound fileを変更する場合は、matching source/target code/data revisionを要求してDB write前にfail-closedします。
- ローカルではrestore journal version 2にfetish inline、compound inline、catalog、matrixのbefore/afterを保存し、途中停止時は同じ世代へroll-forwardします。
- 通常の作品編集journal version 1は3つの作品data fileを、性癖lifecycle journal version 2はさらにmatrixとfetish logを同じ世代へ復旧します。
- 旧v1/v2 matrix backupも従来どおりimportでき、復元されたplayer-added fetishにinline作品がある場合は既存の管理済みID・metadata・review判断を保持したまま、その新規ownerのcatalog linkを同じtransaction/journalへ追加します。
- review queueの`decision`、`target_work_id`、`version`、`updated_at`もDB snapshotとrestoreで保持します。

## Migration safety

初回DB移行は訂正済みchecked inlineをsource状態へ厳密に逆投影してから、同一transaction内でcatalog tableへ展開し、review、correction、bibliographyを順に適用します。これにより公開projectionを保ったまま、版識別子と根拠metadataを正規化できます。ASINまたは厳密な正規化titleだけを自動identityに使い、緩い候補はreview queueへ残します。存在しないfetish IDや同一ID pairを参照するcompound linkは生成時に拒否します。

forward/reverse投影は任意の履歴変換ではありません。checked correction manifestが認識するsourceまたはtarget signatureだけを受け入れます。古いbackupへ戻す場合は、catalog snapshotと同じ世代のcode/data artifactを組にして扱います。
