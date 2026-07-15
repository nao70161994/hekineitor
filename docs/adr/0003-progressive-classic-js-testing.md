# ADR 0003: Test classic JavaScript progressively

- Status: Accepted
- Date: 2026-07-15

## Context

client codeはbundlerなしでbrowserへ配信するclassic scriptで、既存templateのload orderとglobal互換APIに依存します。テストと設定にはES moduleを使いますが、配信コードの全面的なmodule/framework移行はproduct変更と回帰範囲が大きくなります。syntax checkだけでは状態遷移やDOM契約を十分に検証できません。

## Decision

配信方式とglobal互換APIを維持しながら、検証を段階導入します。

1. ESLintでclassic scriptとmoduleそれぞれのglobal/environmentを明示する。
2. 純粋な状態遷移とDOM境界をVitest/jsdomで高速に検証する。
3. startから回答、結果表示までの代表導線をPlaywrightの最小E2Eで検証する。

既存のFlask smoke testと`node --check`はserver/template配線の回帰検出として維持します。browser E2Eは単体testで表せない統合経路に絞ります。

## Consequences

bundler移行なしで回帰検出を強化できます。一方、classic globalはESLint設定へ明示する必要があり、E2Eは実行時間とbrowser dependencyを追加します。新しいclient logicは可能な限り副作用から分離し、Vitestで先に覆います。
