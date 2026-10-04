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
