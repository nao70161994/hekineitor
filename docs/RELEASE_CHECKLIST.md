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
- [ ] `npm run test:pwa` を実行
