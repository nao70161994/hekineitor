# AdSense Setup

AdSense 審査コードは導入済みです。

- 対象: `templates/index.html` の `<head>` 内
- client: `ca-pub-8683516545883768`
- script: `https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-8683516545883768`
- `async` と `crossorigin="anonymous"` を維持
- 重複防止は `tests/test_smoke.py::TestSmoke::test_index_contains_adsense_review_script_once` で確認

確認コマンド:

```sh
npm run test:static
npm run test:pwa
```
