# UI / UX audit

最終更新: 2026-08-26

## 目標と守る設計

初見利用者が迷わず開始し、間接的・抽象的な質問へ直感で答え、適応的な終了を理解し、結果の根拠を確認してからfeedback・追加質問・再挑戦・共有へ進める状態を目標とします。質問で答えを直接尋ねないこと、質問文だけで意味が成立すること、raw posteriorで質問停止を判断すること、最終結果だけへ強い露出分散指数`-3`を適用することは変更しません。

## 監査で確認した問題と対応

| 優先度 | 問題 | 受入基準 | 対応・証拠 |
|---|---|---|---|
| P0 | 適応終了なのに固定分母や推論段階を重ねて表示 | 残り問数を約束せず現在問数だけを示す | 質問画面を「質問 N」、戻る、中断、自己完結した質問、5回答、必要時の通信状態へ限定 |
| P0 | 曖昧な通信失敗で回答済みか不明なまま再操作できる | 同じrequest IDでのみ再照会し、二重回答しない | 回答ボタンlock、状態文、明示再照会、server replay契約、unit/Chromium E2E |
| P0 | 根拠・候補比較・作品・方法論と複数CTAが結果を埋める | 第一階層だけで結果を理解・評価でき、補足は任意に開ける | 結果名、短い説明、一致度、簡易feedback、共有、再プレイを主表示にし、根拠・候補・作品・詳細評価を`aria-expanded`付き「詳しく見る」へ格納 |
| P1 | 開始前の説明、履歴、再開、広告が主CTAと競合 | 初見は即開始でき、状態依存導線だけ必要時に現れる | 見出し、開始、所要時間へ縮約。履歴は保存時だけ、再開はdraft時だけ表示し、再開を主・新規開始を副にする。広告はCTA後へ配置 |
| P1 | 質問の補助ヒント、内部axis、進捗文が本文と重複・誘導 | 表示上の質問は自己完結した本文のみ | `answer_frame`、axis、ヒント、進捗バーを廃止し、回答尺度は初問だけ表示 |
| P1 | 小画面、拡大、safe-area、dialog、focus、contrastの保証不足 | WCAG 2.2 AA目標、320px、400%、keyboard-onlyで操作可能 | semantic section/headings、skip link、48px target、focus trap/restore、inert、tokens、forced-colors/reduced-motion、axe E2E |
| P1 | offline・SW更新時に回答喪失や行き止まりの説明不足 | 下書きを保ち、更新中断と再試行方法を明示 | 7日draft、更新前保存、送信中の更新延期、online/offline toast、retryable error文、PWA unit |
| P2 | UI改善の効果をrelease別に判断できない | 個人情報なしで所要時間、retry/error、共有、Core Web Vitalsを測れる | version 2 summary拡張、LCP/CLS/INP p75、上限値、release別集計、契約テスト、90日保持 |
| P2 | inline styleと非semantic候補グラフが保守・読み上げを阻害 | 状態をcomponent classへ寄せ、値を支援技術へ公開 | template inline style除去、design token、`progress`候補比較、入力label、候補button化 |

## 段階的開示の表示契約

| 状態 | 常時表示 | 条件付き・展開後 |
|---|---|---|
| 開始 | ブランド、魔人、短い期待形成文、開始、所要時間 | 履歴、再開、広告 |
| 質問 | 現在問数、戻る、中断、質問文、5回答 | 初問の回答尺度、送信・復旧状態 |
| 結果 | 結果名、短い説明、一致度、簡易feedback、共有、再プレイ | 根拠、候補比較、関連・作品、方法注記、詳細評価、再プレイ方法 |

PWAインストールは完走済みの端末でだけ提示し、service worker更新通知はこの制限を受けません。共有は主CTAを1つにし、native shareが使えない場合または失敗時にcopyとXの選択dialogを表示します。


## 自動検証範囲

- Python: route、session互換性、匿名event、保持・CSV・不変条件、SEO/OGP/PWA contract
- Vitest: 回答pending/reconcile、draft/resume、share fallback、dialog focus、PWA update、offline、Web Vitals、renderer
- Chromium: 完走、戻る、resume、追加質問、feedback、共有fallback、mobile、axe、keyboard、zoom
- Visual: 375pxの開始・質問、1280pxの結果をLinux Chromium PNG baselineと比較
- 公開read-only QA: health、crawler meta、1200×630 PNG、manifest、service worker、offline

2026-08-26の変更では3画面のbaselineを更新・目視承認してから通常CIへ取り込みます。画面切替時のskip link誤露出、非実データ形式fixtureによる重複名・空の割合表示を画像から検出して修正し、通常CIで差分を失敗扱いにします。

## 実利用データの扱い

UI変更の評価はrelease別sampleで行います。十分な実利用baselineがない状態で、離脱率や所要時間を推測して質問数・停止条件・強い分散設計を変更しません。イベントはURL、IP、User-Agent、永続user/session/run ID、自由記述、回答値を含めません。新しい性癖名・説明を利用者が任意登録する導線だけは、その入力内容を明示的にserverへ送ります。

## 自動化できない境界

iOS Safari、Android Chrome、OS native share sheet、installed PWA更新、VoiceOver/TalkBack、X/LINE/Discord実previewは物理端末・外部account固有です。再現手順、期待値、記録欄は[`MANUAL_DEVICE_QA.md`](MANUAL_DEVICE_QA.md)を正とし、自動検査済み項目と混同しません。
