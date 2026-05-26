# Promoted Stats History Repair

Player-added fetishes can be promoted into the seeded fetish range. New promotions move recent diagnosis ranking counters automatically, but promotions performed before that fix may still have `stats_history` rows under the old player-fetish ID.

Use `/api/admin/repair_promoted_stats_history` only with an explicit `old_id -> new_id` mapping. The tool does not infer mappings because an incorrect merge would corrupt ranking history.

## Admin UI

The admin page includes `昇格済み性癖のランキング履歴修復`. Enter the old player-fetish ID and the promoted seed ID, run dry-run first, then apply with the confirmation text. This uses the same API described below.

## Seed ID Correction

If a promoted stats repair was applied to the wrong seed IDs, use the admin page's advanced `ID移動` section. Enter one mapping per line, run dry-run, then apply with `MOVE_STATS_HISTORY`.

For a one-position shift from 129-132 down to 128-131:

```text
129,128
130,129
131,130
132,131
```

This moves only ranking history keys (`f_guessed_*`, `f_correct_*`, `f_wrong_*`). It does not change fetishes, matrix rows, inference behavior, or player-added fetish records. Overlapping mappings are internally staged through temporary keys so chain moves do not overwrite each other.

## Dry Run

```sh
curl -u "$ADMIN_USER:$ADMIN_PASS" \
  -X POST https://hekineitor.onrender.com/api/admin/repair_promoted_stats_history \
  -H "Content-Type: application/json" \
  -d '{"dry_run":true,"mappings":[{"old_id":10000,"new_id":128}]}'
```

Dry run returns the affected `f_guessed_*`, `f_correct_*`, and `f_wrong_*` rows and value totals without changing data.

## Apply

```sh
curl -u "$ADMIN_USER:$ADMIN_PASS" \
  -X POST https://hekineitor.onrender.com/api/admin/repair_promoted_stats_history \
  -H "Content-Type: application/json" \
  -d '{"confirm_text":"REPAIR_PROMOTED_STATS","mappings":[{"old_id":10000,"new_id":128}]}'
```

Apply merges rows into the new ID by date/key and deletes the old keys. The admin audit log records the mapping count and total moved value, but does not store IP, User-Agent, or personal identifiers.

## Safety Rules

- `old_id` must be in the player-fetish range.
- `new_id` must be in the seeded fetish range.
- Apply requires the exact confirmation text `REPAIR_PROMOTED_STATS`.
- If the mapping is unknown, do not run the repair. Record the orphaned ranking as a manual investigation item instead.
