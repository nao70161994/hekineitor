# Share Links

Result sharing supports both legacy query URLs and short share-id URLs.

## Public URLs

- Legacy, kept for compatibility: `/r?f=<result>&p=<percent>&d=<desc>`
- Short URL, preferred for SNS: `/r/<share_id>`

`share_id` is a 4-6 character base62 token generated server-side. The token maps to a small JSON payload containing only result data:

- `name`
- `probability` / `percent`
- `desc`
- `title`
- `rank`
- `created_at`

No IP address, user agent, session ID, or user identifier is stored.

## Storage

Share links are stored in `data/share_links.json` by default. Set `SHARE_LINKS_PATH` to override this location in tests or deployments. This avoids a DB schema change while keeping URLs stable across requests.

## Creation Flow

- Result share pages loaded through legacy `/r?...` create a short link and use it for `og:url` and the X share button.
- The game client calls `POST /api/share_link` before Web Share / X share and falls back to the legacy URL if short-link creation fails.
- `/r/<share_id>` renders the same result share template and OGP image as `/r?...`.

## Compatibility

Existing `/r?...`, `/ogp.png?...`, and `/ogp?...` routes remain available. Share analytics continue to record `result_page_view`, OGP views, X clicks, Web Share outcomes, and copy outcomes using the result name.
