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
})
