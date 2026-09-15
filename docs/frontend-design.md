# Frontend Design System

Reference for contributors working on the Svelte frontend. Read this before touching any `.svelte` file.

## Layout chrome

- **Sidebar**: 264px fixed width — project selector, navigation links, user menu
- **Topbar**: 54px fixed height — page title, notifications bell, user avatar
- Login (`#/login`) and Register (`#/register`) render **without chrome** — all other authenticated routes get chrome automatically via `App.svelte`

## Colors — `c-*` tokens

All colors are defined as `c-*` tokens in `tailwind.config.js`. **No raw hex values in `.svelte` files.** If a color you need doesn't have a token, add it to the config first.

```js
// tailwind.config.js — add tokens here, not inline in components
colors: {
  'c-critical': '#...',
  'c-high':     '#...',
  'c-medium':   '#...',
  'c-low':      '#...',
  // ...
}
```

### DREAD severity mapping

| DREAD score | Token | Meaning |
|-------------|-------|---------|
| ≥ 8 | `c-critical` | Critical severity |
| ≥ 6 | `c-high` | High severity |
| ≥ 4 | `c-medium` | Medium severity |
| < 4 | `c-low` | Low severity |

Use the shared `dreadColor(score)` helper from `frontend/src/lib/utils.js` — it returns the Tailwind text class (`text-c-critical`, `text-c-high`, etc.). Import it everywhere DREAD scores are displayed; do not re-implement the mapping inline.

## Typography

- **UI text**: IBM Plex Sans (set in `app.css`)
- **Data** (IDs, counts, timestamps, code): IBM Plex Mono

## Buttons

Use only these two classes from `app.css`:

```html
<button class="btn-primary">Save</button>
<button class="btn-ghost">Cancel</button>
```

Do not write custom button styling inline.

## Chips / badges

Use `chip-*` classes from `app.css`:

| Class | Use |
|-------|-----|
| `chip-accent` | Primary highlight |
| `chip-blue` | STRIDE / informational |
| `chip-violet` | MAESTRO |
| `chip-amber` | Warning / medium severity |
| `chip-green` | Approved / success |
| `chip-red` | Critical / rejected |
| `chip-orange` | High severity |
| `chip-gray` | Neutral / disabled |

Never write the chip background/border/color logic inline — always use these classes.

## No inline styles

`style=` attributes are banned except for **dynamic computed values only**, e.g.:

```svelte
<!-- Allowed: dynamic computed value -->
<div style="width: {pct}%"></div>

<!-- Not allowed: static styling -->
<div style="color: red; font-weight: bold"></div>
```

Everything else is Tailwind utilities or `app.css` component classes.

## Icons

Use inline SVGs with `stroke-width` of approximately 1.8 and no fill. Follow the same approach as existing icons in the codebase. Do not add icon libraries or external SVG sprites.

## Content max-widths

Set as `max-w-[Xpx] mx-auto` on the page content wrapper:

| Page type | Max width |
|-----------|-----------|
| Dashboard / model list / results | `1120px` |
| Review | `920px` |
| New model wizard / run | `880px` |
| Settings | `760px` |

## Overlays and menus

Use the `menuOpen` store from `stores.js` — set to the menu name string to open, `null` to close:

```js
import { menuOpen } from '$lib/stores.js'
menuOpen.set('user')    // open
menuOpen.set(null)      // close
```

The backdrop `<div>` in `App.svelte` catches outside clicks and sets `menuOpen = null`. Only `App.svelte` renders the backdrop — overlays are positioned components, not portals.

## Animations

Use Tailwind animation utilities (`animate-spin-slow`, `animate-pulse-dot`, `animate-blink`, `animate-pop-in`). Do not add new `@keyframes` to `app.css` unless the animation can't reasonably live in `tailwind.config.js`.

## Routing

Routes use `svelte-spa-router` (hash-based: `#/path`). Add new routes in `App.svelte`. All authenticated routes automatically receive the sidebar + topbar chrome — no extra work needed.

## API stubs for missing endpoints

If a page needs an API endpoint that doesn't exist yet, add a stub to `frontend/src/lib/api.js` that returns an empty array or object. Do not leave the call as `undefined` — this breaks components that iterate over the result.

```js
// api.js — stub pattern
export async function getNotifications() {
  // TODO: implement when backend route is ready
  return []
}
```

## RBAC visibility

Gate mutation buttons on the user's role — do not show Edit/Delete/Approve buttons to Viewers. The current user's role in the active project is available from the project store. See `web-ui-guide.md` for the full RBAC visibility table.

## Component naming

- Files: `PascalCase.svelte` (`ThreatCard.svelte`, `DreadBadge.svelte`)
- Props: document with `@type` JSDoc comments
- `ModelCard.svelte` ≠ `ThreatCard.svelte` — do not merge them:
  - **ModelCard**: model-summary card on Home (severity bar, status dot, assignee avatars)
  - **ThreatCard**: per-threat card on Review (DREAD score, 5-bar chart, approve/reject)
