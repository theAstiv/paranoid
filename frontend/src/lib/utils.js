/**
 * Maps a DREAD score to its Tailwind text-color class using the design handoff severity scale.
 * @param {number} score
 * @returns {string} Tailwind class
 */
export function dreadColor(score) {
  if (score >= 8) return 'text-c-critical'
  if (score >= 6) return 'text-c-high'
  if (score >= 4) return 'text-c-medium'
  return 'text-c-low'
}

/**
 * Maps a DREAD score to its hex color for inline uses (e.g. SVG fill).
 * @param {number} score
 * @returns {string} hex color
 */
export function dreadHex(score) {
  if (score >= 8) return '#FB6F84'
  if (score >= 6) return '#FFA552'
  if (score >= 4) return '#F5D04E'
  return '#3FD0A8'
}

/**
 * Maps a DREAD score to its chip CSS class.
 * @param {number} score
 * @returns {string}
 */
export function dreadChip(score) {
  if (score >= 8) return 'chip-red'
  if (score >= 6) return 'chip-orange'
  if (score >= 4) return 'chip-amber'
  return 'chip-green'
}

/**
 * Returns a short display label for a severity level.
 * @param {number} score
 * @returns {'Critical'|'High'|'Medium'|'Low'}
 */
export function dreadLabel(score) {
  if (score >= 8) return 'Critical'
  if (score >= 6) return 'High'
  if (score >= 4) return 'Medium'
  return 'Low'
}

/**
 * Truncates a UUID-like id to its first 8 chars for display.
 * @param {string} id
 * @returns {string}
 */
export function shortId(id) {
  return (id || '').slice(0, 8)
}

/**
 * Formats an ISO timestamp as a relative label ("2h ago", "just now", etc.)
 * @param {string} iso
 * @returns {string}
 */
export function relativeTime(iso) {
  if (!iso) return '—'
  const diff = (Date.now() - new Date(iso).getTime()) / 1000
  if (diff < 60) return 'just now'
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return `${Math.floor(diff / 86400)}d ago`
}

/**
 * Returns initials (up to 2 chars) from a display name or username.
 * @param {string} name
 * @returns {string}
 */
export function initials(name) {
  if (!name) return '?'
  const parts = name.trim().split(/\s+/)
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
}
