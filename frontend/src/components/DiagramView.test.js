import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/svelte'
import DiagramView from './DiagramView.svelte'

const mermaidRender = vi.fn()
const mermaidInitialize = vi.fn()
const mermaidRegisterLayoutLoaders = vi.fn()
vi.mock('mermaid', () => ({
  default: {
    initialize: (...args) => mermaidInitialize(...args),
    render: (...args) => mermaidRender(...args),
    registerLayoutLoaders: (...args) => mermaidRegisterLayoutLoaders(...args),
  },
}))
vi.mock('@mermaid-js/layout-elk', () => ({ default: ['elk-layout-stub'] }))

beforeEach(() => {
  vi.clearAllMocks()
  mermaidRender.mockResolvedValue({ svg: '<svg><g class="node"><rect/></g></svg>' })
})

describe('DiagramView — mermaid', () => {
  it('registers the ELK layout loader before the first render', async () => {
    // elkRegisterPromise (module scope) caches after the first call, so this
    // must stay the first test in the file to observe the registration call.
    render(DiagramView, {
      props: { kind: 'mermaid', content: 'graph TD; A-->B', name: 'arch' },
    })
    await waitFor(() => expect(mermaidRegisterLayoutLoaders).toHaveBeenCalledWith(['elk-layout-stub']))
    expect(mermaidInitialize).toHaveBeenCalledWith(expect.objectContaining({ layout: 'elk' }))
  })

  it('renders mermaid source into the container', async () => {
    const { container } = render(DiagramView, {
      props: { kind: 'mermaid', content: 'graph TD; A-->B', name: 'arch' },
    })
    await waitFor(() => expect(mermaidRender).toHaveBeenCalled())
    expect(container.querySelector('.diagram-svg svg')).not.toBeNull()
  })

  it('shows a render-failure panel with a raw-source toggle when rendering throws', async () => {
    mermaidRender.mockRejectedValue(new Error('Parse error'))
    render(DiagramView, { props: { kind: 'mermaid', content: 'graph TD; broken!!!', name: 'arch' } })

    await waitFor(() => expect(screen.getByText('Diagram rendering failed')).toBeInTheDocument())
    expect(screen.queryByText('graph TD; broken!!!')).toBeNull()

    await fireEvent.click(screen.getByText('Show raw source'))
    expect(screen.getByText('graph TD; broken!!!')).toBeInTheDocument()
  })

  it('shows an empty-source message without calling mermaid.render', async () => {
    render(DiagramView, { props: { kind: 'mermaid', content: '', name: 'arch' } })
    await waitFor(() => expect(screen.getByText('Mermaid source is empty.')).toBeInTheDocument())
    expect(mermaidRender).not.toHaveBeenCalled()
  })

  it('re-renders when content changes even if the length stays the same', async () => {
    const { rerender } = render(DiagramView, {
      props: { kind: 'mermaid', content: 'graph TD; A-->B', name: 'arch' },
    })
    await waitFor(() => expect(mermaidRender).toHaveBeenCalledTimes(1))

    mermaidRender.mockResolvedValue({ svg: '<svg><g class="node"><rect/></g>second</svg>' })
    await rerender({ kind: 'mermaid', content: 'graph TD; C-->D', name: 'arch' }) // same length as the first source
    await waitFor(() => expect(mermaidRender).toHaveBeenCalledTimes(2))
  })

  it('drops a stale render that resolves after a newer one started', async () => {
    let resolveFirst
    mermaidRender.mockImplementationOnce(
      () => new Promise((resolve) => { resolveFirst = resolve })
    )
    const { rerender, container } = render(DiagramView, {
      props: { kind: 'mermaid', content: 'graph TD; A-->B', name: 'arch' },
    })
    await waitFor(() => expect(mermaidRender).toHaveBeenCalledTimes(1))

    mermaidRender.mockResolvedValueOnce({ svg: '<svg id="second"></svg>' })
    await rerender({ kind: 'mermaid', content: 'graph TD; C-->D', name: 'arch' })
    await waitFor(() => expect(mermaidRender).toHaveBeenCalledTimes(2))

    // The first (stale) render finally resolves — it must not overwrite the second's result.
    resolveFirst({ svg: '<svg id="first"></svg>' })
    await waitFor(() => expect(container.querySelector('#second')).not.toBeNull())
    expect(container.querySelector('#first')).toBeNull()
  })

  it('re-renders after switching away to an image and back to the same mermaid source', async () => {
    // Regression: the mermaid branch's container unmounts while kind is
    // 'png', so lastRenderedKey must reset — otherwise switching back to the
    // exact same mermaid content leaves the viewport blank.
    const { rerender, container } = render(DiagramView, {
      props: { kind: 'mermaid', content: 'graph TD; A-->B', name: 'arch' },
    })
    await waitFor(() => expect(mermaidRender).toHaveBeenCalledTimes(1))

    await rerender({ kind: 'png', content: 'aGVsbG8=', mediaType: 'image/png', name: 'arch' })
    expect(container.querySelector('.diagram-svg')).toBeNull()

    await rerender({ kind: 'mermaid', content: 'graph TD; A-->B', name: 'arch' })
    await waitFor(() => expect(mermaidRender).toHaveBeenCalledTimes(2))
    expect(container.querySelector('.diagram-svg svg')).not.toBeNull()
  })
})

describe('DiagramView — ELK failure and retry', () => {
  it('resets the cached ELK registration on any render failure so a retry can re-import and succeed', async () => {
    // Force a failure first so the catch block resets the module-scope
    // elkRegisterPromise back to null — otherwise a prior successful
    // registration (from an earlier test in this file) would mask this
    // scenario, since ensureElkRegistered only re-imports when it's null.
    mermaidRender.mockRejectedValueOnce(new Error('boom'))
    render(DiagramView, { props: { kind: 'mermaid', content: 'graph TD; A-->B', name: 'arch' } })
    await waitFor(() => expect(screen.getByText('Diagram rendering failed')).toBeInTheDocument())

    // ELK registration itself fails on the next attempt.
    mermaidRegisterLayoutLoaders.mockImplementationOnce(() => { throw new Error('chunk load failed') })
    await fireEvent.click(screen.getByText('Retry'))
    await waitFor(() => expect(screen.getByText('Diagram rendering failed')).toBeInTheDocument())

    // ELK registration succeeds this time — Retry should now render normally.
    await fireEvent.click(screen.getByText('Retry'))
    await waitFor(() => expect(screen.queryByText('Diagram rendering failed')).toBeNull())
  })
})

describe('DiagramView — fit to view', () => {
  it('scales and centers the content to fill the viewport', async () => {
    const { container } = render(DiagramView, {
      props: { kind: 'mermaid', content: 'graph TD; A-->B', name: 'arch' },
    })
    await waitFor(() => expect(container.querySelector('.diagram-svg svg')).not.toBeNull())

    const viewport = container.querySelector('[role="application"]')
    viewport.getBoundingClientRect = () => ({ width: 480, height: 480, top: 0, left: 0, right: 480, bottom: 480 })
    const svg = container.querySelector('.diagram-svg svg')
    svg.getBoundingClientRect = () => ({ width: 1200, height: 600, top: 0, left: 0, right: 1200, bottom: 600 })

    await fireEvent.click(screen.getByLabelText('Fit to view'))

    const transform = container.querySelector('.absolute').style.transform
    expect(transform).not.toBe('translate(0px, 0px) scale(1)')
  })
})

describe('DiagramView — wheel gating', () => {
  it('does not preventDefault or zoom on a plain wheel event', async () => {
    const { container } = render(DiagramView, { props: { kind: 'mermaid', content: 'graph TD; A-->B', name: 'arch' } })
    await waitFor(() => expect(container.querySelector('.diagram-svg svg')).not.toBeNull())
    const viewport = container.querySelector('[role="application"]')
    const evt = new WheelEvent('wheel', { deltaY: -100, cancelable: true })
    viewport.dispatchEvent(evt)
    expect(evt.defaultPrevented).toBe(false)
  })

  it('zooms and preventDefaults when ctrlKey is held', async () => {
    const { container } = render(DiagramView, { props: { kind: 'mermaid', content: 'graph TD; A-->B', name: 'arch' } })
    await waitFor(() => expect(container.querySelector('.diagram-svg svg')).not.toBeNull())
    const viewport = container.querySelector('[role="application"]')
    const evt = new WheelEvent('wheel', { deltaY: -100, cancelable: true, ctrlKey: true })
    viewport.dispatchEvent(evt)
    expect(evt.defaultPrevented).toBe(true)
  })
})

describe('DiagramView — image', () => {
  it('renders a base64 png as an <img>', () => {
    const { container } = render(DiagramView, {
      props: { kind: 'png', content: 'aGVsbG8=', mediaType: 'image/png', name: 'arch' },
    })
    const img = container.querySelector('img')
    expect(img).not.toBeNull()
    expect(img.getAttribute('src')).toBe('data:image/png;base64,aGVsbG8=')
  })

  it('does not show the Export SVG button for images', () => {
    render(DiagramView, {
      props: { kind: 'png', content: 'aGVsbG8=', mediaType: 'image/png', name: 'arch' },
    })
    expect(screen.queryByText('Export SVG')).toBeNull()
  })
})
