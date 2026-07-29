# Work Catalog Identity Review — 2026-07-28

## Outcome

`data/work_catalog_review_decisions.json`をraw inline catalogへ適用し、74件のreviewをすべて解決しました。

| Item | Before review | After identity review | After safe seed cleanup |
| --- | ---: | ---: | ---: |
| Work master | 423 | 328 | 324 |
| Edition | 239 | 239 | 239 |
| Alias | 115 | 122 | 154 |
| Fetish link | 376 | 376 | 376 |
| Compound link | 189 | 189 | 185 |
| Pending review | 67 | 0 | 0 |
| Projection mismatch | 0 | 0 | 0 |

identity判断の72 merge / 2 keep separateでは公開projectionのtitle、URL、表示順を維持しました。その後のsafe cleanupでは旧公開titleをaliasで保ったまま、明白なplaceholder 4件だけを意図的に推薦から削除しています。manifestはcandidate keyと元work IDを固定し、入力driftを拒否します。

管理APIと同じcanonical JSONで計算したmanifest SHA-256は`6da3aab04feda24b114e746afab44b37f08781443fa242e0971fd6b64780767b`です。

## Explicit cross-title merges

緩い候補抽出だけでは拾えなかった次の7組を`identity_override`としてreview queueへ追加し、元表記をaliasとして保持して統合しました。

- `Given` / `ギヴン`
- `Future Diary` / `ミライニッキ`
- `STEINS;GATE` / `シュタインズ・ゲート`
- `Dungeon Meshi` / `ダンジョン飯`
- `Re:ゼロ` / `Re:ゼロから始める異世界生活`
- `転スラ` / `転生したらスライムだった件`
- `釘宮理恵出演作（ゼロの使い魔・ルイズ）` / `ゼロの使い魔`

## Intentionally kept separate

次の2件はタイトルだけでは巻、スピンオフ、商品単位を安全に判定できず、複数ASINもあるため統合していません。

- `wrv_3cd5ed9375cc6cbbb6a5`: 小林さんちのメイドラゴン。2 work / 2 ASIN。人物別表記が同じシリーズを指す可能性は高いものの、商品とスピンオフの境界が不明。
- `wrv_bc2e31d9182cb45763c5`: ベルセルク。2 work / 2 ASIN。人物・場面別の曖昧な表示名だけでは同一editionと断定しない。

この2件は`status=resolved`、`decision=keep_separate`であり、未処理blockerではありません。シリーズ単位identityへ方針変更するときは、新しいreview manifestで再判断します。

## Data-quality follow-ups

`data/work_catalog_seed_overrides.json`の確実な46表記を適用し、正式作品名を`canonical_title`、旧公開表示をalias、人物・場面・`参考`を52 linkの`context_label`へ分離しました。`魔法老師ネギま！`、`NTRエロゲの金字塔・君が望む永遠`、`カノジョも彼女（直子）`も同じ経路で修正し、公開titleはaliasで維持しています。実作品に推測置換せず、`作品X/Y/Z`と`おれたち○○のいいやつ`は4 master / 4 compound linkを削除しました。ベルセルクとメイドラゴンの`keep_separate`判断には触れていません。

残る確認事項は次のとおりです。

2026-07-29の一次情報監査で優先誤紐付け4件、カテゴリ表記5件、検索URL edition 2件、書誌確認20件を具体化しました。対象ID・根拠・安全な修正方針は[`WORK_CATALOG_DATA_QUALITY_2026-07-29.md`](WORK_CATALOG_DATA_QUALITY_2026-07-29.md)を参照してください。

- edition/ASIN未確認は90 masterで、うち57件は書誌・実在性確認が必要です。媒体、format、editionは推測入力していません。
- 実在未確認の`現実で30歳独身・無職、仮想現実でリア充（参考）`は意図的に未変更です。
- 書誌確認が必要な近似候補: `悪役男爵に転生した件`系、`独り占め×Boyfriend`系。
- 確認待ちの誤記・責務分離: `催眠マイク`、`ヴァンパイア騎士`の人物名、ブランド表記付きタイトル、カテゴリ表記5件。
- ASINを持たないAmazon検索URL 2件は販売版editionとして未確定です。

既存catalogへの適用はdigestで入力を固定した一transactionです。displayの欠落・複数work一致、canonical衝突、削除後の参照残りを拒否し、alias/link IDとowner内positionを決定的に再生成します。同じmanifestの再適用は完全なno-opであり、旧checked catalogからの適用結果がfresh seedと一致することを回帰テストで固定しています。

## Reproduction

```sh
PYTHONPATH=. python scripts/build_work_catalog.py
PYTHONPATH=. python -m pytest -q tests/test_work_catalog.py tests/test_work_catalog_seed_quality.py
```

`/api/admin/works_health`では`automated_parity_ok=true`、`mismatch_count=0`、`pending_review_count=0`を確認します。本番inline廃止には、これに加えて全worker revision一致、fallback/load failureの観測、staging v3 restore rehearsal、手動サインオフが必要です。
