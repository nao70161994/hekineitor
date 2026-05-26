# Result Bias Mitigation

Production analytics on 2026-05-26 showed that diagnosis results were over-concentrated in heavy relation results:

- 共依存: 845 guesses / 41.4%
- 激重感情: 553 guesses / 27.1%
- 共生関係: 160 guesses / 7.8%
- 執着: 129 guesses / 6.3%
- Top 4 total: 82.6%

This mitigation intentionally avoids posterior calculation changes, matrix backfill/correction, prior changes, DB schema changes, and deletion of learned data.

## Safe changes applied

- Q2 wording moved from direct obsession wording to a memory/attention tendency.
- Q60 wording moved from direct codependency wording to a distance/comfort dilemma.
- Q2 and Q60 now carry `early_penalty: true`, so they are less likely to appear in the first five questions.
- When an early top candidate is one of `共依存`, `激重感情`, `共生関係`, or `執着`, question selection lightly favors `attribute`, `world`, `aesthetic`, and `value` categories and soft-penalizes `relation` / `attachment` questions.
- High-YES questions Q70, Q77, and Q141 were rewritten to be more comparative and less universally agreeable.
- Ten abstract support questions were added for attribute/world/aesthetic/value/tone coverage around 眼鏡, 白衣, 敬語, and 人外/異形頭.

## Q120 decision

Q120 (`人前では平気なふりをしがち？`) was already categorized as `tone`. Production contribution data showed it boosting `共生関係` and `激重感情`, but that linkage is learned/matrix-driven rather than a category bug. We did not change matrix or priors. The safer mitigation is to diversify early questions when heavy relation candidates lead.

## Follow-up checks

After deployment, collect at least a few hundred new `question_events` and compare:

- Top 4 heavy relation result share
- Q2/Q60 first-five appearance rate
- category distribution in the first five questions
- accuracy of `共生関係`, `人外/異形頭`, `敬語`, and `白衣`
