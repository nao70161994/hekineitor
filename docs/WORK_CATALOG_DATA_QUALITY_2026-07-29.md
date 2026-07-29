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
- `wrk_d870...` `露出少女日記（成人向け漫画）` / ASIN `B097ZSFLYR`（シリーズ存在は[作者販売ページ](https://fantia.jp/products/685549)で確認、ASINとの同一性は未確認）

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
| `wrk_fcb3804f8a5366e74bd8` | 美しい彼 / BL novel | [徳間書店Chara](https://www.chara-info.net/product/chara-books/8157/) ISBN-10 4-19-900780-4 |
| `wrk_bca29c62f61207b80d55` | ロマンティック・キラー / manga | [集英社](https://www.shueisha.co.jp/books/items/contents.html?isbn=978-4-08-882164-1&mode=1&title=books.shueisha.co.jp) ISBN 978-4-08-882164-1 |

媒体まで確認済みだが一意の販売editionを選べない作品は`ef - a fairy tale of the two.`、`スター☆トゥインクルプリキュア`、`囚われのパルマ`、`ロザリオとバンパイア`、`初恋モンスター`、`Free!`です。`罪喰い（漫画）`は確認できた原作がゲームで推薦意図と衝突し、`花は咲くか`は出版社商品ページ不足のため保留します。

## Other confirmed corrections

- `魔法老師ネギま！`は誤記。canonicalは[講談社公式](https://www.kodansha.co.jp/titles/1000000122)の`魔法先生ネギま！`。誤記を公開aliasとして残さない。
- `カノジョも彼女（直子）`の`直子`は公式人物一覧に存在せず、意図候補を自動選定しない。[作品公式](https://kanokano-anime.com/1st/character/)
- `ミライニッキ`は誤記。canonicalは[KADOKAWA公式](https://www.kadokawa.co.jp/product/200605000102/)の`未来日記`。`Future Diary`は有効な英語alias、人物・場面はlink contextへ分離する。

## Applied P0 correction manifest

`data/work_catalog_corrections.json`で上記P0 4件を実装済みです。canonical SHA-256は`2e629957bd11a85f14269298aa8227298faa16fdba21cf82e19fbceb9d0bf76e`、内訳はsplit 1件・retitle 3件です。checked seedはmaster 325、edition 239、alias 150、fetish link 376、compound link 185、review 74、pending 0です。source row完全一致を基本とし、review timestampはchecked seedの2026-07-28と旧79件manifest由来の2026-07-29だけを明示許可し、同一UTC instantのdate/ISO表現を受け入れます。本番のplayer-added owner 104置換で既に不存在のseed alias/linkだけは`allow_missing`で再作成せず、存在時のdrift、未許可日付、他field差異、collision/dangling参照は拒否します。owner/position維持、冪等再適用、fresh v3 backup由来の本番preflightを自動テストで固定しています。

## Remaining gates

1. `work_editions`へISBNなどASIN以外の書誌識別子を保持できる設計を追加する。
2. 確認済みmedia typeとedition evidenceをseedへ取り込み、未確認値は空のままにする。
3. 残り37件の書誌・実在性を一次ソースで調査する。
4. adult product 4件と推薦意図衝突2件を人手確認する。
