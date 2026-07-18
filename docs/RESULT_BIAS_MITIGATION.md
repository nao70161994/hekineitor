# Result Bias Mitigation

This note records safe mitigation for the heavy-emotion result concentration seen in production alerts.

## Scope

The mitigation intentionally avoids posterior calculation changes, prior changes, matrix rewrites, and learned-data deletion. It only changes question timing metadata and question-selection weighting.

## Heavy-Emotion Early Suppression

The following broad relation/attachment/tone questions are marked with `early_penalty` so they are less likely to appear in the first five questions:

- Q55: one-sided feeling / unrequited axis
- Q87: forbidden-feeling axis
- Q91: painful but inseparable axis
- Q105: notification checking axis
- Q120: pretending to be fine axis
- Q126: being needed axis
- Q132: shadow/darkness axis

Q2 and Q60 were already early-penalized.

## Cluster Diversification

When top candidates cluster around heavy relation results (`共依存`, `激重感情`, `共生関係`, `執着`), question selection now gives a stronger temporary boost to diversifying categories:

- `attribute`
- `world`
- `aesthetic`
- `value`

It also suppresses early `relation` / `attachment` / `tone` repeats while alternatives exist.


## Low-Exposure Result Probe

Before finalizing a result, if the top candidates cluster around heavy-emotion results, the game may ask up to two additional questions from low-exposure-friendly axes (`attribute`, `world`, `aesthetic`, `value`, `role`). This is a timing guard only: it does not change posterior math, priors, or matrix values.

This helps under-presented visual/world/role results get one more chance to separate before a heavy-emotion result is returned.


## Feedback Weighting

Correct feedback on broad heavy-emotion results is now learned more softly:

- `共依存`
- `激重感情`
- `共生関係`
- `執着`

These results can be a plausible match for many players, so a plain correct click is not treated as equally specific evidence as a narrower result. Feedback volume is also imbalanced in production: correct feedback has been roughly three times as common as wrong feedback. To keep total learning pressure closer to balanced, positive feedback is softened and negative feedback is strengthened:

- regular positive factor: `0.7`
- broad heavy-emotion positive factor: `0.45`
- regular negative factor: `1.3`
- broad heavy-emotion negative factor: `1.7`

Near-miss feedback is stronger than regular positive feedback so the selected "close" result can compete with the initially guessed result:

- regular near miss factor: `1.6`
- broad heavy-emotion near miss factor: `1.15`

The broad near-miss factor is still above regular positive learning, but lower than narrow-result near misses to avoid moving the same broad cluster too aggressively.


## Recent Exposure Balancing

最終結果には、直近の表示実績を使った強い分散補正を意図的に適用します。これは同じ高posterior結果ばかり返す状態を避け、発見性とリプレイ性を確保するためのプロダクト仕様です。純粋なposterior順位の再現性よりも、十分に適合する候補の中で結果の多様性を優先します。

補正は、直近 `1000` 件のprimary result exposureについて、各結果の実表示比率と均等期待比率を比較します。

```text
exposure_factor = ((actual_count + 2) / (expected_count + 2)) ** -3
adjusted_score = clamp(raw_posterior * exposure_factor, 0, 1)
```

- 指数 `-3` は、弱い微調整ではなく強い分散を作るための意図的な値です。
- 最低サンプル数による無効化やfactorの上下限clampは設けません。少数時から分散を働かせる設計です。
- 上位だけの救済poolではなく、全候補をadjusted scoreで比較します。
- adjusted scoreは最終順位、表示確率、複合結果・プロフィール・上位チャート、早期終了判定に一貫して使います。
- raw posteriorは `raw_probability` として保持され、質問選択・matrix・priorの計算自体は変更しません。

したがって、表示結果がraw posteriorの1位と一致しないことは不具合ではありません。強度を弱める、最低サンプル数を加える、候補poolを狭める変更は、結果多様性というプロダクト方針を変更するときだけ行います。

本番で `DATABASE_URL` が有効な場合、primary result exposureは `analytics_events` に保存されます。`RESULT_EXPOSURE_LOG_PATH` が指定された場合、またはDBが使えないローカル環境では `data/result_exposures.jsonl` にfallbackします。保存対象は結果ID・結果名・確率・順位・timestampのみで、IP、User-Agent、session ID、ユーザー識別子は保存しません。

読み取り専用endpoint `/api/admin/result_exposure_factors` は、サンプル数、設定、downweight/boostされた結果などの集約診断を返します。raw eventや認証情報は返しません。

## Feedback balancing with exposure

表示分散と学習が逆方向に暴走しないよう、feedback learningにも同じexposure factorを使います。

- overexposed結果へのpositive feedbackはfactorで弱める。ただし `x0.2` を下限とする。
- overexposed結果へのnegative feedbackはfactorの逆数で強める。ただし `x2.5` を上限とする。
- near-missおよびheavy-emotion結果の基礎係数は前節のfeedback weightingを維持する。

表示補正は強くても、positive learningをゼロにはせず、negative learningも無制限には増やしません。

## Expected Effect

序盤ではカテゴリ分散と追加probeで候補を分離し、最終表示では強いexposure correctionによって同じ結果の連続を抑えます。視覚、世界観、役割、価値観などの結果にも実表示とfeedback learningの機会が回ることを狙います。

## Still Not Changed

- raw inference / posteriorの計算
- 質問選択で使うposteriorとmatrix
- Question matrix values
- Prior weights
- Existing stats or learning data
- DB schema

## Result analytics source

Operations notifications and daily reports should prefer `result_exposures` for result distribution. This event is recorded after the final displayed result is selected, so it reflects what users actually saw. `recent_fetish_ranking` remains available as a stats-history fallback, but it can include legacy guessed counters and should not be used alone to judge displayed-result bias when exposure data exists.

The read-only endpoint `/api/admin/result_exposures` returns only aggregate counts (`fetish_id`, `fetish_name`, count/percent/source). It does not expose IP, User-Agent, session id, or tokens.

## Backfilling exposure history

When production has too few `result_exposure` rows for diversity balancing, an administrator can backfill synthetic exposure events from the historical `fetish_log.guessed` counters. This is intentionally opt-in because old guessed counters are not as precise as real displayed-result events.

Preview:

```sh
curl -u admin:$ADMIN_PASS \
  "https://hekineitor.onrender.com/api/admin/result_exposures/backfill?max_events=1000"
```

Apply:

```sh
curl -u admin:$ADMIN_PASS \
  -H "Content-Type: application/json" \
  -H "X-CSRF-Token: $ADMIN_CSRF_TOKEN" \
  -d '{"confirm_text":"BACKFILL_RESULT_EXPOSURES","max_events":1000}' \
  https://hekineitor.onrender.com/api/admin/result_exposures/backfill
```

Backfilled rows are tagged with `source=stats_history_backfill`. They are used by the diversity balancing window, but the public/read-only result exposure ranking excludes them by default so daily reports continue to represent real displayed results only. Use `include_backfill=1` only when auditing the backfill itself.
