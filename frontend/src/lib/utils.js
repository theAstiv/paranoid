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
 * Maps a CVSS v3.1 base score to its Tailwind text-color class, using
 * CVSS's own published severity cut points (4.0/7.0/9.0) — distinct from
 * dreadColor's bands (4/6/8), which average 5 independent 0-10 dimensions
 * rather than scoring one combined 0-10 scale.
 * @param {number} score
 * @returns {string} Tailwind class
 */
export function cvssColor(score) {
  if (score >= 9.0) return 'text-c-critical'
  if (score >= 7.0) return 'text-c-high'
  if (score >= 4.0) return 'text-c-medium'
  return 'text-c-low'
}

/**
 * Maps a CVSS v3.1 base score to its hex color for inline uses (e.g. SVG fill).
 * @param {number} score
 * @returns {string} hex color
 */
export function cvssHex(score) {
  if (score >= 9.0) return '#FB6F84'
  if (score >= 7.0) return '#FFA552'
  if (score >= 4.0) return '#F5D04E'
  return '#3FD0A8'
}

/**
 * Maps a CVSS v3.1 base score to its chip CSS class.
 * @param {number} score
 * @returns {string}
 */
export function cvssChip(score) {
  if (score >= 9.0) return 'chip-red'
  if (score >= 7.0) return 'chip-orange'
  if (score >= 4.0) return 'chip-amber'
  return 'chip-green'
}

/**
 * Returns the CVSS v3.1 qualitative severity rating for a score, matching
 * backend.scoring.cvss31.severity_for_score's bands.
 * @param {number} score
 * @returns {'Critical'|'High'|'Medium'|'Low'|'None'}
 */
export function cvssLabel(score) {
  if (score >= 9.0) return 'Critical'
  if (score >= 7.0) return 'High'
  if (score >= 4.0) return 'Medium'
  if (score > 0) return 'Low'
  return 'None'
}

/**
 * Formats a CVSS score to one decimal place for display — a raw score
 * round-trips through JSON as a bare number (7.0 becomes JS `7`), which
 * would otherwise render as "CVSS 7" instead of "CVSS 7.0".
 * @param {number} score
 * @returns {string}
 */
export function cvssScoreLabel(score) {
  return Number(score).toFixed(1)
}

/**
 * The 8 CVSS v3.1 base metrics: [vectorCode, displayLabel, fieldName, valueLabelsByCode].
 * Shared by CvssBadge (read-only breakdown) and ThreatCard (edit form) so
 * the metric list/labels/vector-string parsing live in exactly one place.
 */
export const CVSS_METRICS = [
  ['AV', 'Attack Vector', 'attack_vector', { N: 'Network', A: 'Adjacent', L: 'Local', P: 'Physical' }],
  ['AC', 'Attack Complexity', 'attack_complexity', { L: 'Low', H: 'High' }],
  ['PR', 'Privileges Required', 'privileges_required', { N: 'None', L: 'Low', H: 'High' }],
  ['UI', 'User Interaction', 'user_interaction', { N: 'None', R: 'Required' }],
  ['S', 'Scope', 'scope', { U: 'Unchanged', C: 'Changed' }],
  ['C', 'Confidentiality', 'confidentiality', { N: 'None', L: 'Low', H: 'High' }],
  ['I', 'Integrity', 'integrity', { N: 'None', L: 'Low', H: 'High' }],
  ['A', 'Availability', 'availability', { N: 'None', L: 'Low', H: 'High' }],
]

/**
 * Parses a CVSS v3.1 vector string ("AV:N/AC:L/...", optional "CVSS:3.1/"
 * prefix) into a {field_name: code} metrics object. Unknown metric codes
 * are ignored rather than raising — this only feeds UI display/editing, and
 * the server is the one source of truth that validates the vector.
 * @param {string} vector
 * @returns {Record<string, string>}
 */
export function parseCvssVector(vector) {
  const out = {}
  if (!vector) return out
  for (const part of vector.replace(/^CVSS:3\.1\//, '').split('/')) {
    const [code, value] = part.split(':')
    const metric = CVSS_METRICS.find(([metricCode]) => metricCode === code)
    if (metric) out[metric[2]] = value
  }
  return out
}

/**
 * Renders a {field_name: code} metrics object back to the canonical
 * "AV:N/AC:L/..." vector string, in CVSS_METRICS' fixed order.
 * @param {Record<string, string>} metrics
 * @returns {string}
 */
export function cvssVectorFromMetrics(metrics) {
  return CVSS_METRICS.map(([code, , field]) => `${code}:${metrics[field]}`).join('/')
}

/**
 * Normalizes a threat's CVSS metrics regardless of shape.
 *
 * `cvss_vector` (flat, from the DB/API) is checked first: it's what was
 * actually persisted. The nested `cvss` object (from a live SSE event, the
 * LLM's raw per-threat output) is only used as a fallback — if a threat
 * object ever carried both (e.g. a stale prop after an edit), preferring
 * the flat field avoids showing metrics that no longer match the saved
 * vector/score.
 * @param {object|null} threat
 * @returns {Record<string, string>|null}
 */
export function normalizeCvssMetrics(threat) {
  if (!threat) return null
  if (threat.cvss_vector) return parseCvssVector(threat.cvss_vector)
  if (threat.cvss && typeof threat.cvss === 'object') return threat.cvss
  return null
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

/**
 * All 11 dependency-engine capability categories, in a fixed display order —
 * matches backend.models.enums.CapabilityCategory.
 */
export const DEPENDENCY_CATEGORIES = [
  'network', 'filesystem', 'process', 'crypto', 'deserialization',
  'dynamic_code', 'native_ffi', 'persistence', 'authentication',
  'environment', 'build_install',
]

/**
 * The set of capability categories a `CapabilityProfile` shows evidence for,
 * mirroring `CapabilityProfile.category_set()` on the backend: only
 * `path_class === 'shipped'` evidence counts, and a flagged install hook
 * always contributes `build_install` even without its own evidence entry.
 * @param {{ evidence?: Array<{category: string, path_class: string}>, install_hooks?: string[] }} [profile]
 * @returns {Set<string>}
 */
export function dependencyCategorySet(profile) {
  const categories = new Set()
  if (!profile) return categories
  for (const e of profile.evidence ?? []) {
    if (e.path_class === 'shipped') categories.add(e.category)
  }
  if (profile.install_hooks?.length) categories.add('build_install')
  return categories
}

/**
 * Short flag labels summarizing what's notable about one package's
 * dependency-engine analysis — surfaced as the heatmap's flags column.
 * @param {{
 *   npm_profile?: {status?: string, install_hooks?: string[]},
 *   github_profile?: {status?: string},
 *   drift?: {signal?: boolean, status?: string},
 *   error?: string,
 * }} [analysis]
 * @returns {string[]}
 */
export function dependencyFlags(analysis) {
  const flags = []
  if (!analysis) return flags
  // `skip_reason` is a dependency that was never analyzed at all (no
  // resolvable pinned version, over the manifest's direct-dependency cap) —
  // distinct from `error`, which is a PackageAnalysis that was actually
  // attempted and failed. Conflating the two would flag an ordinary
  // git/file-spec dependency the same as a real analysis failure.
  if (analysis.skip_reason) flags.push('skipped')
  if (analysis.error) flags.push('error')
  if (analysis.drift?.signal) flags.push('drift')
  if (analysis.npm_profile?.install_hooks?.length) flags.push('install-hook')
  for (const profile of [analysis.npm_profile, analysis.github_profile]) {
    if (profile && profile.status && profile.status !== 'ok') flags.push(profile.status)
  }
  return [...new Set(flags)]
}

/**
 * Formats a package's display label — omits a dangling "@" when a
 * dropped/errored dependency was never resolved to a version.
 *
 * `pkg` may be a raw, unvalidated package.json key (a skipped dependency is
 * dropped before any name regex runs) — collapse embedded newlines/whitespace
 * runs so a hostile manifest key can't break the table layout. Svelte text
 * interpolation already prevents markup injection; this is layout hygiene.
 * @param {string} pkg
 * @param {string} version
 * @returns {string}
 */
export function dependencyDisplayName(pkg, version) {
  const name = pkg.trim().split(/\s+/).join(' ')
  return version ? `${name}@${version}` : name
}
