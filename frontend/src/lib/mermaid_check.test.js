import { describe, it, expect, vi, beforeEach } from 'vitest'

const parse = vi.fn()
vi.mock('mermaid', () => ({ default: { parse: (...args) => parse(...args) } }))

import { checkMermaidSource } from './mermaid_check.js'

beforeEach(() => {
  parse.mockReset()
  parse.mockResolvedValue({ diagramType: 'flowchart-v2' })
})

describe('checkMermaidSource (BB-125)', () => {
  it('returns null for a source Mermaid parses', async () => {
    expect(await checkMermaidSource('graph TD\nA --> B')).toBeNull()
    expect(parse).toHaveBeenCalledWith('graph TD\nA --> B')
  })

  it('returns the first line of the parse error', async () => {
    parse.mockRejectedValue(new Error('No diagram type detected matching given configuration for text: hi\nmore'))
    expect(await checkMermaidSource('hi there')).toBe(
      'No diagram type detected matching given configuration for text: hi',
    )
  })

  it('shortens a long message', async () => {
    parse.mockRejectedValue(new Error('x'.repeat(400)))
    const message = await checkMermaidSource('graph TD\nA')
    expect(message.length).toBeLessThanOrEqual(161)
    expect(message.endsWith('…')).toBe(true)
  })

  it('reports an empty file without calling Mermaid', async () => {
    expect(await checkMermaidSource('   \n')).toMatch(/no diagram/i)
    expect(parse).not.toHaveBeenCalled()
  })

  it('parses the sanitized text, so a stripped payload is not blamed on the file', async () => {
    await checkMermaidSource('graph TD\nA[<img src=x>ok] --> B')
    expect(parse.mock.calls[0][0]).not.toMatch(/<img/i)
  })

  it('treats a failed chunk download as "cannot check", not a parse error', async () => {
    parse.mockRejectedValue(new TypeError('Failed to fetch dynamically imported module: /assets/x.js'))
    expect(await checkMermaidSource('graph TD\nA --> B')).toBeNull()
  })
})
