# Release Checklist

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
- [ ] release commit / CI run: deploy時に記録
- [ ] deploy後のcatalog revision・load failure 0・公開smoke: deploy時に確認

観測waiveは旧inline推薦の保全だけに適用します。catalog整合性、CI、backup、認証、CSRF、監査、公開smokeは引き続き必須です。rollbackは旧inlineではなくv3 catalog backupを使います。
