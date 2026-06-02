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

Result display now applies an exposure correction before the final result is returned. This does not change posterior math, priors, matrix values, or question selection. It re-ranks the final candidate pool and uses the same exposure signal to dampen positive feedback and strengthen negative feedback for overexposed results.

In production with `DATABASE_URL`, the service records primary result exposures to the `analytics_events` table so deploys do not reset the exposure window. When `RESULT_EXPOSURE_LOG_PATH` is set, or when DB storage is unavailable locally, it falls back to JSONL (`data/result_exposures.jsonl`). It stores only result id/name, probability, rank, and timestamp. It does not store IP, User-Agent, session id, or user identifiers.

Current windows and correction range:

- main window: latest `1000` primary result exposures
- short over-concentration guard: latest `300` primary result exposures
- minimum samples before correction: `50`
- candidate pool: posterior top `20`, plus up to `30` low-exposure rescue candidates selected from the rest of the ranked list

The main correction compares recent exposure count to the expected count and clamps the factor to `0.25` - `3.0` for normal results. Broad heavy-emotion results use a stronger floor of `0.2`. The short-window guard applies extra downweighting for over-concentrated results:

- `15%` or higher in the latest 300: `x0.75`
- `25%` or higher: `x0.60`
- `40%` or higher: `x0.45`

Broad heavy-emotion results (`共依存`, `激重感情`, `共生関係`, `執着`) have a factor cap of `0.55` and can be pushed down to `0.2` when recent exposure is still concentrated. A category quota applies on the latest 300 results: if heavy-emotion results exceed `10%`, their factor is capped at `0.25`; if they exceed `25%`, their factor is capped at `0.12`. While that hard quota is active, heavy-emotion results are capped at an effective factor of `0.02` whenever there is any non-heavy candidate in the adjustment pool. Dominant top-result protection is disabled, so overexposed heavy-emotion results can lose close races even when they start as the top posterior candidate.

The read-only endpoint `/api/admin/result_exposure_factors` exposes aggregate correction diagnostics: sample size, config, most downweighted results, most boosted results, and heavy-result factors. It does not return raw events, IP, User-Agent, session id, or tokens.

## Expected Effect

This should reduce early overcommitment to heavy-emotion results and give visual, worldbuilding, role, and value axes more chances to separate candidates before the result is finalized.

## Still Not Changed

- Inference/posterior math
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

## Low-exposure rescue pool

Diversity balancing keeps the primary candidate pool at the top 20 results, but it also selects up to 30 low-exposure rescue candidates from the rest of the ranked list. A candidate is eligible for this rescue pool only when its exposure factor is above 1.0, meaning it has appeared less often than expected in the recent exposure window.

This rescue pool is no longer limited to low-confidence results. Under-shown results always get a chance to compete by adjusted score, while the final answer still comes from posterior score multiplied by exposure factor rather than from random injection.

## Feedback balancing

Positive feedback for overexposed results is now dampened by the exposure factor with a floor of `x0.2`. Negative feedback for overexposed results is strengthened by the inverse exposure factor with a cap of `x2.5`. When exposure data is missing or below the minimum sample threshold, feedback factors fall back to the previous broad/concrete values.

## Stronger diversity tuning

The current tuning makes any overexposed result lose more close races while allowing underexposed candidates to gain more learning opportunities. The rescue pool is capped at 30 candidates to avoid turning the result into a random rotation.
