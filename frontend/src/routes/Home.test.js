import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/svelte'
import { get } from 'svelte/store'
import Home from './Home.svelte'

vi.mock('svelte-spa-router', () => ({
  link: () => ({ destroy: () => {} }),
}))

vi.mock('../lib/api.js', () => ({
  listModels: vi.fn(),
  deleteModel: vi.fn(),
}))

vi.mock('../lib/stores.js', async (importOriginal) => {
  const actual = await importOriginal()
  return { ...actual, notify: vi.fn() }
})

import { listModels, deleteModel } from '../lib/api.js'
import { models, currentProject, notify } from '../lib/stores.js'

const modelA = {
  id: 'm1', title: 'API Gateway', framework: 'STRIDE', status: 'completed',
  threat_count: 3, created_at: '2026-01-01T00:00:00.000Z',
}
const modelB = {
  id: 'm2', title: 'Payments', framework: 'MAESTRO', status: 'pending',
  threat_count: 0, created_at: '2026-01-02T00:00:00.000Z',
}

beforeEach(() => {
  vi.clearAllMocks()
  models.set([])
  currentProject.set(null)
  listModels.mockResolvedValue([])
})

describe('Home — loading and empty states', () => {
  it('loads models on mount', async () => {
    render(Home)
    await waitFor(() => expect(listModels).toHaveBeenCalledWith({ limit: 50, project_id: undefined }))
  })

  it('shows the empty state when there are no models', async () => {
    render(Home)
    await waitFor(() => expect(screen.getByText('No threat models yet.')).toBeInTheDocument())
  })

  it('notifies on load failure', async () => {
    listModels.mockRejectedValue(new Error('server unreachable'))
    render(Home)
    await waitFor(() =>
      expect(notify).toHaveBeenCalledWith('error', expect.stringContaining('server unreachable'))
    )
  })

  it('reloads models when the current project changes', async () => {
    render(Home)
    await waitFor(() => expect(listModels).toHaveBeenCalledTimes(1))

    currentProject.set({ id: 'proj-1' })
    await waitFor(() => expect(listModels).toHaveBeenCalledTimes(2))
    expect(listModels).toHaveBeenLastCalledWith({ limit: 50, project_id: 'proj-1' })
  })
})

describe('Home — rendering models', () => {
  it('renders a card per model and the model count header', async () => {
    listModels.mockResolvedValue([modelA, modelB])
    render(Home)
    await waitFor(() => expect(screen.getByText('API Gateway')).toBeInTheDocument())
    expect(screen.getByText('Payments')).toBeInTheDocument()
    expect(screen.getByText('2 models')).toBeInTheDocument()
  })

  it('uses singular "model" label for exactly one model', async () => {
    listModels.mockResolvedValue([modelA])
    render(Home)
    await waitFor(() => expect(screen.getByText('1 model')).toBeInTheDocument())
  })
})

describe('Home — filtering', () => {
  beforeEach(() => {
    listModels.mockResolvedValue([modelA, modelB])
  })

  it('shows status and framework filter chips with counts', async () => {
    render(Home)
    await waitFor(() => expect(screen.getByText('API Gateway')).toBeInTheDocument())
    expect(screen.getByRole('button', { name: /completed/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /pending/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /STRIDE/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /MAESTRO/ })).toBeInTheDocument()
  })

  it('filters the list by status when a status chip is clicked', async () => {
    render(Home)
    await waitFor(() => expect(screen.getByText('API Gateway')).toBeInTheDocument())

    await fireEvent.click(screen.getByRole('button', { name: /completed/ }))

    expect(screen.getByText('API Gateway')).toBeInTheDocument()
    expect(screen.queryByText('Payments')).toBeNull()
  })

  it('filters the list by framework when a framework chip is clicked', async () => {
    render(Home)
    await waitFor(() => expect(screen.getByText('API Gateway')).toBeInTheDocument())

    await fireEvent.click(screen.getByRole('button', { name: /MAESTRO/ }))

    expect(screen.getByText('Payments')).toBeInTheDocument()
    expect(screen.queryByText('API Gateway')).toBeNull()
  })

  it('shows a filter-empty state when no models match, with a clear-filters action', async () => {
    render(Home)
    await waitFor(() => expect(screen.getByText('API Gateway')).toBeInTheDocument())

    await fireEvent.click(screen.getByRole('button', { name: /completed/ }))
    await fireEvent.click(screen.getByRole('button', { name: /MAESTRO/ }))

    expect(screen.getByText('No models match the current filters.')).toBeInTheDocument()
    await fireEvent.click(screen.getByText('Clear filters'))
    expect(screen.getByText('API Gateway')).toBeInTheDocument()
    expect(screen.getByText('Payments')).toBeInTheDocument()
  })

  it('toggles a filter off when the same chip is clicked again', async () => {
    render(Home)
    await waitFor(() => expect(screen.getByText('API Gateway')).toBeInTheDocument())

    await fireEvent.click(screen.getByRole('button', { name: /completed/ }))
    expect(screen.queryByText('Payments')).toBeNull()

    await fireEvent.click(screen.getByRole('button', { name: /completed/ }))
    expect(screen.getByText('Payments')).toBeInTheDocument()
  })

  it('shows a "clear ×" chip only when a filter is active', async () => {
    render(Home)
    await waitFor(() => expect(screen.getByText('API Gateway')).toBeInTheDocument())
    expect(screen.queryByText('clear ×')).toBeNull()

    await fireEvent.click(screen.getByRole('button', { name: /completed/ }))
    expect(screen.getByText('clear ×')).toBeInTheDocument()
  })
})

describe('Home — delete', () => {
  it('deletes a model after confirmation and shows a success notification', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    listModels.mockResolvedValue([modelA])
    deleteModel.mockResolvedValue(null)
    render(Home)
    await waitFor(() => expect(screen.getByText('API Gateway')).toBeInTheDocument())

    await fireEvent.click(screen.getByTitle('Delete threat model'))

    await waitFor(() => expect(deleteModel).toHaveBeenCalledWith('m1'))
    expect(notify).toHaveBeenCalledWith('success', 'Threat model deleted.')
    expect(get(models)).toEqual([])
  })

  it('does not delete when the confirmation is dismissed', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    listModels.mockResolvedValue([modelA])
    render(Home)
    await waitFor(() => expect(screen.getByText('API Gateway')).toBeInTheDocument())

    await fireEvent.click(screen.getByTitle('Delete threat model'))

    expect(deleteModel).not.toHaveBeenCalled()
    expect(screen.getByText('API Gateway')).toBeInTheDocument()
  })

  it('notifies on delete failure', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    listModels.mockResolvedValue([modelA])
    deleteModel.mockRejectedValue(new Error('forbidden'))
    render(Home)
    await waitFor(() => expect(screen.getByText('API Gateway')).toBeInTheDocument())

    await fireEvent.click(screen.getByTitle('Delete threat model'))

    await waitFor(() => expect(notify).toHaveBeenCalledWith('error', expect.stringContaining('forbidden')))
  })
})
