# ADR 0004: Normalize recommended-work identity and recommendation links

- Status: Accepted
- Date: 2026-07-19

## Context

推薦作品は現在、`fetishes.works` と `compound_works.json` に `{title, url}` をinline保存しています。同じ作品・ASINが複数箇所に複製され、タイトル表記がanalytics上のidentityにもなっています。このため、URL修正、別名統合、複合作品、クリック集計、backup/restoreを一貫して扱えません。

実データには同一ASINの別名、括弧内のキャラクター・版・場面ラベル、同じ正規化候補でも異なるASINを持つ例があります。タイトル正規化だけで自動統合すると別作品・別版を誤ってまとめるため、作品本体、販売版、別名、推薦文脈を分離します。

## Decision

論理モデルを次のcollection/tableに分けます。

- `works_master`: 安定した`work_id`、正式タイトル、正規化タイトル、作品種別、状態。
- `work_editions`: 安定した`edition_id`、`work_id`、ASIN、canonical URL、版・媒体、状態。
- `work_aliases`: 安定した`alias_id`、`work_id`、別名と正規化別名。
- `fetish_work_links`: 性癖、作品、優先販売版・表示alias、表示順、`context_label`、推薦理由。
- `compound_work_links`: 正規化した性癖pairと同じ推薦link属性。

ローカル/seedでは同じ論理collectionを`data/work_catalog.json`に保存し、PostgreSQLでは外部キー付きtableとして保存します。公開表示用には共通resolverが従来互換の`title`と`url`に加えて`work_id`、`edition_id`、`alias_id`を返します。

## Identity and migration rules

- 同一ASINは同一販売版・同一作品として決定的に統合する。
- ASINがない場合は完全一致の正規化タイトルだけを同一作品候補として使う。
- 括弧除去などの緩い正規化はidentityに使わず、review queueの候補作成だけに使う。
- 異なるASINを持つ正規化候補は自動統合しない。
- `work_id`等はmigrationの入力identityから決定的に生成し、再実行しても変わらない。
- title、URL、表示順のlegacy parityをcatalog-first切替の必須条件とする。

## Transition and rollback

1. legacy inline dataからshadow catalogを生成し、決定性・参照整合性・表示parityをCIで固定する。
2. backup formatをcatalog対応へ拡張してrollback手段を先に確保する。
3. PostgreSQL table/local repositoryを追加し、管理writeをtransactional dual-writeへ移行する。
4. 読み取りをcatalog-first、legacy fallbackへ切り替える。混在時に両方を結合しない。
5. 管理CRUD、compound lifecycle、analyticsを安定IDへ移す。
6. 本番parityとrestoreを確認後、inline `works`と`compound_works.json`をsource of truthから外す。

移行中も旧backupと旧イベントは読み取り可能にし、catalog snapshotからlegacy projectionを再生成できる状態をrollback境界とします。

## Consequences

保存構造とmigrationは増えますが、作品修正は一箇所になり、性癖・複合結果ごとの文脈と表示順を失わずに共有できます。クリック分析はタイトル変更から独立し、同名別作品も分離できます。曖昧な候補は管理者reviewが必要であり、自動統合率より誤統合防止を優先します。
