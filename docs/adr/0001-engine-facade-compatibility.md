# ADR 0001: Preserve the Engine facade contract

- Status: Accepted
- Date: 2026-07-15

## Context

推論・学習・永続化の実装は`engine/`内で責務分割されています。一方、アプリとテストは歴史的に`engine` moduleの`Engine`、helper、定数、patch pointを参照しています。内部整理のたびに呼び出し側まで同時変更すると、診断確率や学習deltaの回帰を見落としやすくなります。

## Decision

`engine/__init__.py`を公開入口とし、`Engine`の公開method signature、公開import、必要なpatch pointを互換facadeとして維持します。内部moduleへの分割は可能ですが、推論結果、質問選択、学習delta、永続化形式、DB transaction、session keyの契約変更とは分離します。

変更時は[`../ENGINE_FACADE_CONTRACT.md`](../ENGINE_FACADE_CONTRACT.md)とcontract/regression testsを同時に更新します。意図的な契約変更はmigration pathを明示した別変更として扱います。

Top-level `engine_*` modulesは外部caller向けの互換shimとして保持します。アプリケーションコードは`engine.*`を直接importし、互換性testと移行script以外からshimへの新規依存を追加しません。静的checkでこの依存方向を固定します。

shimを削除できるのは、repository内のproduction参照が0であることに加え、外部caller向けのdeprecation期間を設け、major migrationとして公開import更新手順を提示できた場合だけです。単なる内部行数削減を理由には削除しません。

## Consequences

内部moduleは小さくできますが、互換wrapperが残る場合があります。重複を機械的に除去することより、公開境界での安定性と回帰testを優先します。

## References
- [`../ENGINE_FACADE_CONTRACT.md`](../ENGINE_FACADE_CONTRACT.md)
