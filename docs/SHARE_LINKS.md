# Share Links

Result sharing supports both legacy query URLs and short share-id URLs.

## Public URLs

- Legacy, kept for compatibility: `/r?f=<result>&p=<percent>&d=<desc>`
- Short URL, preferred for SNS: `/r/<share_id>`

`share_id` is an 8-character base62 token generated server-side. Existing IDs between 4 and 12 characters remain valid. The token maps to a small payload containing only result data:

- `name`
- `probability` / `percent`
- `desc`
- `title`
- `rank`
- `created_at`

No IP address, user agent, session ID, or user identifier is stored.

## Storage

When PostgreSQL is configured, share links are stored in the `share_links` table. Otherwise they are stored in `data/share_links.json`. Set `SHARE_LINKS_PATH` to force a specific JSON location in tests or deployments.

`SHARE_LINKS_MAX_ENTRIES` controls the retention limit and defaults to 10,000. After creating a link, entries older than the newest configured limit are removed. PostgreSQL relies on its primary-key constraint for collision detection and retries with a new token without loading every existing ID.

## Creation Flow

- Result share pages loaded through legacy `/r?...` create a short link and use it for `og:url` and the X share button.
- The game client calls `POST /api/share_link` before Web Share / X share and falls back to the legacy URL if short-link creation fails.
- `/r/<share_id>` renders the same result share template and OGP image as `/r?...`.

## Compatibility

Existing `/r?...`, `/ogp.png?...`, and `/ogp?...` routes remain available. Share analytics continue to record `result_page_view`, OGP views, X clicks, Web Share outcomes, and copy outcomes using the result name.
