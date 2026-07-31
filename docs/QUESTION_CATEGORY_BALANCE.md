# Question Category Balance

Hekineitor keeps inference math, priors, and learned data stable while using question metadata to reduce early over-concentration on relation-heavy results.

Question wording follows `docs/QUESTION_DESIGN.md`: each question should split several remaining candidates through an indirect latent axis instead of naming one result directly.

## Categories

Supported question categories:

- `relation`: relationship structure, distance, taboo, secrecy
- `attachment`: anxiety, dependence, obsession, need-to-be-needed signals
- `attribute`: visible or concrete traits such as clothes, glasses, lab coats
- `world`: setting, non-realistic atmosphere, closed places, supernatural context
- `tone`: emotional temperature, quietness, brightness, tension
- `value`: values, observation, rules, decision style
- `role`: roles, protection, power balance, responsibility
- `aesthetic`: cleanliness, order, inorganic feeling, visual mood

The `category` key is optional at runtime. If a question has no category, the engine falls back from its existing axis so older data remains compatible.

## Selection Policy

The existing early abstract-axis preference is preserved, but `best_question` now applies a small category diversity adjustment:

- recent same-category questions are slightly penalized
- relation/attachment repeat is reduced during the first five questions
- attribute/world/tone/value/aesthetic questions get a small early boost when not yet asked
- all penalties are soft; if alternatives are weak or unavailable, the original scoring can still win

This avoids changing posterior calculation, global priors, or learned matrix values.

## Added Questions

Abstract questions were added for non-attachment discovery. Q143-Q152 are cold-start probes whose wording separates these latent dimensions:

- trust based on behavioral consistency rather than readable emotion
- delayed, carefully chosen responses
- monochrome rather than vivid color
- intimacy conveyed without abandoning formal language
- intention perceived behind unexplained events
- voice and timing cues rather than facial cues
- ordered workspaces rather than lived-in rooms
- observing habits before approaching
- precise, almost non-human movement
- carefully composed rather than terse wording

Existing matrix columns are preserved. Q143-Q152 start from neutral matrix values and are monitored as cold-start questions while feedback supplies their candidate-splitting signal.
