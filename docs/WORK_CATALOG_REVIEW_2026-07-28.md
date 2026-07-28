# Work Catalog Identity Review — 2026-07-28

## Outcome

`data/work_catalog_review_decisions.json`をraw inline catalogへ適用し、74件のreviewをすべて解決しました。

| Item | Before review | After review |
| --- | ---: | ---: |
| Work master | 423 | 328 |
| Edition | 239 | 239 |
| Alias | 115 | 122 |
| Fetish link | 376 | 376 |
| Compound link | 189 | 189 |
| Pending review | 67 | 0 |
| Projection mismatch | 0 | 0 |

判断はmerge 72件、keep separate 2件です。公開projectionのtitle、URL、表示順は維持されています。manifestはcandidate keyと元work IDを固定し、入力driftを拒否します。

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

identity migrationとは分けて扱う項目です。現時点では94 masterにedition/ASINがなく、実在性や販売版URLを自動確認できません。特に次を運用review対象にします。

- 書誌確認が必要な近似候補: `悪役男爵に転生した件`系、`独り占め×Boyfriend`系。
- canonical titleへの人物・用途・評価文混入: `賭ケグルイ（…）`、`Killing Stalking（参考）`、`School Days（参考）`、`NTRエロゲの金字塔・君が望む永遠`など。
- 誤記疑い: `魔法老師ネギま！`、`催眠マイク`、`ヴァンパイア騎士`の人物名、ブランド表記付きタイトルなど。
- placeholder疑い: `作品X/Y/Z`、`おれたち○○のいいやつ`。

これらは確認なしに削除・改名・統合すると推薦意図や公開表示を変えるため、identity manifestには混ぜていません。書誌確認後はcanonical title、alias、edition、context labelをそれぞれの責務へ移し、変更前後のprojectionを個別に承認します。

## Reproduction

```sh
PYTHONPATH=. python scripts/build_work_catalog.py
PYTHONPATH=. python -m pytest -q tests/test_work_catalog.py
```

`/api/admin/works_health`では`automated_parity_ok=true`、`mismatch_count=0`、`pending_review_count=0`を確認します。本番inline廃止には、これに加えて全worker revision一致、fallback/load failureの観測、staging v3 restore rehearsal、手動サインオフが必要です。
