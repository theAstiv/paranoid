const MAX_PASSES = 10

// Event names of the standard HTML/SVG handler attributes (`onclick` is `on` +
// `click`). Matching only these keeps label text such as "online = true" or
// "once=1" intact (BB-27). A handler missing from the list is not stripped here
// and is left to Mermaid's `securityLevel: 'strict'` + DOMPurify + the CSP.
const EVENT_NAMES = [
  'abort', 'afterprint', 'animationcancel', 'animationend', 'animationiteration',
  'animationstart', 'auxclick', 'beforeinput', 'beforeprint', 'beforetoggle',
  'beforeunload', 'begin', 'blur', 'cancel', 'canplay', 'canplaythrough', 'change',
  'click', 'close', 'contextmenu', 'copy', 'cuechange', 'cut', 'dblclick', 'drag',
  'dragend', 'dragenter', 'dragleave', 'dragover', 'dragstart', 'drop',
  'durationchange', 'emptied', 'end', 'ended', 'error', 'focus', 'focusin',
  'focusout', 'formdata', 'fullscreenchange', 'fullscreenerror', 'gotpointercapture',
  'hashchange', 'input', 'invalid', 'keydown', 'keypress', 'keyup', 'languagechange',
  'load', 'loadeddata', 'loadedmetadata', 'loadstart', 'lostpointercapture',
  'message', 'messageerror', 'mousedown', 'mouseenter', 'mouseleave', 'mousemove',
  'mouseout', 'mouseover', 'mouseup', 'mousewheel', 'offline', 'online', 'pagehide',
  'pageshow', 'paste', 'pause', 'play', 'playing', 'pointercancel', 'pointerdown',
  'pointerenter', 'pointerleave', 'pointermove', 'pointerout', 'pointerover',
  'pointerrawupdate', 'pointerup', 'popstate', 'progress', 'ratechange',
  'readystatechange', 'rejectionhandled', 'repeat', 'reset', 'resize', 'scroll',
  'scrollend', 'securitypolicyviolation', 'seeked', 'seeking', 'select',
  'selectionchange', 'selectstart', 'slotchange', 'stalled', 'storage', 'submit',
  'suspend', 'timeupdate', 'toggle', 'touchcancel', 'touchend', 'touchmove',
  'touchstart', 'transitioncancel', 'transitionend', 'transitionrun',
  'transitionstart', 'unhandledrejection', 'unload', 'volumechange', 'waiting',
  'webkitanimationend', 'webkitanimationiteration', 'webkitanimationstart',
  'webkittransitionend', 'wheel',
]
// A handler only counts at the start of a word (BB-60): label text such as
// `connectionError = x` or `buttonOnclick = 1` ends a word in "on" + an event name
// and must survive. The separator is captured (not a lookbehind, which old Safari
// lacks) and put back. Nothing is lost to the boundary: the BB-12 nested payloads
// rebuild a handler by deleting something *between* its pieces (a script block, a
// URI scheme), and the loop re-runs every strip until the text stops changing, so
// the rebuilt handler is seen on the next pass, now at a word start.
const HANDLER_ATTR = new RegExp(
  String.raw`(^|[^A-Za-z0-9_])on(?:${EVENT_NAMES.join('|')})\s*=\s*(?:"[^"]*"|'[^']*'|[^\s"'>]*)`,
  'gi',
)

// Tags Mermaid label text may keep (its own <br> line breaks and basic inline
// formatting). Everything below is stripped: an <img> in a label made a same-origin
// GET (KL-5), and the rest can load, navigate or restyle.
//
// Not "any <word>": diagrams legitimately hold `List<Object>` and `List<Source>`
// (class diagrams), `<<interface>>`, `<--` arrows and `a < b`, and `A[i<a] --> B` must
// keep its arrow. So an element name counts only when it is *used as a tag*:
//  - ATTRIBUTE_TAGS need whitespace or `/` after the name (`<img src=x>`, `<a href=y>`,
//    `<img/src=x>`); a generic never has that. Their closing tags (`</a>`) are removed too.
//  - BARE_TAGS are dangerous even with no attributes (`<svg>`, `<iframe>`, `<style>`),
//    and are not plausible type parameters.
// Names that are common label words (map, set, data, text, line, path, time, label,
// option, title) are in neither list. Mermaid's strict mode + DOMPurify + the CSP are
// still the real defence.
const ATTRIBUTE_TAGS = [
  'a', 'animate', 'animatetransform', 'area', 'audio', 'base', 'body', 'button', 'canvas',
  'dialog', 'div', 'embed', 'fieldset', 'form', 'frame', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
  'head', 'html', 'image', 'img', 'input', 'link', 'meta', 'noscript', 'object', 'p',
  'picture', 'select', 'source', 'span', 'table', 'td', 'textarea', 'th', 'tr', 'track',
  'use', 'video',
]
const BARE_TAGS = ['applet', 'foreignobject', 'frameset', 'iframe', 'math', 'style', 'svg']
// An unterminated tag stops at the end of its line, so it can't swallow the diagram.
const BLOCKED_TAG = new RegExp(
  [
    String.raw`</?(?:${BARE_TAGS.join('|')})(?![A-Za-z0-9_-])[^>\n]*>?`,
    String.raw`<(?:${ATTRIBUTE_TAGS.join('|')})(?=[\s/])[^>\n]*>?`,
    String.raw`</(?:${ATTRIBUTE_TAGS.join('|')})\s*>`,
  ].join('|'),
  'gi',
)

// Returns the cleaned text and whether a security strip (script, handler or URI
// scheme) removed anything. Entity decoding and the `---` rewrite are benign
// repairs and don't count.
function decodeAndStrip(input) {
  let s = input
  let removedUnsafe = false
  const strip = (re, keep = '') => {
    const next = s.replace(re, keep)
    if (next !== s) removedUnsafe = true
    s = next
  }
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
  strip(/javascript\s*:/gi)
  strip(/vbscript\s*:/gi)
  strip(/data\s*:\s*text\/html/gi)
  // Embedded <script> blocks and stray opening tags.
  strip(/<script[\s\S]*?<\/script[^>]*>/gi)
  strip(/<script[^>]*\/?>/gi)
  // Event handler attributes (onclick=, onload=, onerror=, …).
  strip(HANDLER_ATTR, '$1')
  // HTML tags other than Mermaid's label formatting (<img>, <svg>, <iframe>, …).
  strip(BLOCKED_TAG)
  // `---` -> `-->` inside the loop: it can supply the `>` that completes a
  // tag (`<script src=x---y`), so the next pass must see its output.
  // Bare `---` at the start of a line is YAML front-matter (legal Mermaid)
  // and is left alone: the rewrite needs a non-space character before it.
  s = s.replace(/(\S)\s*---\s*(\S)/g, '$1 --> $2')
  return { text: s, removedUnsafe }
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
 * schemes, `<script>` tags, known event-handler attributes and non-formatting HTML tags after entity-decoding,
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
  return sanitizeMermaidDetailed(source).text
}

/**
 * Like sanitizeMermaid, and also reports whether a payload (script, event handler or
 * dangerous URI scheme) was stripped. Stripping can leave source Mermaid can't parse
 * (a label emptied to `A[""]`), and the caller can then say the diagram was rejected
 * instead of showing a parse error (BB-39).
 *
 * @param {string} source
 * @returns {{ text: string, removedUnsafe: boolean }}
 */
export function sanitizeMermaidDetailed(source) {
  if (!source) return { text: '', removedUnsafe: false }
  let s = String(source)
  // Strip ```mermaid ... ``` fences (LLMs often wrap output)
  s = s.replace(/^\s*```(?:mermaid)?\s*/i, '').replace(/```\s*$/i, '')

  let settled = false
  let removedUnsafe = false
  for (let i = 0; i < MAX_PASSES; i++) {
    const next = decodeAndStrip(s)
    removedUnsafe ||= next.removedUnsafe
    if (next.text === s) {
      settled = true
      break
    }
    s = next.text
  }
  // Never hand a string that is still changing to the renderer.
  if (!settled) return { text: '', removedUnsafe: true }

  // Strip `click` directives — these can call JavaScript or open URLs and are
  // an XSS vector when securityLevel is not 'strict'. LLMs sometimes emit them.
  // A click directive looks like:  click NodeId callback "tooltip"
  //                            or: click NodeId href "url" [_blank]
  s = s.replace(/^\s*click\s+.*/gim, '')
  return { text: s.trim(), removedUnsafe }
}
