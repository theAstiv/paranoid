import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/svelte'
import Results from './Results.svelte'

vi.mock('svelte-spa-router', () => ({
  link: () => ({ destroy: () => {} }),
}))

vi.mock('../lib/api.js', () => ({
  getModel: vi.fn(),
  updateModel: vi.fn(),
  getModelAssets: vi.fn(),
  getModelFlows: vi.fn(),
  getModelTrustBoundaries: vi.fn(),
  createAsset: vi.fn(),
  updateAsset: vi.fn(),
  deleteAsset: vi.fn(),
  createFlow: vi.fn(),
  updateFlow: vi.fn(),
  deleteFlow: vi.fn(),
  createTrustBoundary: vi.fn(),
  updateTrustBoundary: vi.fn(),
  deleteTrustBoundary: vi.fn(),
  subscribeToRun: vi.fn(() => vi.fn()),
  exportUrl: vi.fn(() => '/api/export/x'),
  // Transitively required by child components (Assignees, Comments)
  listAssignees: vi.fn().mockResolvedValue([]),
  addAssignee: vi.fn(),
  removeAssignee: vi.fn(),
  listProjectMembers: vi.fn().mockResolvedValue([]),
  listComments: vi.fn().mockResolvedValue([]),
  createComment: vi.fn(),
  updateComment: vi.fn(),
  deleteComment: vi.fn(),
}))

vi.mock('../lib/stores.js', async (importOriginal) => {
  const actual = await importOriginal()
  return { ...actual, notify: vi.fn() }
})

import {
  getModel, updateModel, getModelAssets, getModelFlows, getModelTrustBoundaries, subscribeToRun,
} from '../lib/api.js'
import {
  notify, currentModel, threats, pipelineEvents, pipelineRunning, abortRun, config, currentUser,
} from '../lib/stores.js'

const baseModel = {
  id: 'm1',
  title: 'Payments Service',
  status: 'completed',
  framework: 'STRIDE',
  project_id: 'p1',
  iteration_count: 3,
  gap_summaries: [],
  threats: [],
}

beforeEach(() => {
  vi.clearAllMocks()
  currentModel.set(null)
  threats.set([])
  pipelineEvents.set([])
  pipelineRunning.set(false)
  abortRun.set(null)
  config.set(null)
  currentUser.set(null)
  getModel.mockResolvedValue(baseModel)
  getModelAssets.mockResolvedValue([])
  getModelFlows.mockResolvedValue([])
  getModelTrustBoundaries.mockResolvedValue([])
})

describe('Results — loading', () => {
  it('loads the model on mount and renders its title', async () => {
    render(Results, { props: { params: { id: 'm1' } } })
    await waitFor(() => expect(getModel).toHaveBeenCalledWith('m1'))
    await waitFor(() => expect(screen.getByText('Payments Service')).toBeInTheDocument())
  })

  it('notifies on load failure', async () => {
    getModel.mockRejectedValue(new Error('not found'))
    render(Results, { props: { params: { id: 'm1' } } })
    await waitFor(() => expect(notify).toHaveBeenCalledWith('error', expect.stringContaining('not found')))
  })

  it('loads supplementary assets/flows/boundaries for a completed model', async () => {
    render(Results, { props: { params: { id: 'm1' } } })
    await waitFor(() => expect(getModelAssets).toHaveBeenCalledWith('m1'))
    expect(getModelFlows).toHaveBeenCalledWith('m1')
    expect(getModelTrustBoundaries).toHaveBeenCalledWith('m1')
  })
})

describe('Results — header', () => {
  it('shows the status chip and framework', async () => {
    render(Results, { props: { params: { id: 'm1' } } })
    await waitFor(() => expect(screen.getByText('completed')).toBeInTheDocument())
    expect(screen.getByText('STRIDE')).toBeInTheDocument()
  })

  it('shows a Re-run button for a completed model and triggers subscribeToRun', async () => {
    render(Results, { props: { params: { id: 'm1' } } })
    await waitFor(() => expect(screen.getByText('Re-run')).toBeInTheDocument())

    await fireEvent.click(screen.getByText('Re-run'))

    expect(subscribeToRun).toHaveBeenCalled()
    expect(subscribeToRun.mock.calls[0][0]).toBe('m1')
  })

  it('blocks re-run and notifies when the configured provider has no API key', async () => {
    config.set({ default_provider: 'anthropic', anthropic_api_key_set: false })
    getModel.mockResolvedValue({ ...baseModel, provider: 'anthropic' })
    render(Results, { props: { params: { id: 'm1' } } })
    await waitFor(() => expect(screen.getByText('Re-run')).toBeInTheDocument())

    await fireEvent.click(screen.getByText('Re-run'))

    expect(subscribeToRun).not.toHaveBeenCalled()
    expect(notify).toHaveBeenCalledWith('error', expect.stringContaining('No API key configured'))
  })

  it('shows a "Review Threats" link only for a completed model', async () => {
    render(Results, { props: { params: { id: 'm1' } } })
    await waitFor(() => expect(screen.getByText('Review Threats')).toBeInTheDocument())
  })

  it('does not show "Review Threats" for a pending model', async () => {
    getModel.mockResolvedValue({ ...baseModel, status: 'pending' })
    render(Results, { props: { params: { id: 'm1' } } })
    await waitFor(() => expect(screen.getByText('pending')).toBeInTheDocument())
    expect(screen.queryByText('Review Threats')).toBeNull()
  })
})

describe('Results — status workflow actions', () => {
  it('shows "Send to review" for a completed model and transitions on click', async () => {
    const updated = { ...baseModel, status: 'in_review' }
    updateModel.mockResolvedValue(updated)
    render(Results, { props: { params: { id: 'm1' } } })
    await waitFor(() => expect(screen.getByText('Send to review')).toBeInTheDocument())

    await fireEvent.click(screen.getByText('Send to review'))

    await waitFor(() => expect(updateModel).toHaveBeenCalledWith('m1', { status: 'in_review' }))
    await waitFor(() => expect(screen.getByText('in review')).toBeInTheDocument())
  })

  it('shows Approve/Back/Archive for an in_review model', async () => {
    getModel.mockResolvedValue({ ...baseModel, status: 'in_review' })
    render(Results, { props: { params: { id: 'm1' } } })
    await waitFor(() => expect(screen.getByText('Approve')).toBeInTheDocument())
    expect(screen.getByText('Back to completed')).toBeInTheDocument()
    expect(screen.getByText('Archive')).toBeInTheDocument()
  })

  it('notifies on a failed status change', async () => {
    updateModel.mockRejectedValue(new Error('forbidden'))
    render(Results, { props: { params: { id: 'm1' } } })
    await waitFor(() => expect(screen.getByText('Send to review')).toBeInTheDocument())

    await fireEvent.click(screen.getByText('Send to review'))

    await waitFor(() => expect(notify).toHaveBeenCalledWith('error', expect.stringContaining('forbidden')))
  })

  it('shows no status actions for a pending model', async () => {
    getModel.mockResolvedValue({ ...baseModel, status: 'pending' })
    render(Results, { props: { params: { id: 'm1' } } })
    await waitFor(() => expect(screen.getByText('pending')).toBeInTheDocument())
    expect(screen.queryByText('Send to review')).toBeNull()
    expect(screen.queryByText('Approve')).toBeNull()
  })
})

describe('Results — threats and resource panels', () => {
  it('shows the threat summary with up to 5 threats and a "+N more" line', async () => {
    const many = Array.from({ length: 7 }, (_, i) => ({ id: `t${i}`, name: `Threat ${i}`, stride_category: 'Spoofing' }))
    getModel.mockResolvedValue({ ...baseModel, threats: many })
    render(Results, { props: { params: { id: 'm1' } } })
    await waitFor(() => expect(screen.getByText('7 Threats')).toBeInTheDocument())
    expect(screen.getByText('Threat 0')).toBeInTheDocument()
    expect(screen.queryByText('Threat 6')).toBeNull()
    expect(screen.getByText('+2 more')).toBeInTheDocument()
  })

  it('does not show the threat summary when there are no threats', async () => {
    render(Results, { props: { params: { id: 'm1' } } })
    await waitFor(() => expect(screen.getByText('Payments Service')).toBeInTheDocument())
    expect(screen.queryByText(/^\d+ Threats$/)).toBeNull()
  })

  it('renders empty-state labels for assets, flows, and trust boundaries', async () => {
    render(Results, { props: { params: { id: 'm1' } } })
    await waitFor(() => expect(screen.getByText('No assets yet.')).toBeInTheDocument())
    expect(screen.getByText('No data flows yet.')).toBeInTheDocument()
    expect(screen.getByText('No trust boundaries yet.')).toBeInTheDocument()
  })

  it('shows the gap-satisfied message when threats exist but there are no gap summaries', async () => {
    getModel.mockResolvedValue({ ...baseModel, threats: [{ id: 't1', name: 'X' }], gap_summaries: [] })
    render(Results, { props: { params: { id: 'm1' } } })
    await waitFor(() =>
      expect(screen.getByText(/coverage was sufficient after iteration 1/)).toBeInTheDocument()
    )
  })

  it('renders per-iteration gap analysis when gap_summaries are present', async () => {
    getModel.mockResolvedValue({ ...baseModel, gap_summaries: ['Missing auth coverage', 'Missing DoS coverage'] })
    render(Results, { props: { params: { id: 'm1' } } })
    await waitFor(() => expect(screen.getByText('Missing auth coverage')).toBeInTheDocument())
    expect(screen.getByText('Missing DoS coverage')).toBeInTheDocument()
  })
})

describe('Results — code analysis panel', () => {
  it('renders code analysis when the model has a code_summary', async () => {
    getModel.mockResolvedValue({
      ...baseModel,
      code_summary: {
        tech_stack: ['Python', 'FastAPI'],
        auth_patterns: ['JWT'],
        entry_points: ['GET /api/models'],
        security_observations: ['CRITICAL: hardcoded secret'],
      },
    })
    render(Results, { props: { params: { id: 'm1' } } })
    await waitFor(() => expect(screen.getByText('Code Analysis')).toBeInTheDocument())
    expect(screen.getByText('Python')).toBeInTheDocument()
    expect(screen.getByText('JWT')).toBeInTheDocument()
    expect(screen.getByText('/api/models')).toBeInTheDocument()
    expect(screen.getByText('CRITICAL: hardcoded secret')).toBeInTheDocument()
  })

  it('omits the code analysis panel when there is no code_summary', async () => {
    render(Results, { props: { params: { id: 'm1' } } })
    await waitFor(() => expect(screen.getByText('Payments Service')).toBeInTheDocument())
    expect(screen.queryByText('Code Analysis')).toBeNull()
  })
})
