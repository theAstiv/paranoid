import { describe, it, expect } from 'vitest'
import { sanitizeMermaid, sanitizeMermaidDetailed } from './mermaid_sanitize.js'

// BB-39: callers need to know a payload was stripped, as opposed to a benign repair.
describe('sanitizeMermaidDetailed — removedUnsafe', () => {
  it.each([
    ['a script block', 'graph TD\nA[<script>alert(1)</script>] --> B'],
    ['a nested script tag', 'graph TD\nA[<scr<script>ipt>x] --> B'],
    ['an event handler', 'graph TD\nA[x onclick=alert(1)] --> B'],
    ['a javascript: scheme', 'graph TD\nA[javascript:alert(1)] --> B'],
    ['a source that never settles', 'graph TD\n' + '<scr'.repeat(12) + '<script>' + 'ipt>'.repeat(12)],
  ])('is true for %s', (_name, source) => {
    expect(sanitizeMermaidDetailed(source).removedUnsafe).toBe(true)
  })

  it.each([
    ['plain source', 'graph TD\nA --> B'],
    ['markdown fences', '```mermaid\ngraph TD\nA --> B\n```'],
    ['HTML entities', 'graph TD\nA[a &amp; b] --> B'],
    ['a --- separator', 'graph TD\nA --- B'],
    ['label text like "online = true"', 'graph TD\nA[online = true] --> B'],
    ['a click directive', 'graph TD\nA --> B\nclick A callback "tip"'],
    ['a blank source', ''],
  ])('is false for %s', (_name, source) => {
    expect(sanitizeMermaidDetailed(source).removedUnsafe).toBe(false)
  })

  it('returns the same text as sanitizeMermaid', () => {
    const source = '```mermaid\ngraph TD\nA[<script>x</script>] --> B\nclick A cb\n```'
    expect(sanitizeMermaidDetailed(source).text).toBe(sanitizeMermaid(source))
  })
})

describe('sanitizeMermaid', () => {
  it('returns empty string for nullish input', () => {
    expect(sanitizeMermaid('')).toBe('')
    expect(sanitizeMermaid(null)).toBe('')
    expect(sanitizeMermaid(undefined)).toBe('')
  })

  it('strips markdown fences with the mermaid language tag', () => {
    const raw = '```mermaid\ngraph TD\nA --> B\n```'
    expect(sanitizeMermaid(raw)).toBe('graph TD\nA --> B')
  })

  it('strips plain markdown fences without the language tag', () => {
    const raw = '```\ngraph TD\nA --> B\n```'
    expect(sanitizeMermaid(raw)).toBe('graph TD\nA --> B')
  })

  it('decodes &nbsp; &amp; &lt; &gt; entities', () => {
    const raw = 'graph TD\nA[Node&nbsp;1] --> B[A&amp;B]'
    const cleaned = sanitizeMermaid(raw)
    expect(cleaned).toContain('Node 1')
    expect(cleaned).toContain('A&B')
    expect(cleaned).not.toContain('&nbsp;')
    expect(cleaned).not.toContain('&amp;')
  })

  it('replaces inline `---` separators between tokens with arrows', () => {
    const raw = 'graph TD\nA --- B\nC---D'
    const cleaned = sanitizeMermaid(raw)
    expect(cleaned).toContain('A --> B')
    expect(cleaned).toContain('C --> D')
  })

  it('does not corrupt YAML-style front-matter at line start', () => {
    // A standalone `---` line is legal Mermaid front-matter; only `X---Y`
    // between two non-whitespace tokens gets rewritten.
    const raw = '---\ntitle: My Tree\n---\ngraph TD\nA --> B'
    const cleaned = sanitizeMermaid(raw)
    expect(cleaned.startsWith('---\n')).toBe(true)
    expect(cleaned).toContain('title: My Tree')
    expect(cleaned).toContain('A --> B')
  })

  it('trims leading and trailing whitespace', () => {
    expect(sanitizeMermaid('   graph TD\nA --> B   ')).toBe('graph TD\nA --> B')
  })

  it('handles a fully realistic LLM-wrapped output', () => {
    const raw = "```mermaid\ngraph TD\n  Root[Attacker&nbsp;Goal] --- Sub1\n  Sub1 --> Leaf\n```"
    const cleaned = sanitizeMermaid(raw)
    expect(cleaned).not.toContain('```')
    expect(cleaned).toContain('Attacker Goal')
    expect(cleaned).toContain('Root[Attacker Goal] --> Sub1')
    expect(cleaned).toContain('Sub1 --> Leaf')
  })

  it('strips click callback directives (XSS vector)', () => {
    const raw = 'graph TD\nA --> B\nclick A someCallback "tooltip"'
    const cleaned = sanitizeMermaid(raw)
    expect(cleaned).not.toContain('click')
    expect(cleaned).toContain('A --> B')
  })

  it('strips click href directives', () => {
    const raw = 'graph TD\nA --> B\nclick B href "https://evil.example" _blank'
    const cleaned = sanitizeMermaid(raw)
    expect(cleaned).not.toContain('click')
  })

  it('leaves non-click content after a click-looking word alone', () => {
    // Node labels that contain the word "click" should not be stripped
    const raw = 'graph TD\nA[User clicks button] --> B'
    // The node label is NOT a click directive (not at start of line as a directive)
    const cleaned = sanitizeMermaid(raw)
    expect(cleaned).toContain('User clicks button')
  })

  // XSS hardening — dangerous URI schemes
  it('strips javascript: URI scheme from node labels', () => {
    const raw = 'graph TD\nA[javascript:alert(1)] --> B'
    const cleaned = sanitizeMermaid(raw)
    expect(cleaned).not.toMatch(/javascript\s*:/i)
    // Node label bracket remains but the URI scheme is gone
    expect(cleaned).toContain('A[alert(1)] --> B')
  })

  it('strips encoded javascript: URI — decimal numeric reference decoded first', () => {
    // &#106; = 'j'. Without numeric-ref decoding the scheme survives as
    // "&#106;avascript:" and a browser/SVG renderer would later decode it.
    const raw = 'graph TD\nA[&#106;avascript:alert(1)] --> B'
    const cleaned = sanitizeMermaid(raw)
    // Confirm decoding happened (no raw numeric ref remains)
    expect(cleaned).not.toContain('&#106;')
    // Confirm the scheme was stripped after decoding
    expect(cleaned).not.toMatch(/javascript\s*:/i)
    // Full chain: decoded 'j' + stripped 'javascript:' → only payload text left
    expect(cleaned).toContain('A[alert(1)] --> B')
  })

  it('strips hex-encoded javascript: URI — hex numeric reference decoded first', () => {
    // &#x6A; = 'j' in hex. Same bypass vector via a different encoding.
    const raw = 'graph TD\nA[&#x6A;avascript:alert(1)] --> B'
    const cleaned = sanitizeMermaid(raw)
    expect(cleaned).not.toContain('&#x6A;')
    expect(cleaned).not.toMatch(/javascript\s*:/i)
    expect(cleaned).toContain('A[alert(1)] --> B')
  })

  it('strips vbscript: URI scheme', () => {
    const raw = 'graph TD\nA[vbscript:MsgBox(1)] --> B'
    const cleaned = sanitizeMermaid(raw)
    expect(cleaned).not.toMatch(/vbscript\s*:/i)
  })

  it('strips data:text/html URI scheme', () => {
    const raw = 'graph TD\nA[data:text/html,<h1>XSS</h1>] --> B'
    const cleaned = sanitizeMermaid(raw)
    expect(cleaned).not.toMatch(/data\s*:\s*text\/html/i)
  })

  // XSS hardening — script tags
  it('strips embedded <script> blocks', () => {
    const raw = 'graph TD\nA --> B\n<script>alert(1)</script>'
    const cleaned = sanitizeMermaid(raw)
    expect(cleaned).not.toMatch(/<script/i)
    expect(cleaned).toContain('A --> B')
  })

  it('strips self-closing <script> opening tags', () => {
    const raw = 'graph TD\nA --> B\n<script src="evil.js"/>'
    const cleaned = sanitizeMermaid(raw)
    expect(cleaned).not.toMatch(/<script/i)
  })

  it('strips nested / multi-line <script> blocks', () => {
    const raw = 'graph TD\nA --> B\n<script type="text/javascript">\nalert(1)\n</script>'
    const cleaned = sanitizeMermaid(raw)
    expect(cleaned).not.toMatch(/<script/i)
  })

  // XSS hardening — on* event handlers
  it('strips onclick event handler attributes', () => {
    const raw = 'graph TD\nA[Node onclick="alert(1)"] --> B'
    const cleaned = sanitizeMermaid(raw)
    expect(cleaned).not.toMatch(/\bonclick\s*=/i)
    // Handler is stripped; bracket and remaining text survive
    expect(cleaned).toContain('A[Node')
    expect(cleaned).toContain('--> B')
  })

  it('strips onload event handler attributes', () => {
    const raw = 'graph TD\nA[payload onload=\'fetch(evil)\'] --> B'
    const cleaned = sanitizeMermaid(raw)
    expect(cleaned).not.toMatch(/\bonload\s*=/i)
  })

  it('strips onerror event handler attributes', () => {
    const raw = 'graph TD\nA[img onerror="xss()"] --> B'
    const cleaned = sanitizeMermaid(raw)
    expect(cleaned).not.toMatch(/\bonerror\s*=/i)
  })

  // BB-27 — the strip targets real event-handler attributes, not any word that
  // starts with "on" (online, once, only, ongoing).
  describe('on* handler strip (BB-27)', () => {
    it.each(['online = true', 'once=1', 'only = "x"', 'ongoing = yes', 'onboarding=done'])(
      'keeps label text: %s',
      (text) => {
        const raw = `graph TD\nA[status ${text}] --> B`
        expect(sanitizeMermaid(raw)).toBe(raw)
      },
    )

    // Hardcoded on purpose: a loop over the implementation's own list could not
    // notice a handler missing from it.
    it.each([
      'onclick', 'ondblclick', 'onmouseover', 'onmouseenter', 'onmousedown', 'onkeydown', 'onkeyup',
      'onload', 'onerror', 'onabort', 'onfocus', 'onblur', 'onchange', 'oninput', 'onsubmit',
      'onreset', 'onselect', 'onscroll', 'onwheel', 'onresize', 'ontoggle', 'oncontextmenu',
      'onpointerdown', 'onpointerover', 'ontouchstart', 'ondrag', 'ondrop', 'onanimationstart',
      'onanimationend', 'ontransitionend', 'onpageshow', 'onhashchange', 'onmessage', 'onpopstate',
      'onbeforeunload', 'onunload', 'onplay', 'onended', 'onbegin', 'onend', 'onrepeat',
    ])('strips %s, bare or quoted, in any case', (name) => {
      for (const attr of [`${name}=alert(1)`, `${name} = "alert(1)"`, `${name.toUpperCase()}='alert(1)'`]) {
        const cleaned = sanitizeMermaid(`graph TD\nA[x ${attr}] --> B`)
        expect(cleaned).not.toMatch(new RegExp(`${name}\\s*=`, 'i'))
        expect(cleaned).not.toContain('alert(1)')
      }
    })
  })

  // BB-12 — single-pass strips can rebuild the very thing they remove, and
  // decoding &amp; before &lt;/&gt; double-decodes. Output must be a fixed point.
  describe('nested / split payloads (BB-12)', () => {
    const payloads = {
      'nested script open tag': 'graph TD\nA --> B\n<scr<script>ipt>alert(1)</script>',
      'nested script open tag, no closer': 'graph TD\nA --> B\n<scr<script>ipt>alert(1)',
      'dash rewrite completes a tag': 'graph TD\nA --> B\n<script src=x---y',
      'closing tag with whitespace': 'graph TD\nA --> B\n<script>alert(1)</script >',
      'nested script block': 'graph TD\nA --> B\n<scr<script></script>ipt>alert(1)</script>',
      'nested javascript scheme': 'graph TD\nA[javajavascript:script:alert(1)] --> B',
      'double-encoded tags': 'graph TD\nA[&amp;lt;script&amp;gt;alert(1)&amp;lt;/script&amp;gt;] --> B',
      'double-encoded scheme': 'graph TD\nA[&amp;#106;avascript:alert(1)] --> B',
      'nested vbscript scheme': 'graph TD\nA[vbvbscript:script:x] --> B',
      'nested data scheme': 'graph TD\nA[data:text/data:text/htmlhtml,x] --> B',
      'nested handler': 'graph TD\nA[x ononclick=1click=alert(1)] --> B',
    }
    const dangerous = [
      /<script/i,
      /javascript\s*:/i,
      /vbscript\s*:/i,
      /data\s*:\s*text\/html/i,
      /\bon\w+\s*=/i,
      /&#\d+;|&#x[0-9a-f]+;/i,
    ]

    for (const [name, raw] of Object.entries(payloads)) {
      it(`leaves nothing dangerous: ${name}`, () => {
        const cleaned = sanitizeMermaid(raw)
        for (const re of dangerous) expect(cleaned).not.toMatch(re)
      })

      it(`is idempotent: ${name}`, () => {
        const once = sanitizeMermaid(raw)
        expect(sanitizeMermaid(once)).toBe(once)
      })
    }
  })

  // Regression — legitimate diagrams must survive unchanged
  it('does not strip legitimate node labels containing the word "script"', () => {
    const raw = 'graph TD\nA[Run build script] --> B[Deploy]'
    const cleaned = sanitizeMermaid(raw)
    expect(cleaned).toContain('Run build script')
    expect(cleaned).toContain('Deploy')
  })

  it('does not strip arrows or subgraph blocks', () => {
    const raw = 'graph TD\nsubgraph Auth\n  A --> B\nend\nB --> C'
    const cleaned = sanitizeMermaid(raw)
    expect(cleaned).toContain('subgraph Auth')
    expect(cleaned).toContain('A --> B')
    expect(cleaned).toContain('B --> C')
  })
})
