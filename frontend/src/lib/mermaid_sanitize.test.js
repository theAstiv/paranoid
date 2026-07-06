import { describe, it, expect } from 'vitest'
import { sanitizeMermaid } from './mermaid_sanitize.js'

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
