import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/svelte'
import { get } from 'svelte/store'
import NewModel from './NewModel.svelte'

vi.mock('svelte-spa-router', () => ({
  link: () => ({ destroy: () => {} }),
  push: vi.fn(),
}))

vi.mock('../lib/api.js', () => ({
  createModel: vi.fn(),
  subscribeToRun: vi.fn(() => vi.fn()),
  listCodeSources: vi.fn(),
  analyzeBundle: vi.fn(),
  getModel: vi.fn(),
}))

vi.mock('../lib/stores.js', async (importOriginal) => {
  const actual = await importOriginal()
  return { ...actual, notify: vi.fn() }
})

import { push } from 'svelte-spa-router'
import { createModel, subscribeToRun, listCodeSources } from '../lib/api.js'
import { notify, config, currentProject, pipelineRunning } from '../lib/stores.js'

async function goToStep(n) {
  for (let i = 0; i < n; i++) {
    await fireEvent.click(screen.getByText('Next'))
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  config.set(null)
  currentProject.set(null)
  pipelineRunning.set(false)
  listCodeSources.mockResolvedValue([])
})

describe('NewModel — step 0 (title & framework)', () => {
  it('disables Next until a title is entered', async () => {
    render(NewModel)
    expect(screen.getByText('Next')).toBeDisabled()
    await fireEvent.input(screen.getByLabelText('Model title'), { target: { value: 'My System' } })
    expect(screen.getByText('Next')).not.toBeDisabled()
  })

  it('defaults to STRIDE and shows its category description', () => {
    render(NewModel)
    expect(screen.getByText(/Spoofing, Tampering, Repudiation/)).toBeInTheDocument()
  })

  it('switches the framework description when MAESTRO is selected', async () => {
    render(NewModel)
    await fireEvent.click(screen.getByRole('radio', { name: 'MAESTRO' }))
    expect(screen.getByText(/AI\/ML-specific: Model Security/)).toBeInTheDocument()
  })
})

describe('NewModel — step 1 (description)', () => {
  it('disables Next until at least 10 characters are entered', async () => {
    render(NewModel)
    await fireEvent.input(screen.getByLabelText('Model title'), { target: { value: 'Sys' } })
    await fireEvent.click(screen.getByText('Next'))
    expect(screen.getByText('Next')).toBeDisabled()

    await fireEvent.input(screen.getByLabelText('System description'), { target: { value: 'short' } })
    expect(screen.getByText('Next')).toBeDisabled()

    await fireEvent.input(screen.getByLabelText('System description'), { target: { value: 'a valid description here' } })
    expect(screen.getByText('Next')).not.toBeDisabled()
  })

  it('flags coverage gaps for a long description missing key topics', async () => {
    render(NewModel)
    await fireEvent.click(screen.getByText('Next'))
    const longButVague = 'x'.repeat(85)
    await fireEvent.input(screen.getByLabelText('System description'), { target: { value: longButVague } })
    expect(screen.getByText('Coverage gaps detected — consider adding:')).toBeInTheDocument()
    expect(screen.getByText(/No auth mechanism mentioned/)).toBeInTheDocument()
  })

  it('shows "looks complete" when the description covers auth, boundaries, flows, and external systems', async () => {
    render(NewModel)
    await fireEvent.click(screen.getByText('Next'))
    const good = 'The internet-facing API gateway sends requests to an internal auth service using OAuth tokens, then stores data in an external database.'
    await fireEvent.input(screen.getByLabelText('System description'), { target: { value: good } })
    expect(screen.getByText('Description looks complete')).toBeInTheDocument()
  })
})

describe('NewModel — step 3 (code source)', () => {
  it('loads and lists ready code sources when the step is reached', async () => {
    listCodeSources.mockResolvedValue([
      { id: 'src-1', name: 'backend-repo', git_url: 'https://github.com/x/y', last_index_status: 'ready' },
      { id: 'src-2', name: 'not-ready-repo', git_url: 'https://github.com/x/z', last_index_status: 'indexing' },
    ])
    render(NewModel)
    await fireEvent.input(screen.getByLabelText('Model title'), { target: { value: 'Sys' } })
    await goToStep(3)

    await waitFor(() => expect(listCodeSources).toHaveBeenCalled())
    expect(screen.getByText('backend-repo')).toBeInTheDocument()
    expect(screen.queryByText('not-ready-repo')).toBeNull()
  })

  it('shows an empty state when there are no ready sources', async () => {
    render(NewModel)
    await fireEvent.input(screen.getByLabelText('Model title'), { target: { value: 'Sys' } })
    await goToStep(3)
    await waitFor(() => expect(screen.getByText('No indexed sources available.')).toBeInTheDocument())
  })
})

describe('NewModel — step 4 (assumptions)', () => {
  async function toStep4() {
    render(NewModel)
    await fireEvent.input(screen.getByLabelText('Model title'), { target: { value: 'Sys' } })
    await goToStep(4)
  }

  it('adds an assumption to the list', async () => {
    await toStep4()
    await fireEvent.input(screen.getByPlaceholderText(/TLS 1.3 enforced/), { target: { value: 'MFA required for admins' } })
    await fireEvent.click(screen.getByText('Add'))
    expect(screen.getByText('MFA required for admins')).toBeInTheDocument()
  })

  it('adds an assumption on Enter key', async () => {
    await toStep4()
    const input = screen.getByPlaceholderText(/TLS 1.3 enforced/)
    await fireEvent.input(input, { target: { value: 'Rate limiting enabled' } })
    await fireEvent.keyDown(input, { key: 'Enter' })
    expect(screen.getByText('Rate limiting enabled')).toBeInTheDocument()
  })

  it('removes an assumption', async () => {
    await toStep4()
    await fireEvent.input(screen.getByPlaceholderText(/TLS 1.3 enforced/), { target: { value: 'Temp assumption' } })
    await fireEvent.click(screen.getByText('Add'))
    expect(screen.getByText('Temp assumption')).toBeInTheDocument()

    const [removeBtn] = screen.getAllByRole('button').filter(b => b.closest('li'))
    await fireEvent.click(removeBtn)
    expect(screen.queryByText('Temp assumption')).toBeNull()
  })
})

describe('NewModel — step 5 (iterations)', () => {
  it('defaults to 3 iterations and updates the label when changed', async () => {
    render(NewModel)
    await fireEvent.input(screen.getByLabelText('Model title'), { target: { value: 'Sys' } })
    await goToStep(5)
    expect(screen.getByText('3', { selector: 'span' })).toBeInTheDocument()

    const slider = screen.getByLabelText(/Iteration count/)
    await fireEvent.input(slider, { target: { value: '10' } })
    expect(screen.getByText('10', { selector: 'span' })).toBeInTheDocument()
  })
})

describe('NewModel — step 6 (AI components)', () => {
  it('shows a checkbox for STRIDE and toggles hasAiComponents', async () => {
    render(NewModel)
    await fireEvent.input(screen.getByLabelText('Model title'), { target: { value: 'Sys' } })
    await goToStep(6)
    expect(screen.getByText('System includes AI/ML components')).toBeInTheDocument()
  })

  it('shows an informational note instead of a checkbox for MAESTRO', async () => {
    render(NewModel)
    await fireEvent.input(screen.getByLabelText('Model title'), { target: { value: 'Sys' } })
    await fireEvent.click(screen.getByRole('radio', { name: 'MAESTRO' }))
    await goToStep(6)
    expect(screen.getByText(/MAESTRO framework already generates/)).toBeInTheDocument()
    expect(screen.queryByText('System includes AI/ML components')).toBeNull()
  })
})

describe('NewModel — step 7 (review & submit)', () => {
  async function toReview({ title = 'My System' } = {}) {
    render(NewModel)
    await fireEvent.input(screen.getByLabelText('Model title'), { target: { value: title } })
    await goToStep(7)
  }

  it('shows a summary of the entered values', async () => {
    await toReview()
    expect(screen.getByText('My System')).toBeInTheDocument()
    expect(screen.getByText('STRIDE', { selector: 'dd' })).toBeInTheDocument()
  })

  it('warns when the configured provider has no API key set', async () => {
    config.set({ default_provider: 'anthropic', anthropic_api_key_set: false })
    await toReview()
    expect(screen.getByText(/No API key configured for anthropic/)).toBeInTheDocument()
    expect(screen.getByText('Create & Run')).toBeDisabled()
  })

  it('creates the model, subscribes to the run, and navigates to it', async () => {
    createModel.mockResolvedValue({ id: 'model-123' })
    await toReview()

    await fireEvent.click(screen.getByText('Create & Run'))

    await waitFor(() => expect(createModel).toHaveBeenCalledWith(
      expect.objectContaining({ title: 'My System', framework: 'STRIDE', iteration_count: 3 })
    ))
    await waitFor(() => expect(subscribeToRun).toHaveBeenCalled())
    expect(subscribeToRun.mock.calls[0][0]).toBe('model-123')
    await waitFor(() => expect(push).toHaveBeenCalledWith('/models/model-123'))
  })

  it('notifies and stops submitting when model creation fails', async () => {
    createModel.mockRejectedValue(new Error('validation failed'))
    await toReview()

    await fireEvent.click(screen.getByText('Create & Run'))

    await waitFor(() =>
      expect(notify).toHaveBeenCalledWith('error', expect.stringContaining('validation failed'))
    )
    expect(get(pipelineRunning)).toBe(false)
    expect(subscribeToRun).not.toHaveBeenCalled()
  })

  it('includes project_id from the current project when creating the model', async () => {
    currentProject.set({ id: 'proj-9' })
    createModel.mockResolvedValue({ id: 'model-456' })
    await toReview()

    await fireEvent.click(screen.getByText('Create & Run'))

    await waitFor(() =>
      expect(createModel).toHaveBeenCalledWith(expect.objectContaining({ project_id: 'proj-9' }))
    )
  })
})
