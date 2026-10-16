import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/svelte'
import ResourceList from './ResourceList.svelte'

vi.mock('../lib/stores.js', () => ({
  notify: vi.fn(),
}))

import { notify } from '../lib/stores.js'

const fields = [
  { key: 'name', label: 'Name' },
  { key: 'type', label: 'Type' },
]

const items = [
  { id: 'a1', name: 'Auth Service', type: 'internal' },
  { id: 'a2', name: 'Payment API', type: 'external' },
]

describe('ResourceList', () => {
  let onCreate, onUpdate, onDelete

  beforeEach(() => {
    vi.clearAllMocks()
    onCreate = vi.fn().mockResolvedValue({ id: 'new-1', name: 'New Item', type: 'internal' })
    onUpdate = vi.fn().mockResolvedValue({ id: 'a1', name: 'Updated', type: 'internal' })
    onDelete = vi.fn().mockResolvedValue(undefined)
  })

  it('shows empty label when items is empty', () => {
    render(ResourceList, { props: { items: [], fields, onCreate, onUpdate, onDelete, emptyLabel: 'No assets yet.' } })
    expect(screen.getByText('No assets yet.')).toBeInTheDocument()
  })

  it('renders item names from items array', () => {
    render(ResourceList, { props: { items, fields, onCreate, onUpdate, onDelete } })
    expect(screen.getByText('Auth Service')).toBeInTheDocument()
    expect(screen.getByText('Payment API')).toBeInTheDocument()
  })

  it('renders secondary field values', () => {
    render(ResourceList, { props: { items, fields, onCreate, onUpdate, onDelete } })
    expect(screen.getByText('internal')).toBeInTheDocument()
    expect(screen.getByText('external')).toBeInTheDocument()
  })

  it('startAdd() shows the add form', async () => {
    const { component } = render(ResourceList, { props: { items: [], fields, onCreate, onUpdate, onDelete } })
    component.startAdd()
    // Trigger Svelte reactivity
    await new Promise(r => setTimeout(r, 0))
    expect(screen.getByText('Add')).toBeInTheDocument()
  })

  it('Cancel button hides the add form', async () => {
    const { component } = render(ResourceList, { props: { items: [], fields, onCreate, onUpdate, onDelete } })
    component.startAdd()
    await new Promise(r => setTimeout(r, 0))
    await fireEvent.click(screen.getByText('Cancel'))
    expect(screen.queryByText('Add')).toBeNull()
  })

  it('Add button calls onCreate with draft', async () => {
    const { component } = render(ResourceList, { props: { items: [], fields, onCreate, onUpdate, onDelete } })
    component.startAdd()
    await new Promise(r => setTimeout(r, 0))
    await fireEvent.click(screen.getByText('Add'))
    expect(onCreate).toHaveBeenCalledOnce()
  })

  it('calls notify on onCreate failure', async () => {
    onCreate = vi.fn().mockRejectedValue(new Error('Server error'))
    const { component } = render(ResourceList, { props: { items: [], fields, onCreate, onUpdate, onDelete } })
    component.startAdd()
    await new Promise(r => setTimeout(r, 0))
    await fireEvent.click(screen.getByText('Add'))
    await new Promise(r => setTimeout(r, 0))
    expect(notify).toHaveBeenCalledWith('error', expect.stringContaining('Server error'))
  })

  it('calls onDelete when delete button is clicked', async () => {
    render(ResourceList, { props: { items, fields, onCreate, onUpdate, onDelete } })
    const deleteButtons = screen.getAllByTitle('Delete')
    await fireEvent.click(deleteButtons[0])
    await new Promise(r => setTimeout(r, 0))
    expect(onDelete).toHaveBeenCalledWith('a1')
  })

  it('calls notify on onDelete failure', async () => {
    onDelete = vi.fn().mockRejectedValue(new Error('Not found'))
    render(ResourceList, { props: { items, fields, onCreate, onUpdate, onDelete } })
    const deleteButtons = screen.getAllByTitle('Delete')
    await fireEvent.click(deleteButtons[0])
    await new Promise(r => setTimeout(r, 0))
    expect(notify).toHaveBeenCalledWith('error', expect.stringContaining('Not found'))
  })

  it('shows "—" for null/empty field values', () => {
    const sparseItems = [{ id: 'x1', name: 'Sparse', type: '' }]
    render(ResourceList, { props: { items: sparseItems, fields, onCreate, onUpdate, onDelete } })
    expect(screen.getByText('—')).toBeInTheDocument()
  })
})

describe('ResourceList asset links', () => {
  const linkFields = [
    { key: 'source_entity', label: 'Source', linkKey: 'source_asset_id' },
    { key: 'target_entity', label: 'Target', linkKey: 'target_asset_id' },
  ]
  const noop = vi.fn()

  it('renders a linked endpoint as a chip and an unlinked one as plain text', () => {
    const rows = [{ id: 'f1', source_entity: 'API Gateway', target_entity: 'Mystery', source_asset_id: 'a1', target_asset_id: null }]
    render(ResourceList, { props: { items: rows, fields: linkFields, onCreate: noop, onUpdate: noop, onDelete: noop } })
    expect(screen.getByText('API Gateway')).toHaveClass('chip-accent')
    expect(screen.getByText('Mystery')).not.toHaveClass('chip-accent')
  })

  // BB-28: `whitespace-nowrap` let one long extracted endpoint name widen the
  // whole Results page past the viewport. Chips must wrap inside their column.
  it('lets a long endpoint wrap instead of widening the page, linked or not', () => {
    const rows = [{ id: 'f1', source_entity: 'Tool Allowlist / Enforcer', target_entity: 'Mystery', source_asset_id: 'a1', target_asset_id: null }]
    render(ResourceList, { props: { items: rows, fields: linkFields, onCreate: noop, onUpdate: noop, onDelete: noop } })
    for (const chip of [screen.getByText('Tool Allowlist / Enforcer'), screen.getByText('Mystery')]) {
      expect(chip).not.toHaveClass('whitespace-nowrap')
      expect(chip).toHaveClass('break-words')
    }
    // The target chip's left margin sits outside max-width, so it subtracts it
    // (else a wrapped chip sticks out of its column by the margin).
    expect(screen.getByText('Tool Allowlist / Enforcer')).toHaveClass('max-w-full')
    expect(screen.getByText('Mystery')).toHaveClass('ml-1.5', 'max-w-[calc(100%-0.375rem)]')
  })

  it('sizes unlinked text the same as a linked chip', () => {
    const rows = [{ id: 'f1', source_entity: 'Tool Allowlist / Enforcer', target_entity: 'Mystery', source_asset_id: 'a1', target_asset_id: null }]
    render(ResourceList, { props: { items: rows, fields: linkFields, onCreate: noop, onUpdate: noop, onDelete: noop } })
    const linked = screen.getByText('Tool Allowlist / Enforcer')
    const plain = screen.getByText('Mystery')
    expect(linked.className).toContain('text-[11px]')
    expect(plain.className).toContain('text-[11px]')
  })
})
