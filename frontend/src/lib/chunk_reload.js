// After a deploy the content-hashed chunk filenames change. If a user has an
// old tab open, the browser may try to dynamically import a chunk that no longer
// exists and surface "Failed to fetch dynamically imported module". Reloading
// picks up the new index.html and new hashes — the user sees a brief flash
// instead of a hard error.
//
// But a chunk that is missing after the reload too (a broken deploy, a blocked
// file) reloaded the page forever (BB-57). So reload at most once per
// RELOAD_WINDOW_MS: a second failure inside the window is left to surface as an
// error (e.g. DiagramView's error panel).

const STORAGE_KEY = 'paranoid:chunk-reload-at'
export const RELOAD_WINDOW_MS = 10_000

/**
 * @param {{ storage?: Storage, reload?: () => void, now?: () => number }} [deps]
 * @returns {() => boolean} handler; returns true when it reloaded
 */
export function createChunkErrorHandler({
  storage = window.sessionStorage,
  reload = () => window.location.reload(),
  now = () => Date.now(),
} = {}) {
  return function onPreloadError() {
    let last
    try {
      last = Number(storage.getItem(STORAGE_KEY) || 0)
    } catch {
      // No sessionStorage (private mode, blocked site data): without it a
      // reload can't be bounded across page loads, so don't reload at all.
      return false
    }
    const t = now()
    if (last && t - last < RELOAD_WINDOW_MS) return false
    try {
      storage.setItem(STORAGE_KEY, String(t))
    } catch {
      return false
    }
    reload()
    return true
  }
}
