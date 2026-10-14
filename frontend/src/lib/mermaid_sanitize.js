const MAX_PASSES = 10

function decodeAndStrip(input) {
  let s = input
  // Numeric references first, then named ones. `&amp;` goes LAST so that
  // `&amp;lt;` is left as `&lt;` for the next pass instead of being expanded
  // to `<` in the same pass.
  s = s.replace(/&#(\d+);/g, (_, code) => String.fromCharCode(parseInt(code, 10)))
  s = s.replace(/&#x([0-9a-fA-F]+);/gi, (_, code) => String.fromCharCode(parseInt(code, 16)))
  s = s
    .replace(/&nbsp;/gi, ' ')
    .replace(/&lt;/gi, '<')
    .replace(/&gt;/gi, '>')
    .replace(/&amp;/gi, '&')
  // Dangerous URI schemes.
  s = s.replace(/javascript\s*:/gi, '')
  s = s.replace(/vbscript\s*:/gi, '')
  s = s.replace(/data\s*:\s*text\/html/gi, '')
  // Embedded <script> blocks and stray opening tags.
  s = s.replace(/<script[\s\S]*?<\/script[^>]*>/gi, '')
  s = s.replace(/<script[^>]*\/?>/gi, '')
  // on* event handler attributes (onclick=, onload=, onerror=, …).
  s = s.replace(/\bon\w+\s*=\s*(?:"[^"]*"|'[^']*'|[^\s"'>]*)/gi, '')
  // `---` -> `-->` inside the loop: it can supply the `>` that completes a
  // tag (`<script src=x---y`), so the next pass must see its output.
  // Bare `---` at the start of a line is YAML front-matter (legal Mermaid)
  // and is left alone: the rewrite needs a non-space character before it.
  s = s.replace(/(\S)\s*---\s*(\S)/g, '$1 --> $2')
  return s
}

/**
 * Clean common LLM Mermaid output quirks before handing to mermaid.render().
 * Most failures come from markdown fences, HTML entities, or `---` separators
 * that the LLM wrote where an arrow was meant. Run BEFORE rendering, not only
 * on failure, so the parser sees the cleanest possible input.
 *
 * Security note: this is defence in depth. The real protection is Mermaid's
 * `securityLevel: 'strict'` (its own DOMPurify pass) plus the CSP. We still
 * strip `click` directives, `javascript:`/`vbscript:`/`data:text/html` URI
 * schemes, `<script>` tags and `on*` handler attributes after entity-decoding,
 * so encoded payloads (e.g. `&#106;avascript:`) are caught before matching.
 *
 * Decoding and stripping repeat until the string stops changing: a single
 * pass can rebuild what it removed (`<scr<script>ipt>`, `javajavascript:script:`)
 * or leave an entity that a later decode would expand (`&amp;#106;`).
 *
 * @param {string} source Raw Mermaid string (possibly wrapped in fences).
 * @returns {string} Cleaned Mermaid source, or '' if it never settles.
 */
export function sanitizeMermaid(source) {
  if (!source) return ''
  let s = String(source)
  // Strip ```mermaid ... ``` fences (LLMs often wrap output)
  s = s.replace(/^\s*```(?:mermaid)?\s*/i, '').replace(/```\s*$/i, '')

  let settled = false
  for (let i = 0; i < MAX_PASSES; i++) {
    const next = decodeAndStrip(s)
    if (next === s) {
      settled = true
      break
    }
    s = next
  }
  // Never hand a string that is still changing to the renderer.
  if (!settled) return ''

  // Strip `click` directives — these can call JavaScript or open URLs and are
  // an XSS vector when securityLevel is not 'strict'. LLMs sometimes emit them.
  // A click directive looks like:  click NodeId callback "tooltip"
  //                            or: click NodeId href "url" [_blank]
  s = s.replace(/^\s*click\s+.*/gim, '')
  return s.trim()
}
