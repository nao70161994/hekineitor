# AdSense Setup

AdSense 審査コードと最小広告枠は導入済みです。

- 対象: `templates/index.html` / `templates/result_share.html` の `<head>` 内
- client: 環境変数 `ADSENSE_CLIENT` (`ca-pub-8835165458837368`)
- script: `https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=$ADSENSE_CLIENT`
- `async` と `crossorigin="anonymous"` を維持
- 重複防止と未設定時の非表示は `tests/test_smoke.py` の AdSense smoke test で確認

確認コマンド:

```sh
npm run test:static
npm run test:pwa
```

## ads.txt

AdSense 用の `ads.txt` は `static/ads.txt` に配置し、Flask の `/ads.txt` ルートから `text/plain` で配信します。

現在の publisher ID は `pub-8835165458837368` です。Render では `ADSENSE_CLIENT=ca-pub-8835165458837368` を設定してください。

```text
google.com, pub-8835165458837368, DIRECT, f08c47fec0942fa0
```

確認URL:

```text
https://hekineitor.onrender.com/ads.txt
```

Render 環境変数:

```text
ADSENSE_CLIENT=ca-pub-8835165458837368
```

`ADSENSE_CLIENT` 未設定時は広告 script / slot は出力されません。

CSP では AdSense の所有権確認と広告表示に必要な `https://pagead2.googlesyndication.com` などの最小ドメインを許可します。

## Minimal Ad Slots

`ADSENSE_CLIENT` が設定されている場合のみ、`templates/_adsense_slot.html` を通じて最小広告枠を表示します。未設定時は script も slot も出力しません。

配置:

- トップページのスタート説明文の直後
- 診断結果画面の下部
- 共有結果ページのCTA下部

質問中・回答ボタン付近には表示しません。

AdSense の広告ユニットIDが確定したら、`templates/_adsense_slot.html` の placeholder `data-ad-slot="0000000000"` を差し替えてください。
