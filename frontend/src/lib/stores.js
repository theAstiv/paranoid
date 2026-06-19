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
 * @type {import('svelte/store').Writable<(() => void)|null>}
 */
export const abortRun = writable(null)

/**
 * @type {import('svelte/store').Writable<{type: 'success'|'error', message: string}|null>}
 * Auto-dismiss success notifications after 4s in the component that sets them.
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

/**
 * Show a notification and auto-dismiss success messages after 4 seconds.
 * @param {'success'|'error'} type
 * @param {string} message
 */
export function notify(type, message) {
  notification.set({ type, message })
  if (type === 'success') {
    setTimeout(() => notification.set(null), 4000)
  }
}
