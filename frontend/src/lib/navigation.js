// Screen names for the topbar breadcrumb and the browser tab title.

/** Breadcrumb labels by route prefix ('/' only matches the home route itself). */
export const SCREEN_LABELS = {
  '/dashboard': 'Dashboard',
  '/': 'Threat Models',
  '/models/new': 'New Model',
  '/library': 'Library',
  '/sources': 'Code Sources',
  '/members': 'Members',
  '/projects/settings': 'Project Settings',
  '/admin/users': 'Users',
  '/settings': 'Settings',
}

/** Pages the breadcrumb leaves unnamed, by exact route shape. */
const TITLE_PATTERNS = [
  [/^\/login$/, 'Sign in'],
  [/^\/register$/, 'Create account'],
  [/^\/models\/new$/, 'New Model'], // before the /models/:id pattern below
  [/^\/models\/[^/]+\/review$/, 'Review'],
  [/^\/models\/[^/]+\/diff$/, 'Re-run Diff'],
  [/^\/models\/[^/]+\/context$/, 'Review Context'],
  [/^\/models\/[^/]+$/, 'Results'],
  [/^\/threats\/[^/]+\/attack-tree$/, 'Attack Tree'],
  [/^\/threats\/[^/]+\/test-cases$/, 'Test Cases'],
]

/**
 * The breadcrumb label for a location, or '' when the breadcrumb shows none.
 * @param {string} location
 */
export function screenLabel(location) {
  for (const [prefix, label] of Object.entries(SCREEN_LABELS)) {
    if (prefix === '/' ? location === '/' : location.startsWith(prefix)) return label
  }
  return ''
}

/**
 * Whether a location matches one of the router's paths ('/models/:id' style;
 * the '*' catch-all is ignored).
 * @param {string} location
 * @param {string[]} paths
 */
export function isKnownRoute(location, paths) {
  return paths.some(path => {
    if (path === '*') return false
    const pattern = path.split('/').map(part => (part.startsWith(':') ? '[^/]+' : part)).join('/')
    return new RegExp(`^${pattern}$`).test(location)
  })
}

/**
 * The browser tab title for a location (BB-109), e.g. "Review · Paranoid".
 * `knownRoute` is false for a location no route matches (the 404 page).
 * @param {string} location
 * @param {boolean} [knownRoute]
 */
export function pageTitle(location, knownRoute = true) {
  if (!knownRoute) return 'Page not found · Paranoid'
  const exact = TITLE_PATTERNS.find(([pattern]) => pattern.test(location))
  const label = exact ? exact[1] : screenLabel(location)
  return label ? `${label} · Paranoid` : 'Paranoid'
}
