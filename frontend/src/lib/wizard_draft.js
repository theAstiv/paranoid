// The New Model wizard's unsaved input, kept per tab (BB-124): a refresh, or
// Back out of the wizard and in again, used to lose everything typed.
// sessionStorage is per tab already, so two tabs keep two drafts. Every access
// is guarded: storage can be absent or throw (private mode, blocked site data).

const KEY = 'paranoid:new-model-draft:v1'

/** @returns {Record<string, any> | null} the saved draft, or null if none or unreadable */
export function loadDraft() {
  try {
    const raw = sessionStorage.getItem(KEY)
    if (!raw) return null
    const draft = JSON.parse(raw)
    return draft && typeof draft === 'object' && !Array.isArray(draft) ? draft : null
  } catch {
    return null
  }
}

/** @param {Record<string, any>} draft */
export function saveDraft(draft) {
  try {
    sessionStorage.setItem(KEY, JSON.stringify(draft))
  } catch {
    // Full or unavailable: the wizard still works, it just won't survive a reload.
  }
}

export function clearDraft() {
  try {
    sessionStorage.removeItem(KEY)
  } catch {
    // Nothing to clear.
  }
}

export const DRAFT_KEY = KEY
