# Multi-Correct Feedback Plan

Hekineitor differs from Akinator: multiple nearby results can be acceptable answers. A single "correct" feedback should therefore not always mean only the displayed result deserves strong positive learning.

## Current risk

- If one result is displayed often, it receives more correct feedback opportunities.
- Correct feedback happens more often than wrong feedback, so popular displayed results can self-reinforce.
- Nearby results may be valid but receive no learning signal because they were not displayed.

## Current safeguards already in place

- Correct feedback is scaled down relative to wrong feedback.
- Wrong feedback is strengthened to offset high correct-feedback volume.
- Result exposure balancing reduces repeated display of overexposed results.
- Displayed result, feedback target, share target, analytics target, and session result are contract-tested.

## Proposed next PR

Treat result feedback as a weighted neighborhood signal:

1. Keep the displayed result as the primary feedback target.
2. For `correct`, add small positive credit to top related candidates when their posterior is close to the displayed result.
3. For `wrong`, apply stronger negative signal to the displayed result, but do not punish all nearby candidates equally.
4. For `near miss`, ask the player to select the closer result and use that as the positive target.
5. Cap all neighborhood learning so it cannot overpower explicit selected feedback.

## Safety rules

- No DB schema change.
- No matrix reset or bulk correction.
- Preserve existing API responses.
- Add behavior-lock tests before changing learning deltas.
- Roll out with smaller coefficients first and monitor result_exposures.

## Suggested tests

- Correct feedback on a popular result does not increase only that result when a close related result is selected.
- Wrong feedback on an overexposed result reduces its future rank without collapsing unrelated candidates.
- Near-miss selected target receives stronger positive signal than the originally displayed result.
- Existing confirm/finalize_added behavior remains unchanged in normal mode.
- Learning-off test play still skips all learning writes.
