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
