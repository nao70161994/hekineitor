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

## ads.txt

AdSense 用の `ads.txt` は `static/ads.txt` に配置し、Flask の `/ads.txt` ルートから `text/plain` で配信します。

現在の内容は審査・設定前の placeholder です。AdSense 側の publisher ID が確定したら `pub-XXXXXXXXXXXXXXXX` を差し替えてください。

```text
google.com, pub-XXXXXXXXXXXXXXXX, DIRECT, f08c47fec0942fa0
```

確認URL:

```text
https://hekineitor.onrender.com/ads.txt
```
