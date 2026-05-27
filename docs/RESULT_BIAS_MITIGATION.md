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

These results can be a plausible match for many players, so a plain correct click is not treated as equally specific evidence as a narrower result. Their positive feedback factor is `0.55`.

Near-miss feedback is now stronger than before so the selected "close" result can compete with the initially guessed result:

- regular near miss factor: `1.6`
- broad heavy-emotion near miss factor: `1.15`

The broad near-miss factor is still above normal positive learning, but lower than narrow-result near misses to avoid moving the same broad cluster too aggressively.

## Expected Effect

This should reduce early overcommitment to heavy-emotion results and give visual, worldbuilding, role, and value axes more chances to separate candidates before the result is finalized.

## Still Not Changed

- Inference/posterior math
- Question matrix values
- Prior weights
- Existing stats or learning data
- DB schema
