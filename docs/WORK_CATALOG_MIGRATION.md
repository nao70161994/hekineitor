# Work Catalog Retirement Record

旧inline `fetishes.works` / `compound_works.json` から、正規化catalogだけを使う構成への移行記録です。

## Status

2026-07-31にretirementを実施しました。現在の唯一のおすすめ作品source of truthは次のとおりです。

- Local/seed: `data/work_catalog.json`
- PostgreSQL: `works_master`、`work_editions`、`work_edition_identifiers`、`work_aliases`、`fetish_work_links`、`compound_work_links`、`work_identity_reviews`

`data/fetishes.json`は性癖metadataだけを保持し、`works`を持ちません。`data/compound_works.json`、旧cache helper、旧module-level CRUD、inline seed backfill endpointは削除済みです。DBの`fetishes.works`列は旧schemaとの安全な互換のため物理的には残しますが、起動時に`[]`へ消去し、その後は読み書きしません。

## Approval and observation waiver

従来の「7日間以上かつscheduled gate 28回以上」という条件は、legacy fallbackを保持したまま無損失で廃止するための保守的なpolicyでした。2026-07-31、ownerから「旧おすすめ作品については最悪きえても大丈夫だから、すぐ廃止していいよ」と明示承認がありました。

この承認により、旧inlineデータの保持を目的とした観測期間と追加のliteral確認文はwaiveしました。正規化catalog、本番revision 38、pending review 0、staging v3 restore rehearsal成功という既存証跡は維持します。waiveの対象は旧inline推薦の保全だけであり、catalog整合性、テスト、backup、認証、CSRF、監査、公開smokeの品質条件は免除しません。

## Runtime behavior

- すべての通常/compound推薦readはnormalized catalog resolverを使います。
- catalog取得・validationに失敗した場合は`RuntimeError`でfail closedし、旧inlineへfallbackしません。
- 性癖作品編集、compound作品編集、manifest、性癖delete/merge/promoteはcatalogだけをtransactionalに更新します。
- Local JSONのmutation journalはformat version 3で、fetish metadata、catalog、および必要なlifecycle stateだけを同世代へcommit/rollbackします。
- PostgreSQLのcatalog mutationはadvisory lockとrevisionを維持します。互換列`fetishes.works`へdual-writeしません。
- v3 backup/restoreは`work_catalog`を作品情報として復元します。v1/v2 backupに含まれるinline worksは意図的に無視します。

## Historical migration reproducibility

初期catalog生成の決定性を検証する旧inline入力は、production dataではなく`tests/fixtures/legacy_work_catalog/`にテストfixtureとして隔離しました。`scripts/build_work_catalog.py`はこのfixtureから現行catalogを再生成してbyte一致を検証します。fixtureはruntime、seed、rollbackのsourceではありません。

## Deploy verification

1. CIでPython/static/JS/coverage/Chromium E2Eを通す。
2. release前にv3 backupを取得し、catalog digest、revision、pending review 0を記録する。
3. deploy後に`/api/admin/works_health`で`retirement.policy=catalog_only`、`retirement.completed=true`、catalog revision一致、load failure 0を確認する。
4. 通常結果、compound結果、作品順、推薦理由、affiliate URL、SEO/OGP、共有、履歴をsmoke testする。
5. PostgreSQLの`fetishes.works`が空で、正規tableの件数と公開projectionが維持されていることを確認する。

## Production verification (2026-07-31)

- Final application commit: `3a1d169`
- CI: run `30562056642`（Ruff、mypy、全Python/JS、coverage、Chromium E2E、PostgreSQL lifecycle成功）
- Read-only Ops Check: run `30562790881` success
- Catalog rollout gate: run `30562793029` success。12 samples / 62.895秒、revision snapshot/database/cacheすべて38、legacy fallback 0、catalog load failure 0、blocker 0、manual signoff不要を確認
- 公開smoke: `/health` status ok / PostgreSQL / matrix 137x153、実診断30問を完走し、結果理由と推薦作品3件を確認

## Rollback

旧inline fallbackは復活させません。問題発生時は次の順でcatalogを復旧します。

1. 管理更新を停止し、現在のv3 backupを追加保存する。
2. 直前の正常なv3 backupから`work_catalog`とmatrix/fetish metadataを同一transactionでrestoreする。
3. code rollbackが必要なら、catalog-only契約を持つ直前releaseへ戻す。
4. catalog digest/revision、通常/compound推薦、affiliate、SEO/OGP、共有を再確認する。
5. 原因、影響owner、復元digestを監査記録へ残す。

旧inlineデータをrollback sourceとして使うことはありません。
