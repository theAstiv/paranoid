import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/svelte'
import AttackTree from './AttackTree.svelte'

vi.mock('svelte-spa-router', () => ({
  link: () => ({ destroy: () => {} }),
}))

vi.mock('../lib/api.js', () => ({
  getThreat: vi.fn(),
  listAttackTrees: vi.fn(),
  generateAttackTree: vi.fn(),
}))

vi.mock('../lib/stores.js', async (importOriginal) => {
  const actual = await importOriginal()
  return { ...actual, notify: vi.fn() }
})

const mermaidRender = vi.fn()
vi.mock('mermaid', () => ({
  default: {
    initialize: vi.fn(),
    render: (...args) => mermaidRender(...args),
  },
}))

import { getThreat, listAttackTrees, generateAttackTree } from '../lib/api.js'
import { notify, currentModel } from '../lib/stores.js'

const baseThreat = { id: 't1', name: 'SQL Injection', description: 'desc' }

beforeEach(() => {
  vi.clearAllMocks()
  currentModel.set(null)
  getThreat.mockResolvedValue(baseThreat)
  listAttackTrees.mockResolvedValue([])
  mermaidRender.mockResolvedValue({ svg: '<svg>tree</svg>' })
})

describe('AttackTree — loading', () => {
  it('loads the threat and shows its details', async () => {
    render(AttackTree, { props: { params: { id: 't1' } } })
    await waitFor(() => expect(screen.getByText('SQL Injection')).toBeInTheDocument())
    expect(screen.getByText('desc')).toBeInTheDocument()
  })

  it('notifies on load failure', async () => {
    getThreat.mockRejectedValue(new Error('not found'))
    render(AttackTree, { props: { params: { id: 't1' } } })
    await waitFor(() => expect(notify).toHaveBeenCalledWith('error', expect.stringContaining('not found')))
  })

  it('shows an empty state when no attack tree exists yet', async () => {
    render(AttackTree, { props: { params: { id: 't1' } } })
    await waitFor(() => expect(screen.getByText(/No attack tree yet/)).toBeInTheDocument())
    expect(screen.getByText('Generate')).toBeInTheDocument()
  })

  it('shows the "← Review" link only when a current model is set', async () => {
    currentModel.set({ id: 'm1' })
    const { container } = render(AttackTree, { props: { params: { id: 't1' } } })
    await waitFor(() => expect(screen.getByText('SQL Injection')).toBeInTheDocument())
    expect(container.querySelector('a[href="/models/m1/review"]')).not.toBeNull()
  })
})

describe('AttackTree — existing tree', () => {
  it('renders the most recently generated tree on load', async () => {
    listAttackTrees.mockResolvedValue([
      { id: 'tree1', mermaid_source: 'graph TD; A-->B' },
      { id: 'tree2', mermaid_source: 'graph TD; C-->D' },
    ])
    render(AttackTree, { props: { params: { id: 't1' } } })
    await waitFor(() => expect(mermaidRender).toHaveBeenCalled())
    expect(screen.getByText('Regenerate')).toBeInTheDocument()
  })
})

describe('AttackTree — generate', () => {
  it('generates a new tree and renders it', async () => {
    generateAttackTree.mockResolvedValue({ id: 'tree1', mermaid_source: 'graph TD; A-->B' })
    render(AttackTree, { props: { params: { id: 't1' } } })
    await waitFor(() => expect(screen.getByText('Generate')).toBeInTheDocument())

    await fireEvent.click(screen.getByText('Generate'))

    await waitFor(() => expect(generateAttackTree).toHaveBeenCalledWith('t1'))
    await waitFor(() => expect(mermaidRender).toHaveBeenCalled())
    await waitFor(() => expect(screen.getByText('Regenerate')).toBeInTheDocument())
  })

  it('notifies on generation failure', async () => {
    generateAttackTree.mockRejectedValue(new Error('LLM timeout'))
    render(AttackTree, { props: { params: { id: 't1' } } })
    await waitFor(() => expect(screen.getByText('Generate')).toBeInTheDocument())

    await fireEvent.click(screen.getByText('Generate'))

    await waitFor(() => expect(notify).toHaveBeenCalledWith('error', expect.stringContaining('LLM timeout')))
  })

  it('shows a render-failure panel with a raw-source toggle when mermaid rendering throws', async () => {
    generateAttackTree.mockResolvedValue({ id: 'tree1', mermaid_source: 'graph TD; broken!!!' })
    mermaidRender.mockRejectedValue(new Error('Parse error'))
    render(AttackTree, { props: { params: { id: 't1' } } })
    await waitFor(() => expect(screen.getByText('Generate')).toBeInTheDocument())

    await fireEvent.click(screen.getByText('Generate'))

    await waitFor(() => expect(screen.getByText('Mermaid rendering failed')).toBeInTheDocument())
    expect(screen.queryByText('graph TD; broken!!!')).toBeNull()

    await fireEvent.click(screen.getByText('Show raw source'))
    expect(screen.getByText('graph TD; broken!!!')).toBeInTheDocument()

    await fireEvent.click(screen.getByText('Hide raw source'))
    expect(screen.queryByText('graph TD; broken!!!')).toBeNull()
  })
})
