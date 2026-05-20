# Review Checklist

## Backend

- Routes keep the same URLs, HTTP methods, and status codes.
- Session keys remain compatible with existing diagnosis and resume flows.
- Admin endpoints still require admin authentication and CSRF checks where applicable.
- SEO routes keep `og:image`, canonical URLs, robots, sitemap, and noindex behavior intact.
- Engine facade methods remain available for tests and existing imports.

## Frontend

- `data-action` bindings still cover all buttons and controls.
- No inline event handlers are reintroduced.
- Result screen still renders normal, compound, work, feedback, and share sections.
- Draft resume, history retry, quick retry, and add-fetish flows still call the same APIs.
- Mobile tap targets remain large enough after CSS changes.

## Operations

- Admin maintenance queue surfaces missing URL, search URL, and missing ASIN cases.
- ASIN backfill dry-run does not mutate data.
- Matrix import/export and restore paths retain backup safeguards.
- Runtime health route still reports matrix, persistence, and error state.

## Verification

- `git diff --check`
- `node --check static/app.js`
- `pytest`
- Browser smoke test for start, answer, result, feedback, share, resume, and admin page.
