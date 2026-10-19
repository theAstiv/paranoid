import { writable, derived, get } from 'svelte/store'

// ---------------------------------------------------------------------------
// Auth state
// ---------------------------------------------------------------------------

/**
 * The authenticated user object (from GET /api/auth/me), or null when logged out.
 * Persisted in memory only — restored on page load by calling /api/auth/me with
 * the stored access token.
 * @type {import('svelte/store').Writable<object|null>}
 */
export const currentUser = writable(null)

/**
 * True while the initial auth check (on page load) is in flight.
 * Components can use this to show a loading spinner instead of a login redirect.
 * @type {import('svelte/store').Writable<boolean>}
 */
export const authLoading = writable(true)

// ---------------------------------------------------------------------------
// Token helpers — localStorage-backed, used by api.js
// ---------------------------------------------------------------------------

const _TOKEN_KEY = 'paranoid_access_token'

/** @returns {string|null} */
export function getStoredToken() {
  try { return localStorage.getItem(_TOKEN_KEY) } catch { return null }
}

/** @param {string} token */
export function setStoredToken(token) {
  try { localStorage.setItem(_TOKEN_KEY, token) } catch { /* ignore */ }
}

export function clearStoredToken() {
  try { localStorage.removeItem(_TOKEN_KEY) } catch { /* ignore */ }
}

// ---------------------------------------------------------------------------
// Pipeline / model stores
// ---------------------------------------------------------------------------

/** @type {import('svelte/store').Writable<object[]>} list of threat model records */
export const models = writable([])

/** @type {import('svelte/store').Writable<object|null>} current model with threats[] embedded */
export const currentModel = writable(null)

/** @type {import('svelte/store').Writable<object[]>} threats for current model */
export const threats = writable([])

/** @type {import('svelte/store').Writable<object[]>} SSE PipelineEvent objects received so far */
export const pipelineEvents = writable([])

/** @type {import('svelte/store').Writable<boolean>} */
export const pipelineRunning = writable(false)

/** @type {import('svelte/store').Writable<object|null>} from GET /api/config */
export const config = writable(null)

/**
 * Abort function for the active SSE pipeline stream, or null when idle.
 * Set by NewModel before navigating; consumed by Results in onDestroy.
 * Aborting only stops following the run: the run is a server-side background
 * task and carries on (BB-71).
 * @type {import('svelte/store').Writable<(() => void)|null>}
 */
export const abortRun = writable(null)

/**
 * @type {import('svelte/store').Writable<{type: 'success'|'error', message: string}|null>}
 * Set through notify(), which dismisses it on a timer.
 */
export const notification = writable(null)

/** Pending threat count for the current model */
export const pendingCount = derived(
  threats,
  $t => $t.filter(t => t.status === 'pending').length
)

/** Most recent SSE event */
export const lastEvent = derived(
  pipelineEvents,
  $e => $e.at(-1) ?? null
)

export const SUCCESS_TOAST_MS = 4000
// Longer than a success so an error can be read; it can still be dismissed early.
export const ERROR_TOAST_MS = 8000

/**
 * Show a notification and dismiss it after SUCCESS_TOAST_MS or ERROR_TOAST_MS.
 * @param {'success'|'error'} type
 * @param {string} message
 */
export function notify(type, message) {
  const toast = { type, message }
  notification.set(toast)
  // Clear only this toast: a newer one set meanwhile keeps its own full time.
  setTimeout(() => {
    if (get(notification) === toast) notification.set(null)
  }, type === 'success' ? SUCCESS_TOAST_MS : ERROR_TOAST_MS)
}

// ---------------------------------------------------------------------------
// Multi-user / project stores (Phase 2)
// ---------------------------------------------------------------------------

/**
 * The currently-active project context, or null before Phase 2 backend ships.
 * Shape: { id, name, org, role } | null
 * @type {import('svelte/store').Writable<object|null>}
 */
export const currentProject = writable(null)

const _PROJECT_KEY = 'paranoid_active_project'

// Remember the selection across reloads; without this, every page load fell
// back to the newest project the user belongs to.
currentProject.subscribe(p => {
  if (!p?.id) return
  try { localStorage.setItem(_PROJECT_KEY, p.id) } catch { /* ignore */ }
})

/**
 * The project to activate on page load: the remembered one if the user is
 * still a member of it, otherwise the first in the list.
 * @param {object[]} list
 * @returns {object|null}
 */
export function pickInitialProject(list) {
  if (!list.length) return null
  let storedId = null
  try { storedId = localStorage.getItem(_PROJECT_KEY) } catch { /* ignore */ }
  return list.find(p => p.id === storedId) ?? list[0]
}

/**
 * The project to show once `list` (re)loads for a possibly different user:
 * the current selection if it's in the list, as the list's own object so
 * `member_role` is the new user's, otherwise the initial pick.
 * @param {object|null} current
 * @param {object[]} list
 * @returns {object|null}
 */
export function reconcileProject(current, list) {
  return list.find(p => p.id === current?.id) ?? pickInitialProject(list)
}

/**
 * All projects the current user is a member of.
 * @type {import('svelte/store').Writable<object[]>}
 */
export const projects = writable([])

/**
 * Unread notification items from GET /api/notifications.
 * @type {import('svelte/store').Writable<object[]>}
 */
export const notifications = writable([])

/**
 * Count of unread notifications for the bell badge.
 * @type {import('svelte/store').Readable<number>}
 */
export const notifUnread = derived(
  notifications,
  $n => $n.filter(n => !n.is_read).length
)

/**
 * Which overlay menu is open: 'project' | 'user' | 'notif' | null
 * @type {import('svelte/store').Writable<string|null>}
 */
export const menuOpen = writable(null)

/**
 * Reset all per-session, per-user state. Call on logout and on auth-expiry
 * (401 after a failed refresh) — otherwise the previous user's projects/
 * notifications survive in these stores until something happens to
 * overwrite them, which only happens on the initial page-load fetch, not on
 * a logout→login cycle within the same SPA session.
 */
export function clearAuthState() {
  currentUser.set(null)
  notifications.set([])
  projects.set([])
  currentProject.set(null)
  menuOpen.set(null)
  // A toast from the old session must not greet the next user. Callers that
  // report the expiry itself notify after this returns.
  notification.set(null)
}
