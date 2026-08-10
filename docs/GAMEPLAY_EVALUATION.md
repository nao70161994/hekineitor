# ゲームプレイ自動評価

`scripts/evaluate_gameplay.py`は、質問文、matrix、推論、質問選択、結果分散の変更を固定条件で比較するオフラインregression harnessです。`scripts/check.sh`からCI gateとして実行されます。

## 循環評価を避けるfixture

`tests/fixtures/gameplay_personas.json`には、精度を採点する8種類の代表personaと、IDK多め・近接候補・除外再挑戦の3種類の境界personaを保存します。回答は人手でレビューした強い回答と未指定の軸に対する穏やかな既定回答であり、現在のmatrix確率からsampling・生成しません。境界personaは制御フローを検証するため`accuracy_scored: false`とし、通常personaのTop1/Top3を歪めません。

評価は2種類です。

- transcript: 人手で明示した回答だけをholdoutとして一括推論し、Top1/Top3とconfidence calibrationを測る。
- adaptive: 実際の質問選択、複合的な停止判定、最大30問、IDK回復、低露出軸probe、除外を再現し、personaが選ばれた質問へ回答する。

personaのtargetや回答を変更する時は、質問文の意味と期待する嗜好像を人がレビューします。品質gateを通す目的でmatrixの値を読み取って回答を自動反転させてはいけません。

## 出力する指標

- transcript/adaptiveのTop1・Top3正解率
- top confidenceのBrier score（小さいほど良い）
- 平均質問数
- 各回答前後のentropy差による平均情報利得と、persona別`question_trace`・質問ID別`question_metrics`
- `exp(entropy)`で表した実効候補数の平均削減量（各質問の前後差もtraceへ記録）
- legacy無信号質問とcold-start質問の選択数
- 質問反復数と質問ID transcript
- 結果分布と最大集中のgate
- 強い結果分散の実効べき指数`-3`、数式一致、低露出候補のboost数
- seed、最大質問数、実行秒数
- 停止理由、停止時のraw Top1/Top2比・実効候補数・leader安定回答数、停止後30問までshadow継続した場合のleader変化
- standard / IDK多め / 近接候補 / 除外再挑戦のscenario coverage
- 結果名を直接含む質問と`answer_frame`欠落の件数

## 実行方法

```sh
PYTHONPATH=. python scripts/evaluate_gameplay.py \
  --baseline tests/fixtures/gameplay_eval_baseline.json \
  --check \
  --output /tmp/gameplay_eval_report.json
```

seedの既定値は`20260809`です。`--check`は絶対閾値またはbaseline許容差を外れるとexit 1にし、`quality_gate.failures`へcheck名、delta、理由を出します。baselineは`tests/fixtures/gameplay_eval_baseline.json`です。

`adaptive.rows[].question_trace`には質問ID、persona回答、情報利得、実効候補削減量、無信号/cold-start判定を残します。`adaptive.question_metrics`は同じ値を質問IDごとに集約するため、平均指標が悪化した時に原因となった質問まで追跡できます。

質問継続と停止はraw posteriorで評価し、指数`-3`の分散補正は最終結果順位にだけ適用します。最低12問まではconfidenceで終了せず、その後は絶対確率だけでなくTop1/Top2比、posterior entropyから算出した実効候補数、同じleaderが続いた回答数を組み合わせます。hard limitは30問、IDK連続終了は6回です。production-likeな大きいexposure factorでもraw確信度が低い1問目で終了しないことをAPI回帰テストで確認します。

絶対gateはTop1/Top3、calibration、平均28問以下、confidence停止後のleader変化0、hard-limit比率、情報利得、実効候補削減、無信号0、cold-start 1診断1問以下、反復0、全scenario、直接結果名0、`answer_frame`欠落0、結果集中、分散数式、60秒以内を確認します。baseline gateはTop1/Top3、calibration、情報利得、実効候補削減、未定義回答率の悪化を許容差内に制限します。

## baseline更新

baselineは機能変更と同じPRで無条件に更新しません。次を満たす時だけ、レビュー済みの主要値を手作業で更新します。

1. 変化した質問・matrix・停止条件・分散式を説明できる。
2. persona回答がmatrixから生成されていない。
3. 個別`rows`で退行したpersonaを確認した。
4. 意図的な退行ならゲーム設計上の理由を記録した。
5. `sh scripts/check.sh`とbrowser E2Eが通る。

現在の強い結果分散は意図的な仕様です。`DIVERSITY_ALPHA=3.0`をfactorへ負のべきとして適用するため、レポート上の実効指数は`-3.0`です。弱める変更を「偏り修正」としてbaseline更新してはいけません。
