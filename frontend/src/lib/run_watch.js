// Notices a run or extraction started elsewhere: another tab, another user, the
// CLI (BB-129). Pages that edit a model used to load once and never look again,
// so Approve hit threats a re-run had already replaced.

import { getActiveRun } from './api.js'

export const WATCH_INTERVAL_MS = 5000

/**
 * Check the model's active run now (unless `immediate` is false), every
 * `intervalMs` while the tab is visible, and when the tab becomes visible.
 * `onActive(run)` is called each time a check finds one, unless `skip()` says
 * the page is already following a run. Errors are ignored: the next check retries.
 *
 * @param {string} modelId
 * @param {(run: { kind: 'run' | 'extract', started_at: string }) => void} onActive
 * @param {{ skip?: () => boolean, immediate?: boolean, intervalMs?: number }} [options]
 * @returns {{ stop: () => void, check: () => Promise<void> }}
 */
export function watchActiveRun(modelId, onActive, options = {}) {
  const { skip = () => false, immediate = true, intervalMs = WATCH_INTERVAL_MS } = options
  let stopped = false
  let inFlight = false

  async function check() {
    if (stopped || inFlight || skip()) return
    if (typeof document !== 'undefined' && document.visibilityState === 'hidden') return
    inFlight = true
    try {
      const { active_run: run } = await getActiveRun(modelId)
      if (!stopped && run && !skip()) onActive(run)
    } catch {
      // Transient (network, a 404 while the model is being deleted): retry next tick.
    } finally {
      inFlight = false
    }
  }

  const onVisible = () => { if (document.visibilityState === 'visible') check() }
  const timer = setInterval(check, intervalMs)
  if (typeof document !== 'undefined') document.addEventListener('visibilitychange', onVisible)
  if (immediate) check()

  return {
    check,
    stop() {
      stopped = true
      clearInterval(timer)
      if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', onVisible)
    },
  }
}

/** Banner text for an active run of `kind`. */
export function activeRunMessage(kind) {
  return kind === 'extract'
    ? 'A context extraction is in progress; changes are paused.'
    : 'A re-run is in progress; changes are paused.'
}
