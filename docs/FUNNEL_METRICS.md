# Funnel Metrics

This document records the operational source of the start/completion funnel so alerts do not treat mixed or incomplete counters as exact conversion data.

## Counters

- `start_count` / daily `start`
  - Incremented by `POST /api/start` when a new diagnosis starts.
  - Incremented by `POST /api/resume` only when the client submits saved answer pairs. This treats a restored draft as a resumed diagnosis start so restored sessions cannot produce completions without a matching start source.
  - Empty resume requests return the first question but do not increment start.

- `completion_count` / daily `completion`
  - Incremented in `make_guess()` when the API returns a result for the active session.
  - Guarded by the session key `completion_recorded` so continuing, re-rendering, or retrying inside the same server session does not double count.

- `play_count` / daily `play`
  - Legacy completion-like counter incremented with `completion_count`.
  - Kept for compatibility with existing admin labels.

- `result_page_view`
  - Share analytics event recorded by `/r?...` and `/r/<share_id>` result-share pages.
  - This is not a diagnosis completion and must not be mixed into `completion_count`.

## Non-counting routes

- `/r?...` and `/r/<share_id>` record share analytics only.
- `/ogp.png` and `/ogp` record OGP view events only.
- Reloading a rendered result page does not increment `completion_count` unless the client repeats the API flow and receives a new `make_guess()` response.

## Reliability Rules

`completion_rate` is unavailable when completions exceed starts. This can happen with historical mixed data, restored drafts from older deployments, or counter resets. In that case admin/API/reporting should show `—` or `unavailable` instead of a percentage over 100%.

Small samples and exact 100% rates are treated as reference values by ntfy reports because they may come from short windows where every tracked start reached a result.

## Investigation Notes

The observed production mismatch (`start_count=1257`, `completion_count=1278`) is consistent with restored draft sessions reaching `make_guess()` while `/api/resume` did not increment `start_count`. The route now counts answered resume requests as a start source, while existing historical mismatch is handled by marking the rate unavailable.
