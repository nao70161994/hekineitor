# Result Analytics Lifecycle

This document defines how result names and IDs are handled in operational analytics.

## Stable identity

- `fetish_id` is the stable identity for a result whenever an event has it.
- `fetish_name` is display text and can change after promotion, rename, or data repair.
- Historical event rows are not rewritten during normal deploys.

## Current display name normalization

Read-only result exposure ranking endpoints normalize display names at read time:

- `/api/admin/result_exposures`
- `/api/admin/result_exposure_trend`

When an exposure event has `fetish_id`, these endpoints display the current name from `engine.fetishes` instead of trusting the historical event name. This avoids stale labels after player-added fetish promotion or rename.

## Historical counters

`stats_history` and legacy guessed counters may include old IDs or old names. They are useful as fallback but should not be the primary source for current result bias analysis.

Preferred source order:

1. `result_exposures` for displayed-result distribution.
2. `share_events` for share/result page behavior, filtered to current known result names.
3. `stats_history` only as a legacy fallback when exposure events are unavailable.

## When to repair data

Do not rewrite historical analytics for simple rename cases. Use read-time normalization.

Run a repair only when:

- a promoted player fetish was attached to the wrong `fetish_id`, or
- stats were moved to the wrong ID, or
- an admin operation created duplicate ID ownership.

Repair operations must be explicit, audited, and dry-run first.

## Current open risks

- Events without `fetish_id` can only be grouped by historical name.
- Legacy `stats_history` remains cumulative and can overstate old heavy-result bias.
- Data repairs should remain separate from presentation fixes.
