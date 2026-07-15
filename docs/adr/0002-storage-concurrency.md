# ADR 0002: Make storage concurrency explicit

- Status: Accepted
- Date: 2026-07-15

## Context

local JSON engine storageはprocessごとにmemory stateを持ちます。複数processが同じfileへ書くと、file writeをatomicにしても古いmemory snapshotで新しい更新を上書きできます。session SQLiteがprocess間共有できることは、engine stateの安全性を保証しません。

## Decision

JSON engine storageは単一process専用とします。同一process内のthreadはlockされたsnapshot/persistence経路を使えます。起動時のprocess lockを取得できない場合はfail-closedで停止します。複数workerまたは複数replicaで運用する場合は`DATABASE_URL`を設定し、DB transactionと共有state reloadを使用します。

session storageは別の関心事です。local session SQLiteはprocess間共有可能ですが、JSON engine modeのworker制限を緩和しません。

## Consequences

単一processの制約は起動時に明示され、誤った複数worker構成は静かにdataを破損させず停止します。水平scaleが必要な環境ではDB backendの運用とmigrationが必須になります。
