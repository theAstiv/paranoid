import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/svelte'
import { get } from 'svelte/store'
import Review from './Review.svelte'

vi.mock('svelte-spa-router', () => ({
  link: () => ({ destroy: () => {} }),
}))

vi.mock('../lib/api.js', () => ({
  getModelThreats: vi.fn(),
  updateThreat: vi.fn(),
  bulkUpdateThreatStatus: vi.fn(),
  getCommentCounts: vi.fn(),
  exportUrl: vi.fn(() => '/api/export/x'),
}))

vi.mock('../lib/stores.js', async (importOriginal) => {
  const actual = await importOriginal()
  return { ...actual, notify: vi.fn() }
})

import { getModelThreats, updateThreat, bulkUpdateThreatStatus, getCommentCounts } from '../lib/api.js'
import { notify, threats, currentModel } from '../lib/stores.js'

function threat(overrides = {}) {
  return {
    id: 't1',
    name: 'SQL Injection',
    description: 'desc',
    stride_category: 'Tampering',
    status: 'pending',
    ...overrides,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  threats.set([])
  currentModel.set(null)
  getModelThreats.mockResolvedValue([])
  updateThreat.mockResolvedValue({})
  bulkUpdateThreatStatus.mockResolvedValue({ updated: 0 })
  getCommentCounts.mockResolvedValue([])
})

describe('Review — loading', () => {
  it('loads threats on mount', async () => {
    render(Review, { props: { params: { id: 'm1' } } })
    await waitFor(() => expect(getModelThreats).toHaveBeenCalledWith('m1'))
  })

  it('notifies on load failure', async () => {
    getModelThreats.mockRejectedValue(new Error('boom'))
    render(Review, { props: { params: { id: 'm1' } } })
    await waitFor(() => expect(notify).toHaveBeenCalledWith('error', expect.stringContaining('boom')))
  })

  it('shows an empty state when there are no threats', async () => {
    render(Review, { props: { params: { id: 'm1' } } })
    await waitFor(() => expect(screen.getByText('No threats.')).toBeInTheDocument())
  })

  it('shows the current model title when set', async () => {
    currentModel.set({ id: 'm1', title: 'Payments Service' })
    render(Review, { props: { params: { id: 'm1' } } })
    await waitFor(() => expect(screen.getByText('Payments Service')).toBeInTheDocument())
  })
})

describe('Review — filtering', () => {
  beforeEach(() => {
    getModelThreats.mockResolvedValue([
      threat({ id: 't1', name: 'Pending one', status: 'pending' }),
      threat({ id: 't2', name: 'Approved one', status: 'approved' }),
      threat({ id: 't3', name: 'Rejected one', status: 'rejected' }),
    ])
  })

  it('shows filter counts', async () => {
    render(Review, { props: { params: { id: 'm1' } } })
    await waitFor(() => expect(screen.getByText('Pending one')).toBeInTheDocument())
    expect(screen.getAllByText('(3)').length).toBeGreaterThanOrEqual(1)
  })

  it('filters to only pending threats', async () => {
    render(Review, { props: { params: { id: 'm1' } } })
    await waitFor(() => expect(screen.getByText('Pending one')).toBeInTheDocument())

    await fireEvent.click(screen.getByRole('button', { name: /^pending/ }))

    expect(screen.getByText('Pending one')).toBeInTheDocument()
    expect(screen.queryByText('Approved one')).toBeNull()
    expect(screen.queryByText('Rejected one')).toBeNull()
  })

  it('filters to only approved threats', async () => {
    render(Review, { props: { params: { id: 'm1' } } })
    await waitFor(() => expect(screen.getByText('Pending one')).toBeInTheDocument())

    await fireEvent.click(screen.getByRole('button', { name: /^approved/ }))

    expect(screen.getByText('Approved one')).toBeInTheDocument()
    expect(screen.queryByText('Pending one')).toBeNull()
  })
})

/** Open the collapsed "Filters" panel that holds category/source/sort/range controls. */
async function openFilters() {
  await fireEvent.click(screen.getByRole('button', { name: 'Filters' }))
}

/** Rendered threat names, in DOM order — used to assert sort results. */
function renderedNames(container) {
  return [...container.querySelectorAll('h3')].map(el => el.textContent.trim())
}

/** Per-card selection checkboxes, excluding the leading "Select all" checkbox. */
function cardCheckboxes() {
  return screen.getAllByRole('checkbox').slice(1)
}

describe('Review — category filter', () => {
  beforeEach(() => {
    getModelThreats.mockResolvedValue([
      threat({ id: 't1', name: 'Tamper one', stride_category: 'Tampering' }),
      threat({ id: 't2', name: 'Spoof one', stride_category: 'Spoofing' }),
      threat({ id: 't3', name: 'Dos one', stride_category: 'Denial of Service' }),
    ])
  })

  it('filters to a single STRIDE category', async () => {
    render(Review, { props: { params: { id: 'm1' } } })
    await waitFor(() => expect(screen.getByText('Tamper one')).toBeInTheDocument())

    await openFilters()
    await fireEvent.click(screen.getByRole('button', { name: 'Tampering' }))

    expect(screen.getByText('Tamper one')).toBeInTheDocument()
    expect(screen.queryByText('Spoof one')).toBeNull()
    expect(screen.queryByText('Dos one')).toBeNull()
  })

  it('accumulates multiple categories', async () => {
    render(Review, { props: { params: { id: 'm1' } } })
    await waitFor(() => expect(screen.getByText('Tamper one')).toBeInTheDocument())

    await openFilters()
    await fireEvent.click(screen.getByRole('button', { name: 'Tampering' }))
    await fireEvent.click(screen.getByRole('button', { name: 'Spoofing' }))

    expect(screen.getByText('Tamper one')).toBeInTheDocument()
    expect(screen.getByText('Spoof one')).toBeInTheDocument()
    expect(screen.queryByText('Dos one')).toBeNull()
  })

  it('deselecting the last category restores all threats', async () => {
    render(Review, { props: { params: { id: 'm1' } } })
    await waitFor(() => expect(screen.getByText('Tamper one')).toBeInTheDocument())

    await openFilters()
    await fireEvent.click(screen.getByRole('button', { name: 'Tampering' }))
    expect(screen.queryByText('Spoof one')).toBeNull()

    await fireEvent.click(screen.getByRole('button', { name: 'Tampering' }))

    expect(screen.getByText('Tamper one')).toBeInTheDocument()
    expect(screen.getByText('Spoof one')).toBeInTheDocument()
    expect(screen.getByText('Dos one')).toBeInTheDocument()
  })
})

describe('Review — source filter', () => {
  beforeEach(() => {
    getModelThreats.mockResolvedValue([
      threat({ id: 't1', name: 'From model', source: 'llm' }),
      threat({ id: 't2', name: 'From rules', source: 'rule_engine' }),
    ])
  })

  it('filters to LLM-sourced threats', async () => {
    render(Review, { props: { params: { id: 'm1' } } })
    await waitFor(() => expect(screen.getByText('From model')).toBeInTheDocument())

    await openFilters()
    await fireEvent.click(screen.getByRole('button', { name: 'LLM' }))

    expect(screen.getByText('From model')).toBeInTheDocument()
    expect(screen.queryByText('From rules')).toBeNull()
  })

  it('filters to rule-engine threats', async () => {
    render(Review, { props: { params: { id: 'm1' } } })
    await waitFor(() => expect(screen.getByText('From model')).toBeInTheDocument())

    await openFilters()
    await fireEvent.click(screen.getByRole('button', { name: 'Rule Engine' }))

    expect(screen.getByText('From rules')).toBeInTheDocument()
    expect(screen.queryByText('From model')).toBeNull()
  })

  it('returns to all sources when "All" is chosen again', async () => {
    render(Review, { props: { params: { id: 'm1' } } })
    await waitFor(() => expect(screen.getByText('From model')).toBeInTheDocument())

    await openFilters()
    await fireEvent.click(screen.getByRole('button', { name: 'LLM' }))
    await fireEvent.click(screen.getByRole('button', { name: 'All' }))

    expect(screen.getByText('From model')).toBeInTheDocument()
    expect(screen.getByText('From rules')).toBeInTheDocument()
  })
})

describe('Review — DREAD and confidence ranges', () => {
  it('filters out threats whose DREAD score falls outside the range', async () => {
    getModelThreats.mockResolvedValue([
      threat({ id: 't1', name: 'High risk', dread_score: 9 }),
      threat({ id: 't2', name: 'Low risk', dread_score: 2 }),
    ])
    render(Review, { props: { params: { id: 'm1' } } })
    await waitFor(() => expect(screen.getByText('High risk')).toBeInTheDocument())

    await openFilters()
    const [dreadMin] = screen.getAllByRole('spinbutton')
    await fireEvent.input(dreadMin, { target: { value: '8' } })

    expect(screen.getByText('High risk')).toBeInTheDocument()
    expect(screen.queryByText('Low risk')).toBeNull()
  })

  it('keeps threats that have no DREAD score at all', async () => {
    getModelThreats.mockResolvedValue([
      threat({ id: 't1', name: 'Scored', dread_score: 2 }),
      threat({ id: 't2', name: 'Unscored' }),
    ])
    render(Review, { props: { params: { id: 'm1' } } })
    await waitFor(() => expect(screen.getByText('Unscored')).toBeInTheDocument())

    await openFilters()
    const [dreadMin] = screen.getAllByRole('spinbutton')
    await fireEvent.input(dreadMin, { target: { value: '8' } })

    // Null-score threats pass through rather than being silently hidden.
    expect(screen.getByText('Unscored')).toBeInTheDocument()
    expect(screen.queryByText('Scored')).toBeNull()
  })

  it('filters out threats whose confidence falls outside the range', async () => {
    getModelThreats.mockResolvedValue([
      threat({ id: 't1', name: 'Confident', confidence: 0.9 }),
      threat({ id: 't2', name: 'Unsure', confidence: 0.2 }),
    ])
    render(Review, { props: { params: { id: 'm1' } } })
    await waitFor(() => expect(screen.getByText('Confident')).toBeInTheDocument())

    await openFilters()
    const confMin = screen.getAllByRole('spinbutton')[2]
    await fireEvent.input(confMin, { target: { value: '50' } })

    expect(screen.getByText('Confident')).toBeInTheDocument()
    expect(screen.queryByText('Unsure')).toBeNull()
  })

  it('keeps threats that have no confidence value at all', async () => {
    getModelThreats.mockResolvedValue([
      threat({ id: 't1', name: 'Unsure', confidence: 0.2 }),
      threat({ id: 't2', name: 'No confidence' }),
    ])
    render(Review, { props: { params: { id: 'm1' } } })
    await waitFor(() => expect(screen.getByText('No confidence')).toBeInTheDocument())

    await openFilters()
    const confMin = screen.getAllByRole('spinbutton')[2]
    await fireEvent.input(confMin, { target: { value: '50' } })

    expect(screen.getByText('No confidence')).toBeInTheDocument()
    expect(screen.queryByText('Unsure')).toBeNull()
  })
})

describe('Review — sorting', () => {
  it('sorts by DREAD score, highest first', async () => {
    getModelThreats.mockResolvedValue([
      threat({ id: 't1', name: 'Middle', dread_score: 5 }),
      threat({ id: 't2', name: 'Highest', dread_score: 9 }),
      threat({ id: 't3', name: 'Lowest', dread_score: 1 }),
    ])
    const { container } = render(Review, { props: { params: { id: 'm1' } } })
    await waitFor(() => expect(screen.getByText('Middle')).toBeInTheDocument())

    await openFilters()
    await fireEvent.change(screen.getByRole('combobox'), { target: { value: 'dread' } })

    expect(renderedNames(container)).toEqual(['Highest', 'Middle', 'Lowest'])
  })

  it('sorts by confidence, highest first', async () => {
    getModelThreats.mockResolvedValue([
      threat({ id: 't1', name: 'Middle', confidence: 0.5 }),
      threat({ id: 't2', name: 'Highest', confidence: 0.9 }),
      threat({ id: 't3', name: 'Lowest', confidence: 0.1 }),
    ])
    const { container } = render(Review, { props: { params: { id: 'm1' } } })
    await waitFor(() => expect(screen.getByText('Middle')).toBeInTheDocument())

    await openFilters()
    await fireEvent.change(screen.getByRole('combobox'), { target: { value: 'confidence' } })

    expect(renderedNames(container)).toEqual(['Highest', 'Middle', 'Lowest'])
  })

  it('sorts by category alphabetically', async () => {
    getModelThreats.mockResolvedValue([
      threat({ id: 't1', name: 'Tamper one', stride_category: 'Tampering' }),
      threat({ id: 't2', name: 'Dos one', stride_category: 'Denial of Service' }),
      threat({ id: 't3', name: 'Spoof one', stride_category: 'Spoofing' }),
    ])
    const { container } = render(Review, { props: { params: { id: 'm1' } } })
    await waitFor(() => expect(screen.getByText('Tamper one')).toBeInTheDocument())

    await openFilters()
    await fireEvent.change(screen.getByRole('combobox'), { target: { value: 'category' } })

    expect(renderedNames(container)).toEqual(['Dos one', 'Spoof one', 'Tamper one'])
  })

  it('preserves source order under the default sort', async () => {
    getModelThreats.mockResolvedValue([
      threat({ id: 't1', name: 'First', dread_score: 1 }),
      threat({ id: 't2', name: 'Second', dread_score: 9 }),
    ])
    const { container } = render(Review, { props: { params: { id: 'm1' } } })
    await waitFor(() => expect(screen.getByText('First')).toBeInTheDocument())

    expect(renderedNames(container)).toEqual(['First', 'Second'])
  })
})

describe('Review — selection', () => {
  beforeEach(() => {
    getModelThreats.mockResolvedValue([
      threat({ id: 't1', name: 'Pending one', status: 'pending' }),
      threat({ id: 't2', name: 'Approved one', status: 'approved' }),
    ])
  })

  it('selects every filtered threat via "Select all"', async () => {
    render(Review, { props: { params: { id: 'm1' } } })
    await waitFor(() => expect(screen.getByText('Pending one')).toBeInTheDocument())

    await fireEvent.click(screen.getByLabelText(/Select all/))

    expect(screen.getByText('2 of 2 selected')).toBeInTheDocument()
  })

  it('"Select all" only covers threats visible under the active filter', async () => {
    render(Review, { props: { params: { id: 'm1' } } })
    await waitFor(() => expect(screen.getByText('Pending one')).toBeInTheDocument())

    await fireEvent.click(screen.getByRole('button', { name: /^pending/ }))
    await fireEvent.click(screen.getByLabelText(/Select all/))

    expect(screen.getByText('1 of 1 selected')).toBeInTheDocument()
  })

  it('clicking "Select all" again clears the selection', async () => {
    render(Review, { props: { params: { id: 'm1' } } })
    await waitFor(() => expect(screen.getByText('Pending one')).toBeInTheDocument())

    await fireEvent.click(screen.getByLabelText(/Select all/))
    expect(screen.getByText('2 of 2 selected')).toBeInTheDocument()

    await fireEvent.click(screen.getByLabelText(/Select all/))

    expect(screen.queryByText(/selected/)).toBeNull()
  })

  it('"Clear selection" empties the selection bar', async () => {
    render(Review, { props: { params: { id: 'm1' } } })
    await waitFor(() => expect(screen.getByText('Pending one')).toBeInTheDocument())

    await fireEvent.click(screen.getByLabelText(/Select all/))
    await fireEvent.click(screen.getByText('Clear selection'))

    expect(screen.queryByText(/selected/)).toBeNull()
  })

  it('toggles an individual threat on and off', async () => {
    render(Review, { props: { params: { id: 'm1' } } })
    await waitFor(() => expect(screen.getByText('Pending one')).toBeInTheDocument())

    await fireEvent.click(cardCheckboxes()[0])
    expect(screen.getByText('1 of 2 selected')).toBeInTheDocument()

    await fireEvent.click(cardCheckboxes()[0])
    expect(screen.queryByText(/selected/)).toBeNull()
  })
})

describe('Review — selection pruning across filter changes', () => {
  beforeEach(() => {
    getModelThreats.mockResolvedValue([
      threat({ id: 't1', name: 'Pending one', status: 'pending' }),
      threat({ id: 't2', name: 'Approved one', status: 'approved' }),
      threat({ id: 't3', name: 'Rejected one', status: 'rejected' }),
    ])
  })

  it('drops now-hidden threats from the selection when a filter narrows', async () => {
    render(Review, { props: { params: { id: 'm1' } } })
    await waitFor(() => expect(screen.getByText('Pending one')).toBeInTheDocument())

    await fireEvent.click(screen.getByLabelText(/Select all/))
    expect(screen.getByText('3 of 3 selected')).toBeInTheDocument()

    await fireEvent.click(screen.getByRole('button', { name: /^pending/ }))

    expect(screen.getByText('1 of 1 selected')).toBeInTheDocument()
  })

  it('never bulk-applies to a threat hidden by the active filter', async () => {
    bulkUpdateThreatStatus.mockResolvedValue({ updated: 1 })
    render(Review, { props: { params: { id: 'm1' } } })
    await waitFor(() => expect(screen.getByText('Pending one')).toBeInTheDocument())

    await fireEvent.click(screen.getByLabelText(/Select all/))
    await fireEvent.click(screen.getByRole('button', { name: /^pending/ }))
    await fireEvent.click(screen.getByText('Approve selected (1)'))

    // t2/t3 were selected before the filter narrowed — they must not be touched.
    await waitFor(() => expect(bulkUpdateThreatStatus).toHaveBeenCalledWith(['t1'], 'approved'))
    expect(get(threats).find(t => t.id === 't2').status).toBe('approved')
    expect(get(threats).find(t => t.id === 't3').status).toBe('rejected')
  })

  it('restores a hidden selection when the filter widens again', async () => {
    render(Review, { props: { params: { id: 'm1' } } })
    await waitFor(() => expect(screen.getByText('Pending one')).toBeInTheDocument())

    await fireEvent.click(screen.getByLabelText(/Select all/))
    await fireEvent.click(screen.getByRole('button', { name: /^pending/ }))
    expect(screen.getByText('1 of 1 selected')).toBeInTheDocument()

    await fireEvent.click(screen.getByRole('button', { name: /^all/ }))

    // Narrowing a filter hides a selection rather than destroying it — the
    // safety rule is enforced by deriving from what is visible, so there is
    // no need to discard the rest.
    expect(screen.getByText('3 of 3 selected')).toBeInTheDocument()
  })

  it('clears the selection bar when the filter hides every selected threat', async () => {
    render(Review, { props: { params: { id: 'm1' } } })
    await waitFor(() => expect(screen.getByText('Pending one')).toBeInTheDocument())

    await fireEvent.click(cardCheckboxes()[0]) // 'Pending one'
    expect(screen.getByText('1 of 3 selected')).toBeInTheDocument()

    await fireEvent.click(screen.getByRole('button', { name: /^approved/ }))

    expect(screen.queryByText(/selected/)).toBeNull()
  })
})

describe('Review — individual approve/reject', () => {
  it('optimistically approves a threat and persists it', async () => {
    getModelThreats.mockResolvedValue([threat()])
    render(Review, { props: { params: { id: 'm1' } } })
    await waitFor(() => expect(screen.getByText('SQL Injection')).toBeInTheDocument())

    await fireEvent.click(screen.getByText('Approve'))

    await waitFor(() => expect(updateThreat).toHaveBeenCalledWith('t1', { status: 'approved' }))
    expect(get(threats)[0].status).toBe('approved')
  })

  it('rolls back on approve failure and notifies', async () => {
    getModelThreats.mockResolvedValue([threat()])
    updateThreat.mockRejectedValue(new Error('rejected by server'))
    render(Review, { props: { params: { id: 'm1' } } })
    await waitFor(() => expect(screen.getByText('SQL Injection')).toBeInTheDocument())

    await fireEvent.click(screen.getByText('Approve'))

    await waitFor(() => expect(notify).toHaveBeenCalledWith('error', expect.stringContaining('rejected by server')))
    expect(get(threats)[0].status).toBe('pending')
  })

  it('optimistically rejects a threat and persists it', async () => {
    getModelThreats.mockResolvedValue([threat()])
    render(Review, { props: { params: { id: 'm1' } } })
    await waitFor(() => expect(screen.getByText('SQL Injection')).toBeInTheDocument())

    await fireEvent.click(screen.getByText('Reject'))

    await waitFor(() => expect(updateThreat).toHaveBeenCalledWith('t1', { status: 'rejected' }))
    expect(get(threats)[0].status).toBe('rejected')
  })
})

describe('Review — bulk actions', () => {
  it('approves all pending threats', async () => {
    bulkUpdateThreatStatus.mockResolvedValue({ updated: 2 })
    getModelThreats.mockResolvedValue([
      threat({ id: 't1', name: 'One' }),
      threat({ id: 't2', name: 'Two' }),
    ])
    render(Review, { props: { params: { id: 'm1' } } })
    await waitFor(() => expect(screen.getByText(/Approve all/)).toBeInTheDocument())

    await fireEvent.click(screen.getByText('Approve all (2)'))

    await waitFor(() => expect(bulkUpdateThreatStatus).toHaveBeenCalledWith(['t1', 't2'], 'approved'))
    await waitFor(() => expect(notify).toHaveBeenCalledWith('success', 'Approved all: 2 threats'))
  })

  it('rejects all pending threats', async () => {
    bulkUpdateThreatStatus.mockResolvedValue({ updated: 2 })
    getModelThreats.mockResolvedValue([threat({ id: 't1' }), threat({ id: 't2' })])
    render(Review, { props: { params: { id: 'm1' } } })
    await waitFor(() => expect(screen.getByText('Reject all (2)')).toBeInTheDocument())

    await fireEvent.click(screen.getByText('Reject all (2)'))

    await waitFor(() => expect(bulkUpdateThreatStatus).toHaveBeenCalledWith(['t1', 't2'], 'rejected'))
    await waitFor(() => expect(notify).toHaveBeenCalledWith('success', 'Rejected all: 2 threats'))
  })

  it('rolls back all optimistic updates on bulk failure', async () => {
    getModelThreats.mockResolvedValue([threat({ id: 't1' }), threat({ id: 't2' })])
    bulkUpdateThreatStatus.mockRejectedValue(new Error('network down'))
    render(Review, { props: { params: { id: 'm1' } } })
    await waitFor(() => expect(screen.getByText('Approve all (2)')).toBeInTheDocument())

    await fireEvent.click(screen.getByText('Approve all (2)'))

    await waitFor(() =>
      expect(notify).toHaveBeenCalledWith('error', expect.stringContaining('network down'))
    )
    expect(get(threats).every(t => t.status === 'pending')).toBe(true)
  })

  it('shows and applies "Approve Critical+High" only for high-severity pending threats', async () => {
    bulkUpdateThreatStatus.mockResolvedValue({ updated: 1 })
    getModelThreats.mockResolvedValue([
      threat({ id: 't1', name: 'Critical one', dread_score: 9 }),
      threat({ id: 't2', name: 'Low one', dread_score: 2 }),
    ])
    render(Review, { props: { params: { id: 'm1' } } })
    await waitFor(() => expect(screen.getByText(/Approve Critical\+High/)).toBeInTheDocument())

    await fireEvent.click(screen.getByText('Approve Critical+High (1)'))

    await waitFor(() => expect(bulkUpdateThreatStatus).toHaveBeenCalledWith(['t1'], 'approved'))
    expect(get(threats).find(t => t.id === 't2').status).toBe('pending')
  })

  it('shows and applies "Reject Low" only for low-severity pending threats', async () => {
    bulkUpdateThreatStatus.mockResolvedValue({ updated: 1 })
    getModelThreats.mockResolvedValue([
      threat({ id: 't1', name: 'Critical one', dread_score: 9 }),
      threat({ id: 't2', name: 'Low one', dread_score: 2 }),
    ])
    render(Review, { props: { params: { id: 'm1' } } })
    await waitFor(() => expect(screen.getByText(/Reject Low/)).toBeInTheDocument())

    await fireEvent.click(screen.getByText('Reject Low (1)'))

    await waitFor(() => expect(bulkUpdateThreatStatus).toHaveBeenCalledWith(['t2'], 'rejected'))
    expect(get(threats).find(t => t.id === 't1').status).toBe('pending')
  })

  it('hides bulk-action buttons when there are no pending threats', async () => {
    getModelThreats.mockResolvedValue([threat({ id: 't1', status: 'approved' })])
    render(Review, { props: { params: { id: 'm1' } } })
    await waitFor(() => expect(screen.getByText('SQL Injection')).toBeInTheDocument())
    expect(screen.queryByText(/Approve all/)).toBeNull()
    expect(screen.queryByText(/Reject all/)).toBeNull()
  })
})
