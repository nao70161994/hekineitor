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

この欄は旧inline source of truthを廃止するreleaseで記入します。空欄や未チェックが1つでもあれば廃止しません。

### Evidence

- [ ] retirement候補commit: `________________`
- [ ] 観測開始（JST）: `________________`
- [ ] 観測終了（JST）: `________________`
- [ ] 7日以上・28回以上の連続scheduled rollout gate成功: `first run ________` / `last run ________`
- [ ] 観測中にdeploy、catalog mutation、失敗run、欠測がない
- [ ] worker ID変更・再起動をすべて列挙し、周辺platform logにcatalog unavailable/fallbackがないことを確認
- [x] 24時間以内のv3 backup run / digest: `30538922038` / `4952e3628a7431570265dadb64653699638fa82fdc653d2e3fcb1de8c576c268`
- [x] staging serviceとDBがproductionから隔離済み（確認者）: `Provision Isolated Staging run 30538833713（DB外部接続deny-all確認済み）`
- [x] staging restore workflow run: `30539222595`
- [x] evidence artifact: `staging-v3-restore-rehearsal-30539222595`
- [x] 自動gateがlossless restore、catalog digest、revision、parity、public smokeをすべて通過
- [ ] 通常結果、理由、作品順、追加質問、当て直し、履歴を目視確認
- [ ] compound結果、各要素の決め手、推薦理由を目視確認
- [ ] affiliate遷移、canonical、OGP preview、共有URLのstaging hostを目視確認
- [ ] 確認者 / 完了日時（JST）: `________________` / `________________`
- [ ] rollback担当者 / 実施可能時間: `________________` / `________________`
- [ ] 最終承認者が`RETIRE LEGACY INLINE`を記録: `________________`
