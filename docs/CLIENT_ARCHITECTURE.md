# Browser Client Modules

The main page loads classic scripts with `defer`. The browser runs them in document order, and several modules publish APIs on `window` for later modules. Preserve the order in `templates/index.html` when changing those tags.

## Load order

| Module | Provides | Used by |
| --- | --- | --- |
| `game_state.js` | `HekiState` | network, game flow, draft, history, renderers |
| `api_client.js` | `HekiApiClient` | network |
| `utils.js` | shared DOM, parsing, and URL helpers | renderers and app bootstrap |
| `renderers.js` | screen transitions and result rendering | game flow, UI, event delegation |
| `app.js` | no browser API; compatibility entrypoint placeholder | no direct dependency |
| `network.js` | request lifecycle and answer controls | game flow, teaching, feedback |
| `ui.js` | screen state, genie state, modals, toast | game flow, teaching, events |
| `game_flow.js` | diagnosis state transitions | draft, history, events |
| `draft.js` | local resume and answer drafts | UI and game flow |
| `teach.js` | answer correction and new-result flow | event delegation |
| `history.js` | local diagnosis history | UI and game flow |
| `feedback.js` | result and detailed feedback | event delegation |
| `share.js` | share payloads, native share, event tracking | game flow, renderers, events |
| `pwa.js` | install and completion state | game flow, history, events |
| `performance.js` | performance instrumentation | app bootstrap |
| `events.js` | delegated actions and keyboard handling | the modules above |

`catalog.js` is loaded only by the catalog page. `admin.js` and `admin_ops.js` belong to the administration page. Keep compatibility aliases at the module boundary while templates and older flows still call them; new cross-module behavior should use the owning `Heki*` API.

## Stylesheet boundaries

| Stylesheet | Responsibility | Loaded by |
| --- | --- | --- |
| `app.css` | Shared/base styles and legacy component rules | Main and privacy pages |
| `public_experience.css` | Screen state, focused gameplay, and responsive public UI rules | Main and privacy pages, after `app.css` |
| `admin.css` | Admin layout, controls, and reusable admin presentation classes | Admin page |

Keep the public stylesheet order when moving rules: `public_experience.css` contains later overrides that intentionally follow the base rules. Add new public styles to the narrowest fitting file and keep admin presentation in `admin.css` instead of template `style` attributes.

## Change guidance

- A module may call only an API provided earlier in the main-page load order, unless it uses an explicit optional check (`?.`).
- Update this table and `tests/test_smoke.py::test_client_module_scripts_are_loaded_in_dependency_order` when adding or moving a module.
- Prefer moving one related feature at a time to ES modules only when its callers and page entry points can migrate together.
