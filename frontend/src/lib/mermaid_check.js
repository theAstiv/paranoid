import { isChunkLoadError } from './chunk_reload.js'
import { sanitizeMermaid } from './mermaid_sanitize.js'

const MAX_MESSAGE_CHARS = 160

/**
 * Parse Mermaid source the way the viewer will, so the wizard can flag a file that
 * isn't a diagram (prose in a .txt, a half-written diagram) at upload instead of
 * after the run (BB-125).
 *
 * Resolves to an error message, or null when the source parses or can't be checked.
 * A failure to load Mermaid itself is "can't be checked", not a verdict: the backend
 * still rejects files that are plainly not diagrams.
 *
 * @param {string} text
 * @returns {Promise<string|null>}
 */
export async function checkMermaidSource(text) {
  const cleaned = sanitizeMermaid(text)
  if (!cleaned) return 'The file has no diagram in it.'
  let mermaid
  try {
    mermaid = (await import('mermaid')).default
  } catch {
    return null
  }
  try {
    await mermaid.parse(cleaned)
    return null
  } catch (err) {
    if (isChunkLoadError(err)) return null
    const first = String(err?.message || 'Mermaid cannot parse this file.').split('\n')[0].trim()
    return first.length > MAX_MESSAGE_CHARS ? `${first.slice(0, MAX_MESSAGE_CHARS)}…` : first
  }
}
