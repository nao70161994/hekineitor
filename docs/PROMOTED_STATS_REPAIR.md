# Promoted Stats History Repair

Player-added fetishes can be promoted into the seeded fetish range. New promotions move recent diagnosis ranking counters automatically, but promotions performed before that fix may still have `stats_history` rows under the old player-fetish ID.

Use `/api/admin/repair_promoted_stats_history` only with an explicit `old_id -> new_id` mapping. The tool does not infer mappings because an incorrect merge would corrupt ranking history.

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
