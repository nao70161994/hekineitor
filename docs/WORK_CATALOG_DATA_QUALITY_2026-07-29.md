# Work Catalog Data Quality Audit — 2026-07-29

一次情報なしにASIN・媒体・作品identityを推測しないための監査記録です。対象IDは`data/work_catalog.json`時点であり、本番追加データへの修正は別のdigest-locked manifestで行います。

## Priority identity corrections

| Priority | Current identity | Finding | Safe action | Source |
| --- | --- | --- | --- | --- |
| P0 | `wrk_76a08381045d290abf30` ゼロの使い魔 / edition `wed_c5214e34ec2b68ce172b` | ASIN `B0CVLHHDD3`は別作品『Lv2からチートだった元勇者候補のまったり異世界ライフ』。声優文脈だけで誤統合されている | editionとlinkを新masterへ分離。context=`フェンリース（CV：釘宮理恵）`。既存master/editionを上書きしない | [作品公式](https://lv2-cheat.com/character) |
| P0 | `wrk_5d1a3d2f9813efa92de1` 乙女ゲーム転生もの（アンジェリーク） | ASIN `B0FYCVC6BF`は『学園物の乙女ゲームの世界に転生したけど、チート持ちの背景男子生徒だったようです。（コミック）：9』 | 正式seriesをmaster、巻9をedition、乙女ゲーム転生をcontextへ。アンジェリーク関連付けを除去 | Amazon商品metadataで照合済み。推薦ownerとの適合は要review |
| P0 | `wrk_875e300c4de51e82ed13` テイルズシリーズ（執事キャラ） | ASIN `B07N19VKLX`は『テイルズ オブ ヴェスペリア REMASTER パーフェクトガイド』 | 書名をcanonicalへ。執事キャラ文脈とlink適合性はreview | [バンダイナムコ公式表記](https://www.bandainamcoent.co.jp/license/detail6/) |
| P0 | `wrk_635907b25c09a91c33a9` アンジェリーク（コーエーテクモ） | ASIN `B011KZQVH4`は『由羅カイリ画集 ～アンジェリーク 20th Anniversary～』 | 画集名をcanonicalへ。brandはpublisher metadataへ。別作品identityのaliasを付けない | Amazon商品metadataで照合済み |
| P1 | `wrk_33c8b635e0949835b8cb` NTR同人誌（燃堂力作品） | 燃堂力は『斉木楠雄のΨ難』の登場人物でcreator表記ではない | ASINの商品名・作者確認までlinkをreview/quarantine | [テレビ東京公式人物一覧](https://www.tv-tokyo.co.jp/anime/saikikusuo/chara/index.html) |

P0は別identityのedition混入であり、通常の表記normalizationとして処理しません。新master作成、edition/link再割当、alias/context整理を一つのtransactionで行い、前後projectionと監査digestを保存します。

## Category-like titles and unresolved adult products

次の5 masterは分類語がcanonicalへ混入しています。括弧だけを機械削除せず、正式商品metadataを確認するまでidentity review対象とします。

- `wrk_70c7ec...` `ネトラレーゼ（成人向け漫画）` / ASIN `B07WRK3MF8`
- `wrk_7f498...` `闇の契約（成人向け漫画）` / editionなし
- `wrk_9b707...` `人妻ゆうわく日記（成人向け漫画）` / ASIN `B07PVX5CFT`
- `wrk_c0e365...` `美少年レモネード（成人向け）` / editionなし
- `wrk_d870...` `露出少女日記（成人向け漫画）` / 旧ASIN `B097ZSFLYR`（[作者販売ページ](https://fantia.jp/products/685549)とは別作品と確認し、P0 correctionで作者販売版へ訂正済み）

年齢確認画面で商品title/creator/formatを一次確認できないASINは推測補完しません。

## Search URLs incorrectly stored as editions

- `wed_b8234...` `ヤンキーなのにデレてる（漫画）`: generic descriptorかつAmazon検索URL。editionを削除し、作品identity確定までlink/masterをreview対象にする。
- `wed_ca299...` `逃げるは恥だが役に立つ（漫画）`: canonical=`逃げるは恥だが役に立つ`、media type=`manga`。紙1巻ISBN `9784063409116`は[講談社公式](https://www.kodansha.co.jp/comic/products/0000036370)で確認済み。検索URLをdirect editionへ置換する。

## Confirmed bibliography batch 1

ASINはAmazon直商品ページと照合できた場合だけ登録します。次は出版社公式でwork identity/mediaを確認済みです。

| Work ID | Canonical title / media | Confirmed edition evidence |
| --- | --- | --- |
| `wrk_024d35e969ce0e0e60a5` | 悪役令嬢、セシリア・シルビィは死にたくないので男装することにした。 / novel | [KADOKAWA](https://www.kadokawa.co.jp/product/321904000238/) ISBN 9784041085189 |
| `wrk_0fcf28096047c38c750d` | ありふれた職業で世界最強 / light novel | [OVERLAP](https://www.over-lap.co.jp/%E3%81%82%E3%82%8A%E3%81%B5%E3%82%8C%E3%81%9F%E8%81%B7%E6%A5%AD%E3%81%A7%E4%B8%96%E7%95%8C%E6%9C%80%E5%BC%B7%2B1/product/0/9784865540550/?cat=BNK&swrd=) ISBN 9784865540550 |
| `wrk_16e3c1c2c5c6f71ae45d` | 後宮の烏 / novel | [集英社](https://www.shueisha.co.jp/books/items/contents.html?jdcn=08680188947409000000) ISBN 978-4-08-680188-1 |
| `wrk_286d342ff0d9ff0e1eba` | 私の推しは悪役令嬢。 / novel | [一迅社](https://www.ichijinsha.co.jp/novels/title/%E7%A7%81%E3%81%AE%E6%8E%A8%E3%81%97%E3%81%AF%E6%82%AA%E5%BD%B9%E4%BB%A4%E5%AC%A2%E3%80%82-revolution/%E7%A7%81%E3%81%AE%E6%8E%A8%E3%81%97%E3%81%AF%E6%82%AA%E5%BD%B9%E4%BB%A4%E5%AC%A2%E3%80%82-revolution-1/) 再刊1巻 ISBN 9784758023191 |
| `wrk_2963e9bc04eb994776e4` | 聖女の魔力は万能です / novel | [KADOKAWA](https://www.kadokawa.co.jp/product/321610000556/) ISBN 9784040721859 |
| `wrk_4048f3276783e290bff0` | 悪役令嬢後宮物語 / novel | [アリアンローズ](https://arianrose.jp/novel/?published_id=37) ISBN 978-4-86134-638-5 |
| `wrk_40c906687d851692c4d8` | 高嶺と花 / manga | [白泉社](https://www.hakusensha.co.jp/comicslist/46600/) ISBN 9784592213512 |
| `wrk_6e3204ae78651cf027ac` | スパイ教室 / light novel | [KADOKAWA](https://www.kadokawa.co.jp/topics/4082/) 1巻 ISBN 9784040734804 |
| `wrk_775db3c198f6e12b6c5e` | SPY×FAMILY / manga | [集英社](https://www.shueisha.co.jp/books/items/contents.html?isbn=978-4-08-882011-8) ISBN 978-4-08-882011-8 |
| `wrk_9f859ccf09278af37a98` | 彼女が公爵邸に行った理由 / full-color manga | [KADOKAWA](https://www.kadokawa.co.jp/product/321904000749/) ISBN 9784040659039 |
| `wrk_fcb3804f8a5366e74bd8` | 美しい彼 / BL novel | [徳間書店Chara](https://www.chara-info.net/product/chara-books/8157/) / [NDL](https://ndlsearch.ndl.go.jp/books/R100000038-I4742369) ISBN-13 9784199007804。出版社ページの10桁風表記`4-19-900780-4`はchecksum不正のため登録しない |
| `wrk_bca29c62f61207b80d55` | ロマンティック・キラー / manga | [集英社](https://www.shueisha.co.jp/books/items/contents.html?isbn=978-4-08-882164-1&mode=1&title=books.shueisha.co.jp) ISBN 978-4-08-882164-1 |

媒体まで確認済みだが一意の販売editionを選べない作品は`ef - a fairy tale of the two.`、`スター☆トゥインクルプリキュア`、`囚われのパルマ`、`ロザリオとバンパイア`、`初恋モンスター`、`Free!`です。`罪喰い（漫画）`は確認できた原作がゲームで推薦意図と衝突し、`花は咲くか`は出版社商品ページ不足のため保留します。

## Other confirmed corrections

- `魔法老師ネギま！`は誤記。canonicalは[講談社公式](https://www.kodansha.co.jp/titles/1000000122)の`魔法先生ネギま！`。誤記を公開aliasとして残さない。
- `カノジョも彼女（直子）`の`直子`は公式人物一覧に存在せず、意図候補を自動選定しない。[作品公式](https://kanokano-anime.com/1st/character/)
- `ミライニッキ`は誤記。canonicalは[KADOKAWA公式](https://www.kadokawa.co.jp/product/200605000102/)の`未来日記`。`Future Diary`は有効な英語alias、人物・場面はlink contextへ分離する。

## Applied correction manifest

`data/work_catalog_corrections.json`はschema v3、55件（split 1、retitle 8、quarantine 45、link rebind 1）です。canonical SHA-256は`ad70a6240291b0c5b9501d6c83e9bc617c8060be1a8e9314379e0f5570f7f3c4`です。checked seedはmaster 325、edition 253、edition identifier 14、alias 159、fetish link 373、compound link 141、review 74、pending 0です。根拠不足45作品は同じwork IDの`archived`行として監査可能に保ち、公開linkだけを除去しています。

quarantineはsource work/linkの全field、owner、position、edition URLを固定し、削除後のowner positionを連番化します。inline projectionはforwardでupdate後にremove、reverseでremove復元後にupdateし、同一manifest内の削除から算出した最終positionだけを許容します。`allow_missing`は既適用の不在だけを許容し、同signatureの別owner・別position移動は拒否します。catalog更新・inline同期・逆projectionはいずれもatomic、冪等、fail-closedです。既存のreview timestamp互換とplayer-added owner 104の保護も維持します。
既存のlink rebindは本番で追加された性癖owner 107の推薦だけを対象にするoptionalな`link_rebind`です。作品・版・owner・position・旧link ID・旧aliasなし・表示title・URLをすべて固定し、既存alias `逃げるは恥だが役に立つ（漫画）`へ接続します。canonical titleは短い正式名のまま、inlineの表示titleとURLは変えません。checked seedでは対象linkが存在しないため`allow_missing=true`のno-opです。

## Applied bibliography manifest

schema v2と`data/work_catalog_bibliography.json`で上記12版のISBN-13、版名、出版社、一次情報URLを登録し、媒体だけ確認できた6作品はmedia typeと根拠URLだけを登録しました。canonical SHA-256は`e572a91427ecac77bf278766fed35627f645ea885d69366c010e6891bd2cb908`です。ISBNは全件checksum検証済みで、ISBN-10入力もISBN-13へ正規化されます。全correctionを重ねた現行seedはmaster 325、edition 253、edition identifier 14、alias 159、fetish link 373、compound link 141、review 74、pending 0です。正式名を変更した作品は旧表示をaliasとして保持し、raw parity 0を維持します。

## Auditable research queue

旧記録の「残り37件」は、初期の要調査57件から具体化済み20件を引いた算術だけが保存され、元57件のwork ID一覧と選定規則が残っていません。このため37件を事後に断定すると恣意的な除外が生じます。

`data/work_catalog_research_queue.json`は、確認済み1件を除いた監査履歴45件をすべて`quarantined`として保持します。旧pending 39件はJPO Books、NDL Search、出版社・著者公式ページ、正規電子書店を完全一致titleで再調査しました。`シンデレラの偽装婚約（漫画）`だけは[A-WAGON表記を持つBOOK☆WALKER作品ページ](https://bookwalker.jp/series/549171/)と[コミックシーモア作品ページ](https://www.cmoa.jp/title/335103/)で、原作・鳴田るな、漫画・シキユリ、全8話の同一作品を確認できました。canonicalを`シンデレラの偽装婚約`、media typeを`manga`とし、旧表示はaliasとして保持します。seriesページはidentity根拠に限定し、editionは[BOOK☆WALKERの合本版1商品ページ](https://bookwalker.jp/dedd8698ce-91a7-4354-8239-3cc82613c858/)を`シンデレラの偽装婚約〖合本版〗 1`、publisher `A-WAGON`、format `digital`として登録します。

残る38件は完全一致書誌を確認できず、似た語を含む別作品からidentityを推定しません。既存7件と合わせた45件は元owner pair・position・work ID・理由を失わず、catalog側が`archived`かつ無参照であることをCIで検証します。research queueのpendingは0です。

## Current research candidates

`data/work_catalog_research_candidates.json`は、現行`works_master`が`active`、fetishまたはcompound linkから参照中、かつ`work_editions`を持たない、という固定規則から生成する別artifactです。各作品の全owner参照、媒体種別、`bibliography_state`、catalog digestを保存します。`media_confirmed`は通常またはbatch2書誌manifestに版なしの一次情報根拠がある作品、`identity_unverified`はそれ以外を表します。

これは公開中の推薦に安全な直接版を補うための調査入力です。上記45件のquarantine queueは、根拠不足のため公開から除去済みの履歴と復元根拠です。33件へ45件を混ぜず、候補の減少は版追加またはlink/master状態の明示変更によってのみ発生させます。生成とdrift確認は次を使用します。

```sh
PYTHONPATH=. python scripts/build_work_catalog_research_candidates.py --write
PYTHONPATH=. python scripts/build_work_catalog_research_candidates.py
```

### Active-linked editionless audit batch 2

抽出時点の33件を一次情報で再調査し、13件はexact identityを確認、19件はexact identity未確認、`囚われのパルマ`1件はidentity確認済みでも推薦文脈に不適合と判定しました。`data/work_catalog_corrections_batch2.json`は後二群の計20 masterを`archived`へ移し、元ownerを固定した21 compound linkを除去します。

`data/work_catalog_bibliography_batch2.json`は確認済み13件をinput-lockし、13 editionと12 identifierを追加します。最後に残った`花は咲くか`は、[楽天ブックス](https://books.rakuten.co.jp/rb/6243095/)と[アニメイト](https://www.animate-onlineshop.jp/pn/%E3%80%90%E3%82%B3%E3%83%9F%E3%83%83%E3%82%AF%E3%80%91%E8%8A%B1%E3%81%AF%E5%92%B2%E3%81%8F%E3%81%8B%281%29/pd/65087/)で日高ショーコ著、第1巻、幻冬舎コミックス、ISBN `9784344818279`が一致する紙版を確認し、既存の媒体確認行を同じdigest-lock付きmanifest内で販売版へ昇格しました。batch2適用後のactive・参照中・editionなし候補は0件です。

correction2は公開linkの安全な隔離、bibliography2は一次情報で確認できた書誌だけを担当します。旧45件quarantine queueへ履歴を混ぜず、candidate artifactは最終catalog digestに対して再生成します。

## Adult and intent-conflict audit (2026-07-30)

指定6件は再監査し、根拠不足のまま公開維持しない方針で処理しました。

- `wrk_9b70748b8f29776d9e3d`: ASIN `B07PVX5CFT`を小説`妻は人妻、人妻は妻`へ訂正。作品は保持し、26歳の妻を扱う内容のため熟女推薦linkを除去。
- `wrk_33c8de99aa77f9c17600`: `人妻とNTR（ネトラレ）温泉旅行`へ訂正し、[JPO Books](https://www.books.or.jp/book-details/9784799211441)の紙版ISBN `9784799211441`を追加。幼なじみ要素がないため該当linkを除去。
- `wrk_7d5a75f6654855f5dad5`: 登録rowだけでは同名BL小説と正式題の異なる[Operetta公式ゲーム](https://www.ignote.net/operetta/tumikui/)を識別できないため、ゲームへ推測retitleせずquarantine。
- `wrk_70c7ec0820afa8d25895`: 失効ASINから成人動画seriesの版を特定できないためquarantine。
- `wrk_7f4986ef9061ea40f1a0`、`wrk_c0e3655fd3bad028ca35`: 作者・出版社・公式販売の同一商品根拠がなくquarantine。

追加で、書誌なしの`後宮の謀略令嬢（小説）`、`魔法科のループ転生（小説）`、`同居から始まった仕事人間の恋（漫画）`も、安全な兄弟推薦が残るownerから除去しました。`逃げるは恥だが役に立つ`は[講談社公式](https://www.kodansha.co.jp/comic/products/0000036370)の1巻、ISBN `9784063409116`へ検索URLを置換しています。

## Remaining gates

55件版schema v3 correctionの本番適用は完了しています。workflow run `30517950724`で適用し、適用後backup `30517999082`とrollout gate `30518120489`により、最終digest `a106ff6d35574d48b53e5f554b491ca87800bc7f043efd754d172ebd10966747`、全件数、revision 32、raw/approved parity mismatch 0、fallback/load failure 0を保存しています。適用後catalogはローカルpreflight結果とbyte-equivalentです。

1. staging v3 restore rehearsalは完了済み。
2. 2026-07-31の明示承認により保存継続の観測待ちは撤回し、旧inline source of truthを即時廃止した。

### Phase 2 production rollout (2026-07-30)

release `e0711f6`でbatch 2のcorrection、bibliography、link bindingと、既適用catalogを安全に受理するparity判定を本番へ反映しました。適用前backupはworkflow run `30528863296`、冪等なmanifest適用はrun `30528898955`、適用後rollout gateはrun `30528967729`です。

本番catalogの最終digestは`4952e3628a7431570265dadb64653699638fa82fdc653d2e3fcb1de8c576c268`、revisionは38です。manifest適用ではbatch 2 correction 20件、bibliography 13件、link binding 12件を確認し、再適用時の変更は0件でした。raw/approved projectionはいずれもmismatch 0、pending review 0です。

rollout gateは12 sampleを65.048秒観測し、1 workerのsnapshot/database/cache revisionがすべて38、legacy fallback 0、catalog load failure 0、`retirement_ready=true`、`automated_eligible=true`を確認しました。この観測は移行時の証跡として保存します。2026-07-31の明示承認後はcatalog-only運用へ移行し、旧inline保存は廃止済みです。
