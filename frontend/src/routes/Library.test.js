import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/svelte'
import Library from './Library.svelte'

vi.mock('svelte-spa-router', () => ({
  link: () => ({ destroy: () => {} }),
}))

vi.mock('../lib/api.js', () => ({
  listModels: vi.fn(),
  getModelThreats: vi.fn(),
  deleteModel: vi.fn(),
  updateThreat: vi.fn(),
}))

vi.mock('../lib/stores.js', async (importOriginal) => {
  const actual = await importOriginal()
  return { ...actual, notify: vi.fn() }
})

import { listModels, getModelThreats, deleteModel } from '../lib/api.js'
import { notify } from '../lib/stores.js'

const modelA = { id: 'm1', title: 'API Gateway', framework: 'STRIDE', threat_count: 2 }
const threatA = { id: 't1', name: 'SQL Injection', description: 'desc', status: 'pending', impact: 'High', stride_category: 'Tampering' }
const threatB = { id: 't2', name: 'XSS', description: 'desc2', status: 'approved', impact: 'Low', stride_category: 'Spoofing' }

beforeEach(() => {
  vi.clearAllMocks()
  listModels.mockResolvedValue([])
})

describe('Library — loading', () => {
  it('loads models on mount', async () => {
    render(Library)
    await waitFor(() => expect(listModels).toHaveBeenCalledWith({ limit: 50 }))
  })

  it('notifies on load failure', async () => {
    listModels.mockRejectedValue(new Error('boom'))
    render(Library)
    await waitFor(() => expect(notify).toHaveBeenCalledWith('error', expect.stringContaining('boom')))
  })

  it('shows an empty state when there are no models', async () => {
    render(Library)
    await waitFor(() => expect(screen.getByText('No threat models yet.')).toBeInTheDocument())
  })
})

describe('Library — model rows', () => {
  beforeEach(() => {
    listModels.mockResolvedValue([modelA])
  })

  it('renders the model title, framework, and threat count', async () => {
    render(Library)
    await waitFor(() => expect(screen.getByText('API Gateway')).toBeInTheDocument())
    expect(screen.getByText('STRIDE')).toBeInTheDocument()
    expect(screen.getByText('2 threats')).toBeInTheDocument()
  })

  it('expands a model and loads its threats', async () => {
    getModelThreats.mockResolvedValue([threatA, threatB])
    render(Library)
    await waitFor(() => expect(screen.getByText('API Gateway')).toBeInTheDocument())

    await fireEvent.click(screen.getByText('API Gateway'))

    await waitFor(() => expect(getModelThreats).toHaveBeenCalledWith('m1'))
    await waitFor(() => expect(screen.getByText('SQL Injection')).toBeInTheDocument())
    expect(screen.getByText('XSS')).toBeInTheDocument()
  })

  it('collapses an expanded model on second click without re-fetching', async () => {
    getModelThreats.mockResolvedValue([threatA])
    render(Library)
    await waitFor(() => expect(screen.getByText('API Gateway')).toBeInTheDocument())

    await fireEvent.click(screen.getByText('API Gateway'))
    await waitFor(() => expect(screen.getByText('SQL Injection')).toBeInTheDocument())

    await fireEvent.click(screen.getByText('API Gateway'))
    expect(screen.queryByText('SQL Injection')).toBeNull()

    await fireEvent.click(screen.getByText('API Gateway'))
    expect(getModelThreats).toHaveBeenCalledTimes(1)
  })

  it('notifies when loading threats fails', async () => {
    getModelThreats.mockRejectedValue(new Error('threats down'))
    render(Library)
    await waitFor(() => expect(screen.getByText('API Gateway')).toBeInTheDocument())

    await fireEvent.click(screen.getByText('API Gateway'))

    await waitFor(() => expect(notify).toHaveBeenCalledWith('error', expect.stringContaining('threats down')))
  })
})

describe('Library — filtering within an expanded model', () => {
  beforeEach(async () => {
    listModels.mockResolvedValue([modelA])
    getModelThreats.mockResolvedValue([threatA, threatB])
  })

  it('filters threats by search query', async () => {
    render(Library)
    await waitFor(() => expect(screen.getByText('API Gateway')).toBeInTheDocument())
    await fireEvent.click(screen.getByText('API Gateway'))
    await waitFor(() => expect(screen.getByText('SQL Injection')).toBeInTheDocument())

    await fireEvent.input(screen.getByLabelText('Search threats'), { target: { value: 'xss' } })

    expect(screen.getByText('XSS')).toBeInTheDocument()
    expect(screen.queryByText('SQL Injection')).toBeNull()
  })

  it('filters threats by impact', async () => {
    render(Library)
    await waitFor(() => expect(screen.getByText('API Gateway')).toBeInTheDocument())
    await fireEvent.click(screen.getByText('API Gateway'))
    await waitFor(() => expect(screen.getByText('SQL Injection')).toBeInTheDocument())

    await fireEvent.change(screen.getByLabelText('Filter by impact'), { target: { value: 'Low' } })

    expect(screen.getByText('XSS')).toBeInTheDocument()
    expect(screen.queryByText('SQL Injection')).toBeNull()
  })

  it('filters threats by status', async () => {
    render(Library)
    await waitFor(() => expect(screen.getByText('API Gateway')).toBeInTheDocument())
    await fireEvent.click(screen.getByText('API Gateway'))
    await waitFor(() => expect(screen.getByText('SQL Injection')).toBeInTheDocument())

    await fireEvent.change(screen.getByLabelText('Filter by status'), { target: { value: 'approved' } })

    expect(screen.getByText('XSS')).toBeInTheDocument()
    expect(screen.queryByText('SQL Injection')).toBeNull()
  })

  it('shows a no-match message when filters exclude everything', async () => {
    render(Library)
    await waitFor(() => expect(screen.getByText('API Gateway')).toBeInTheDocument())
    await fireEvent.click(screen.getByText('API Gateway'))
    await waitFor(() => expect(screen.getByText('SQL Injection')).toBeInTheDocument())

    await fireEvent.input(screen.getByLabelText('Search threats'), { target: { value: 'nonexistent' } })

    expect(screen.getByText('No threats match the current filters.')).toBeInTheDocument()
  })
})

describe('Library — delete', () => {
  beforeEach(() => {
    listModels.mockResolvedValue([modelA])
  })

  it('deletes a model after confirmation without expanding it', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    deleteModel.mockResolvedValue(null)
    render(Library)
    await waitFor(() => expect(screen.getByText('API Gateway')).toBeInTheDocument())

    await fireEvent.click(screen.getByTitle('Delete threat model'))

    await waitFor(() => expect(deleteModel).toHaveBeenCalledWith('m1'))
    await waitFor(() => expect(notify).toHaveBeenCalledWith('success', 'Threat model deleted.'))
    expect(getModelThreats).not.toHaveBeenCalled()
  })

  it('does not delete when confirmation is dismissed', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    render(Library)
    await waitFor(() => expect(screen.getByText('API Gateway')).toBeInTheDocument())

    await fireEvent.click(screen.getByTitle('Delete threat model'))

    expect(deleteModel).not.toHaveBeenCalled()
  })

  it('notifies on delete failure', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    deleteModel.mockRejectedValue(new Error('forbidden'))
    render(Library)
    await waitFor(() => expect(screen.getByText('API Gateway')).toBeInTheDocument())

    await fireEvent.click(screen.getByTitle('Delete threat model'))

    await waitFor(() => expect(notify).toHaveBeenCalledWith('error', expect.stringContaining('forbidden')))
  })
})
