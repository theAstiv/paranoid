/**
 * Clean common LLM Mermaid output quirks before handing to mermaid.render().
 * Most failures come from markdown fences, HTML entities, or `---` separators
 * that the LLM wrote where an arrow was meant. Run BEFORE rendering, not only
 * on failure, so the parser sees the cleanest possible input.
 *
 * Security note: `click` directives in Mermaid can execute JavaScript when
 * `securityLevel: 'loose'` is set. We strip them here so the caller can safely
 * use the stricter `'strict'` security level. Additionally, `javascript:`/
 * `vbscript:`/`data:text/html` URI schemes, embedded `<script>` tags, and
 * `on*` event handler attributes are removed after entity-decoding so that
 * encoded payloads (e.g. `&#106;avascript:`) are caught before matching.
 *
 * @param {string} source Raw Mermaid string (possibly wrapped in fences).
 * @returns {string} Cleaned Mermaid source.
 */
export function sanitizeMermaid(source) {
  if (!source) return ''
  let s = String(source)
  // Strip ```mermaid ... ``` fences (LLMs often wrap output)
  s = s.replace(/^\s*```(?:mermaid)?\s*/i, '').replace(/```\s*$/i, '')
  // Decode HTML entities that break the parser — must run BEFORE the XSS
  // strips below so encoded payloads like &#106;avascript: or &#x6A;avascript:
  // are normalised to plain text before scheme-matching.
  // Numeric decimal references (&#106;) and hex references (&#x6A;) first:
  s = s.replace(/&#(\d+);/g, (_, code) => String.fromCharCode(parseInt(code, 10)))
  s = s.replace(/&#x([0-9a-fA-F]+);/gi, (_, code) => String.fromCharCode(parseInt(code, 16)))
  // Named entity references:
  s = s
    .replace(/&nbsp;/gi, ' ')
    .replace(/&amp;/gi, '&')
    .replace(/&lt;/gi, '<')
    .replace(/&gt;/gi, '>')
  // Strip dangerous URI schemes from labels/hrefs.
  s = s.replace(/javascript\s*:/gi, '')
  s = s.replace(/vbscript\s*:/gi, '')
  s = s.replace(/data\s*:\s*text\/html/gi, '')
  // Strip embedded <script> blocks (including self-closing opening tags).
  s = s.replace(/<script[\s\S]*?<\/script>/gi, '')
  s = s.replace(/<script[^>]*\/?>/gi, '')
  // Strip on* event handler attributes (onclick=, onload=, onerror=, …).
  s = s.replace(/\bon\w+\s*=\s*(?:"[^"]*"|'[^']*'|[^\s"'>]*)/gi, '')
  // Strip `click` directives — these can call JavaScript or open URLs and are
  // an XSS vector when securityLevel is not 'strict'. LLMs sometimes emit them.
  // A click directive looks like:  click NodeId callback "tooltip"
  //                            or: click NodeId href "url" [_blank]
  s = s.replace(/^\s*click\s+.*/gim, '')
  // Replace bare `---` separators between two non-whitespace tokens on the
  // same line with arrows. Bare `---` at the start of a line is YAML
  // front-matter (legal Mermaid) and is left alone.
  s = s.replace(/(\S)\s*---\s*(\S)/g, '$1 --> $2')
  return s.trim()
}
