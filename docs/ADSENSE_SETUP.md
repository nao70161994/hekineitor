# AdSense Setup

AdSense client scriptは `ADSENSE_CLIENT` で設定します。広告slotはページごとにIDを設定した場所だけ表示します。

- 対象: `templates/index.html` / `templates/result_share.html` の `<head>` 内
- client: 環境変数 `ADSENSE_CLIENT` (`ca-pub-8683516545883768`)
- script: `https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=$ADSENSE_CLIENT`
- `async` と `crossorigin="anonymous"` を維持
- 重複防止と未設定時の非表示は `tests/test_smoke.py` の AdSense smoke test で確認

確認コマンド:

```sh
npm run test:static
npm run test:pwa
```

## ads.txt

AdSense 用の `/ads.txt` は起動時の `ADSENSE_CLIENT` から Publisher ID を導出して返す構成です。`ADSENSE_CLIENT` 未設定時は `static/ads.txt` をフォールバックとして配信します。

現在の publisher ID は `pub-8683516545883768` です。Render では `ADSENSE_CLIENT=ca-pub-8683516545883768` を設定してください。

```text
google.com, pub-8683516545883768, DIRECT, f08c47fec0942fa0
```

確認URL:

```text
https://hekineitor.onrender.com/ads.txt
```

Render 環境変数:

```text
ADSENSE_CLIENT=ca-pub-8683516545883768
```

`ADSENSE_CLIENT` 未設定時は広告 script / slot は出力されません。clientだけ設定してslot IDがない場合も、広告scriptと枠は出ません。

CSP では AdSense の所有権確認と広告表示に必要な `https://pagead2.googlesyndication.com`、`https://ep1.adtrafficquality.google` / `https://ep2.adtrafficquality.google`、`https://www.google.com` などの最小ドメインを許可します。

## Minimal Ad Slots

`ADSENSE_CLIENT` と対応する広告ユニットIDが設定されている場合のみ、`templates/_adsense_slot.html` を通じて広告枠を表示します。slot IDは数字のみ受け付け、未設定や `0000000000` は無効として扱います。

配置:

- トップページのスタート説明文の直後
- 診断結果画面の下部
- 共有結果ページのCTA下部

Renderでは実際に作成した広告ユニットIDを、使用する場所ごとに設定してください。

```text
ADSENSE_SLOT_HOME=<トップページのslot ID>
ADSENSE_SLOT_RESULT=<診断結果画面のslot ID>
ADSENSE_SLOT_SHARE=<共有結果ページのslot ID>
```

質問中・回答ボタン付近には表示しません。

広告slotを使わない場所は対応する環境変数を設定しないでください。slot IDをテンプレートへ直接書き込む必要はありません。
