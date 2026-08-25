# Release Checklist

## Game quality and analytics

- [ ] `sh scripts/check.sh`で固定persona評価を含む全gateが成功
- [ ] 評価レポートで平均28問以下、confidence停止後leader変化0、全境界scenario、legacy無信号0、cold-start 1診断1問以下、質問反復0、直接結果名0、実効分散指数`-3.0`
- [ ] 「惜しい」で上位3候補、1件選択、残り表示、候補なし、通信失敗、二重tapを確認
- [ ] 推測結果のnear-missと訂正候補のpositive学習が1つのfeedback batchで保存される
- [ ] 訂正確定の同一再送が二重学習せず、異なる再送・重複IDを拒否し、未選択候補を負例にしない
- [ ] `/api/admin/gameplay_events`で新releaseのversion 2 summaryと`invariants.valid=true`を確認
- [ ] summary CSVに永続識別子、IP、User-Agent、自由記述、回答値がないことをspot check
- [ ] PostgreSQL storage statusの90日保持とrelease別分母を確認
- [ ] rollback時にversionなしイベントがlegacyへ隔離されることを確認

## AdSense

- [x] AdSense 審査コード導入済み
- [x] `templates/index.html` の `<head>` 内に1回だけ設置
- [x] `async` / `crossorigin="anonymous"` を維持
- [x] `npm run test:static` で重複なしを確認

## PWA / Static

- [ ] `/manifest.json` を実機確認
- [ ] `/sw.js` を実機確認
- [ ] `/offline` を実機確認
- [x] `npm run test:pwa` 自動contract確認済み（2026-07-19）

## Public UI / UX

- [x] axe WCAG 2.2 AA、keyboard-only、dialog focus trap/restoreがChromium E2Eで成功（2026-08-22）
- [x] 320px、200%/400%拡大、長い結果名で横overflow・重なりがない（2026-08-22）
- [x] 開始・質問・結果のvisual baseline差分を目視承認し、`npm run test:visual`が成功（2026-08-22）
- [x] offline、回答再照会、resume、共有取消/失敗fallbackで回答と操作導線を失わない（2026-08-22）
- [ ] 開始・質問・結果の段階的開示、条件付き履歴/再開、完走後install、単一共有CTAをDOM/unit/Chromium/visualで確認（2026-08-26変更）
- [ ] `/api/admin/gameplay_events`のWeb Vitals p75、UI error/retry、所要時間のrelease別sampleを確認
- [ ] 公開URLで開始から結果・追加質問・再挑戦・共有fallbackまでtest-playし、health/OGP/PWA検査が成功
- [ ] iOS/Android native share、実screen reader、installed PWA、外部SNS previewは`MANUAL_DEVICE_QA.md`へ記録

## Work catalog inline retirement

2026-07-31にcatalog-only releaseを承認しました。

- [x] owner承認: 「旧おすすめ作品については最悪きえても大丈夫だから、すぐ廃止していいよ」
- [x] 旧inline保全のための7日/28回観測と追加literal確認をwaive
- [x] v3 backup / digest: `30538922038` / `4952e3628a7431570265dadb64653699638fa82fdc653d2e3fcb1de8c576c268`
- [x] 隔離staging restore: workflow `30539222595` / artifact `staging-v3-restore-rehearsal-30539222595`
- [x] lossless catalog restore、revision、public smokeを確認
- [x] 通常/compound診断、作品理由、作品順、追加質問、当て直し、履歴を確認
- [x] affiliate、canonical、OGP、共有URLを確認
- [x] `data/fetishes.json`からinline `works`を削除
- [x] `data/compound_works.json`、旧cache/API、inline backfillを削除
- [x] runtime read/write/restore/reportをcatalog-onlyへ変更
- [x] catalog障害時のfail-closedテストと、旧storage再導入防止contractを追加
- [x] release commit / CI run: `3a1d169` / `30562056642`（Ruff、mypy、coverage、Chromium E2E、PostgreSQL統合を含め成功）
- [x] deploy後のcatalog revision・load failure 0・公開smoke: Ops Check `30562790881`、rollout gate `30562793029`、公開診断30問/推薦3件/理由表示を確認

観測waiveは旧inline推薦の保全だけに適用します。catalog整合性、CI、backup、認証、CSRF、監査、公開smokeは引き続き必須です。rollbackは旧inlineではなくv3 catalog backupを使います。
