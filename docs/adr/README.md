# Architecture Decision Records

ADRは、今後の変更でも維持すべき判断と理由を短く記録します。

| ADR | Status | Decision |
| --- | --- | --- |
| [0001](0001-engine-facade-compatibility.md) | Accepted | `engine` packageの公開facade互換性を維持する |
| [0002](0002-storage-concurrency.md) | Accepted | JSON storageは単一process、複数workerはDBを使う |
| [0003](0003-progressive-classic-js-testing.md) | Accepted | classic JSを維持しつつESLint/Vitest/Playwrightを段階適用する |

新しい判断は連番ファイルで追加します。判断を置き換える場合は元のADRを`Superseded`にし、後継ADRへのリンクを残します。
