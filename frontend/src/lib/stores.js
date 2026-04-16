import { writable, derived } from 'svelte/store'

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
