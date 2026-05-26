# Question Category Balance

Hekineitor keeps inference math, priors, and learned data stable while using question metadata to reduce early over-concentration on relation-heavy results.

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

Eight abstract questions were added for non-attachment discovery:

- world: non-realistic atmosphere
- attribute: neat clothes/uniforms
- tone: quiet relationship temperature
- aesthetic: inorganic atmosphere
- world: closed or special places
- role: rules and roles
- aesthetic: cleanliness and order
- value: observing / being observed

Existing matrix columns are preserved. New columns are seeded with neutral values plus light domain priors for relevant attribute/world/tone/value candidates.
